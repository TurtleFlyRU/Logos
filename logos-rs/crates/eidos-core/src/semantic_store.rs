//! Semantic SQLite (`knowledge.db`) — parity с ``kernel.memory.SemanticMemory``.

use std::path::Path;

use rusqlite::{Connection, OptionalExtension, Row};
use serde_json::{json, Value};

use eidos_protocol::semantic::SemanticPrinciple;

use crate::error::{CoreError, Result};
use crate::paths::Paths;

const INIT_SQL: &str = r"
            CREATE TABLE IF NOT EXISTS principles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                principle TEXT NOT NULL UNIQUE,
                source_episode_ids TEXT,
                confidence REAL DEFAULT 0.5,
                created_at REAL,
                updated_at REAL,
                last_retrieved_at REAL,
                retrieval_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                next_review_at REAL,
                decay REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_principles_confidence ON principles(confidence);
";

pub struct SemanticStore {
    conn: Connection,
}

impl SemanticStore {
    pub fn open(paths: &Paths) -> Result<Self> {
        let p = paths.semantic_db_path();
        if let Some(parent) = p.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                CoreError::WorkingMemory(format!("semantic dir: {e}"))
            })?;
        }
        let conn = Connection::open(&p)?;
        let s = Self { conn };
        s.init_schema()?;
        Ok(s)
    }

    pub fn open_path(db_path: &Path) -> Result<Self> {
        if let Some(parent) = db_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                CoreError::WorkingMemory(format!("semantic dir: {e}"))
            })?;
        }
        let conn = Connection::open(db_path)?;
        let s = Self { conn };
        s.init_schema()?;
        Ok(s)
    }

    fn init_schema(&self) -> Result<()> {
        self.conn.execute_batch(INIT_SQL)?;
        self.ensure_column("last_retrieved_at", "REAL")?;
        self.ensure_column("retrieval_count", "INTEGER DEFAULT 0")?;
        self.ensure_column("success_count", "INTEGER DEFAULT 0")?;
        self.ensure_column("next_review_at", "REAL")?;
        self.ensure_column("decay", "REAL DEFAULT 0.0")?;
        Ok(())
    }

    fn ensure_column(&self, name: &str, definition: &str) -> Result<()> {
        let mut stmt = self.conn.prepare("PRAGMA table_info(principles)")?;
        let exists = stmt
            .query_map([], |row| row.get::<_, String>(1))?
            .filter_map(std::result::Result::ok)
            .any(|n| n == name);
        if exists {
            return Ok(());
        }
        let sql = format!("ALTER TABLE principles ADD COLUMN {name} {definition}");
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

    /// Как ``SemanticMemory.get_principles``.
    pub fn get_principles(&self, min_confidence: f64, limit: usize) -> Result<Vec<SemanticPrinciple>> {
        let lim = i64::try_from(limit).unwrap_or(i64::MAX);
        let mut stmt = self.conn.prepare(
            "SELECT * FROM principles WHERE confidence >= ?1 ORDER BY confidence DESC LIMIT ?2",
        )?;
        let col_names = stmt
            .column_names()
            .iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>();
        let rows = stmt.query_map(rusqlite::params![min_confidence, lim], |row| {
            principle_from_row(row, &col_names)
        })?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    pub fn count(&self) -> Result<i64> {
        let n: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM principles", [], |row| row.get(0))?;
        Ok(n)
    }

    pub fn get_by_id(&self, id: i64) -> Result<Option<SemanticPrinciple>> {
        let mut stmt = self.conn.prepare("SELECT * FROM principles WHERE id = ?1")?;
        let col_names = stmt
            .column_names()
            .iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>();
        let row = stmt
            .query_row(rusqlite::params![id], |row| principle_from_row(row, &col_names))
            .optional()?;
        Ok(row)
    }

    /// Вставка / upsert (как ``SemanticMemory.store_principle``).
    pub fn store_principle(
        &self,
        principle: &str,
        source_ids: &[i64],
        confidence: f64,
    ) -> Result<()> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let src = serde_json::to_string(source_ids)?;
        self.conn.execute(
            r"INSERT INTO principles (principle, source_episode_ids, confidence, created_at, updated_at)
               VALUES (?1, ?2, ?3, ?4, ?5)
               ON CONFLICT(principle) DO UPDATE SET
                   confidence = MAX(confidence, excluded.confidence),
                   source_episode_ids = excluded.source_episode_ids,
                   updated_at = excluded.updated_at,
                   next_review_at = NULL",
            rusqlite::params![principle, src, confidence, now, now],
        )?;
        Ok(())
    }
}

fn col_idx(names: &[String], key: &str) -> Option<usize> {
    names.iter().position(|n| n == key)
}

fn parse_episode_ids(raw: Option<&str>) -> Vec<i64> {
    let Some(s) = raw.filter(|t| !t.trim().is_empty()) else {
        return vec![];
    };
    serde_json::from_str::<Vec<i64>>(s).unwrap_or_default()
}

fn principle_from_row(row: &Row, col_names: &[String]) -> rusqlite::Result<SemanticPrinciple> {
    let mut p = SemanticPrinciple {
        id: None,
        principle: String::new(),
        source_episode_ids: vec![],
        confidence: 0.0,
        created_at: None,
        updated_at: None,
        last_retrieved_at: None,
        retrieval_count: None,
        success_count: None,
        next_review_at: None,
        decay: None,
        extra: json!({}),
    };

    let known: &[&str] = &[
        "id",
        "principle",
        "source_episode_ids",
        "confidence",
        "created_at",
        "updated_at",
        "last_retrieved_at",
        "retrieval_count",
        "success_count",
        "next_review_at",
        "decay",
    ];
    let known_set: std::collections::HashSet<&str> = known.iter().copied().collect();
    let mut extra_map = serde_json::Map::new();

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
        p.id = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "principle") {
        p.principle = row.get::<_, Option<String>>(i)?.unwrap_or_default();
    }
    if let Some(i) = col_idx(col_names, "source_episode_ids") {
        let t: Option<String> = row.get(i)?;
        p.source_episode_ids = parse_episode_ids(t.as_deref());
    }
    if let Some(i) = col_idx(col_names, "confidence") {
        p.confidence = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "created_at") {
        p.created_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "updated_at") {
        p.updated_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "last_retrieved_at") {
        p.last_retrieved_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "retrieval_count") {
        p.retrieval_count = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "success_count") {
        p.success_count = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "next_review_at") {
        p.next_review_at = row.get(i)?;
    }
    if let Some(i) = col_idx(col_names, "decay") {
        p.decay = row.get(i)?;
    }

    p.extra = Value::Object(extra_map);
    Ok(p)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn roundtrip_principle() {
        let dir = std::env::temp_dir().join(format!(
            "eidos_semantic_test_{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let db = dir.join("knowledge.db");
        let store = SemanticStore::open_path(&db).expect("open");
        store
            .store_principle("test principle", &[1, 2], 0.9)
            .expect("store");
        let rows = store.get_principles(0.1, 10).expect("get");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].principle, "test principle");
        assert_eq!(rows[0].source_episode_ids, vec![1_i64, 2]);
    }
}
