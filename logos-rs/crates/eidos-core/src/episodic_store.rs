//! Эпизодическая память SQLite — parity с ``kernel.memory.EpisodicMemory`` (схема и базовые запросы).

use std::path::Path;

use rusqlite::{Connection, OptionalExtension, Row};
use serde_json::{json, Value};

use eidos_protocol::episodic::EpisodicEpisode;

use crate::error::{CoreError, Result};
use crate::paths::Paths;

const INIT_SQL: &str = r"
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT,
                salience REAL DEFAULT 0.0,
                tags TEXT,
                summary TEXT,
                raw_text TEXT,
                compressed TEXT,
                linked_episodes TEXT,
                context_keys TEXT,
                project TEXT,
                task TEXT,
                outcome TEXT,
                tools TEXT,
                tools_used TEXT,
                valid_until REAL,
                access_count INTEGER DEFAULT 0,
                last_accessed_at REAL,
                archived_at REAL,
                forget_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodes_salience ON episodes(salience);
";

/// Доступ к ``data/episodic/episodes.db``.
pub struct EpisodicStore {
    conn: Connection,
}

impl EpisodicStore {
    /// Открыть или создать БД, применить схему как в Python.
    pub fn open(paths: &Paths) -> Result<Self> {
        let p = paths.episodic_db_path();
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                CoreError::WorkingMemory(format!("episodic dir: {e}"))
            })?;
        }
        let conn = Connection::open(&p)?;
        let s = Self { conn };
        s.init_schema()?;
        Ok(s)
    }

    /// Открыть по явному пути (тесты).
    pub fn open_path(db_path: &Path) -> Result<Self> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                CoreError::WorkingMemory(format!("episodic dir: {e}"))
            })?;
        }
        let conn = Connection::open(db_path)?;
        let s = Self { conn };
        s.init_schema()?;
        Ok(s)
    }

    fn init_schema(&self) -> Result<()> {
        self.conn.execute_batch(INIT_SQL)?;
        self.ensure_column("context_keys", "TEXT")?;
        self.ensure_column("project", "TEXT")?;
        self.ensure_column("task", "TEXT")?;
        self.ensure_column("outcome", "TEXT")?;
        self.ensure_column("tools", "TEXT")?;
        self.ensure_column("tools_used", "TEXT")?;
        self.ensure_column("valid_until", "REAL")?;
        self.ensure_column("access_count", "INTEGER DEFAULT 0")?;
        self.ensure_column("last_accessed_at", "REAL")?;
        self.ensure_column("archived_at", "REAL")?;
        self.ensure_column("forget_reason", "TEXT")?;
        self.ensure_column("source", "TEXT")?;
        self.ensure_column("source_id", "TEXT")?;
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_source ON episodes(source)",
            [],
        )?;
        Ok(())
    }

    fn ensure_column(&self, name: &str, definition: &str) -> Result<()> {
        let mut stmt = self.conn.prepare("PRAGMA table_info(episodes)")?;
        let exists = stmt
            .query_map([], |row| row.get::<_, String>(1))?
            .filter_map(std::result::Result::ok)
            .any(|n| n == name);
        if exists {
            return Ok(());
        }
        let sql = format!("ALTER TABLE episodes ADD COLUMN {name} {definition}");
        match self.conn.execute(&sql, []) {
            Ok(_) => Ok(()),
            Err(e) => {
                let msg = e.to_string().to_lowercase();
                if msg.contains("duplicate column") {
                    Ok(())
                } else {
                    Err(e.into())
                }
            }
        }
    }

    /// Последние эпизоды (как ``EpisodicMemory.query``).
    pub fn query(&self, limit: usize, min_salience: f64) -> Result<Vec<EpisodicEpisode>> {
        let limit_i = i64::try_from(limit).unwrap_or(i64::MAX);
        let mut stmt = self.conn.prepare(
            "SELECT * FROM episodes WHERE salience >= ?1 ORDER BY timestamp DESC LIMIT ?2",
        )?;
        let col_names = stmt
            .column_names()
            .iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>();
        let rows = stmt.query_map(rusqlite::params![min_salience, limit_i], |row| {
            episode_from_row(row, &col_names)
        })?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    /// Вставка строки (как ``EpisodicMemory.store``).
    pub fn store(&self, episode: &EpisodicEpisode) -> Result<i64> {
        let tags = serde_json::to_string(&episode.tags)?;
        let linked = serde_json::to_string(&episode.linked_episodes)?;
        let ctx_keys = serde_json::to_string(&episode.context_keys)?;
        let tools_json = episode
            .tools
            .as_ref()
            .map(serde_json::to_string)
            .transpose()?
            .unwrap_or_else(|| "[]".to_string());
        let tools_used_json = episode
            .tools_used
            .as_ref()
            .map(serde_json::to_string)
            .transpose()?
            .unwrap_or_else(|| "[]".to_string());

        self.conn.execute(
            "INSERT INTO episodes (
                   timestamp, session_id, salience, tags, summary, raw_text,
                   compressed, linked_episodes, context_keys, project, task,
                   outcome, tools, tools_used, valid_until, access_count, last_accessed_at,
                   archived_at, forget_reason, source, source_id
               )
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21)",
            rusqlite::params![
                episode.timestamp,
                episode.session_id,
                episode.salience,
                tags,
                episode.summary,
                episode.raw_text,
                episode.compressed,
                linked,
                ctx_keys,
                episode.project,
                episode.task,
                episode.outcome,
                tools_json,
                tools_used_json,
                episode.valid_until,
                episode.access_count.unwrap_or(0),
                episode.last_accessed_at,
                episode.archived_at,
                episode.forget_reason,
                episode.source,
                episode.source_id,
            ],
        )?;
        Ok(self.conn.last_insert_rowid())
    }

    /// Одна запись по id.
    pub fn get_by_id(&self, id: i64) -> Result<Option<EpisodicEpisode>> {
        let mut stmt = self.conn.prepare("SELECT * FROM episodes WHERE id = ?1")?;
        let col_names = stmt
            .column_names()
            .iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>();
        let row = stmt
            .query_row(rusqlite::params![id], |row| episode_from_row(row, &col_names))
            .optional()?;
        Ok(row)
    }

    /// Число строк (диагностика).
    pub fn count(&self) -> Result<i64> {
        let n: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM episodes", [], |row| row.get(0))?;
        Ok(n)
    }
}

fn col_idx(names: &[String], key: &str) -> Option<usize> {
    names.iter().position(|n| n == key)
}

fn episode_from_row(row: &Row, col_names: &[String]) -> rusqlite::Result<EpisodicEpisode> {
    let mut episode = EpisodicEpisode {
        id: None,
        timestamp: 0.0,
        session_id: None,
        salience: 0.0,
        tags: vec![],
        summary: String::new(),
        raw_text: String::new(),
        compressed: String::new(),
        linked_episodes: vec![],
        context_keys: vec![],
        project: None,
        task: None,
        outcome: None,
        tools: None,
        tools_used: None,
        valid_until: None,
        access_count: None,
        last_accessed_at: None,
        archived_at: None,
        forget_reason: None,
        source: None,
        source_id: None,
        extra: json!({}),
    };

    let mut extra_map = serde_json::Map::new();
    let known: &[&str] = &[
        "id",
        "timestamp",
        "session_id",
        "salience",
        "tags",
        "summary",
        "raw_text",
        "compressed",
        "linked_episodes",
        "context_keys",
        "project",
        "task",
        "outcome",
        "tools",
        "tools_used",
        "valid_until",
        "access_count",
        "last_accessed_at",
        "archived_at",
        "forget_reason",
        "source",
        "source_id",
    ];
    let known_set: std::collections::HashSet<&str> = known.iter().copied().collect();

    for (i, name) in col_names.iter().enumerate() {
        if known_set.contains(name.as_str()) {
            continue;
        }
        let s: rusqlite::Result<Option<String>> = row.get(i);
        if let Ok(Some(val)) = s {
            if !val.is_empty() {
                extra_map.insert(name.clone(), Value::String(val));
            }
        }
    }

    if let Some(i) = col_idx(col_names, "id") {
        episode.id = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "timestamp") {
        episode.timestamp = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "session_id") {
        episode.session_id = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "salience") {
        episode.salience = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "tags") {
        let t: Option<String> = row.get(i)?;
        episode.tags = parse_json_str_to_string_vec(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "summary") {
        episode.summary = row.get::<_, Option<String>>(i)?.unwrap_or_default();
    }
    if let Some(i) = col_idx(col_names, "raw_text") {
        episode.raw_text = row.get::<_, Option<String>>(i)?.unwrap_or_default();
    }
    if let Some(i) = col_idx(col_names, "compressed") {
        episode.compressed = row.get::<_, Option<String>>(i)?.unwrap_or_default();
    }
    if let Some(i) = col_idx(col_names, "linked_episodes") {
        let t: Option<String> = row.get(i)?;
        episode.linked_episodes = parse_json_linked(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "context_keys") {
        let t: Option<String> = row.get(i)?;
        episode.context_keys = parse_json_str_to_string_vec(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "project") {
        episode.project = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "task") {
        episode.task = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "outcome") {
        episode.outcome = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "tools") {
        let t: Option<String> = row.get(i)?;
        episode.tools = parse_json_value(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "tools_used") {
        let t: Option<String> = row.get(i)?;
        episode.tools_used = parse_json_value(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "valid_until") {
        episode.valid_until = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "access_count") {
        episode.access_count = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "last_accessed_at") {
        episode.last_accessed_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "archived_at") {
        episode.archived_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "forget_reason") {
        episode.forget_reason = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "source") {
        episode.source = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "source_id") {
        episode.source_id = row.get(i)?;
    }

    episode.extra = Value::Object(extra_map);
    Ok(episode)
}

fn parse_json_str_to_string_vec(raw: Option<&str>) -> Vec<String> {
    let Some(s) = raw.filter(|t| !t.trim().is_empty()) else {
        return vec![];
    };
    serde_json::from_str::<Vec<String>>(s).unwrap_or_default()
}

fn parse_json_linked(raw: Option<&str>) -> Vec<i64> {
    let Some(s) = raw.filter(|t| !t.trim().is_empty()) else {
        return vec![];
    };
    serde_json::from_str::<Vec<i64>>(s).unwrap_or_default()
}

fn parse_json_value(raw: Option<&str>) -> Option<Value> {
    let s = raw?.trim();
    if s.is_empty() {
        return None;
    }
    serde_json::from_str(s).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn roundtrip_store_query() {
        let dir = std::env::temp_dir().join(format!(
            "eidos_episodic_test_{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let db = dir.join("episodes.db");
        let store = EpisodicStore::open_path(&db).expect("open");
        let ep = EpisodicEpisode {
            id: None,
            timestamp: 1700000000.0,
            session_id: Some("sess-1".into()),
            salience: 0.8,
            tags: vec!["cli".into()],
            summary: "hello".into(),
            raw_text: "full".into(),
            compressed: String::new(),
            linked_episodes: vec![],
            context_keys: vec![],
            project: None,
            task: None,
            outcome: None,
            tools: None,
            tools_used: None,
            valid_until: None,
            access_count: Some(0),
            last_accessed_at: None,
            archived_at: None,
            forget_reason: None,
            source: None,
            source_id: None,
            extra: json!({}),
        };
        let id = store.store(&ep).expect("store");
        assert!(id > 0);
        let rows = store.query(10, 0.0).expect("query");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].summary, "hello");
        assert_eq!(rows[0].id, Some(id));
        let one = store.get_by_id(id).expect("get").expect("row");
        assert_eq!(one.raw_text, "full");
    }
}
