//! Метаданные CLI-сессий (`data/cli_sessions/`).

use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::error::Result;
use crate::paths::Paths;
use crate::working_memory::atomic_write_bytes;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionRecord {
    pub session_id: String,
    #[serde(default)]
    pub created_at: f64,
    #[serde(default)]
    pub updated_at: f64,
    #[serde(default = "default_transport")]
    pub transport: String,
    #[serde(flatten)]
    pub extra: Value,
}

fn default_transport() -> String {
    "cli".into()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LatestFile {
    active_session_id: String,
    updated_at: f64,
}

pub fn new_session_id() -> String {
    Uuid::new_v4().to_string()
}

pub fn is_uuid(s: &str) -> bool {
    Uuid::parse_str(s.trim()).is_ok()
}

pub fn normalize_session_id(s: &str) -> Result<String> {
    Uuid::parse_str(s.trim())
        .map(|u| u.to_string())
        .map_err(|_| crate::error::CoreError::WorkingMemory("некорректный UUID сессии".into()))
}

pub fn touch_session(paths: &Paths, session_id: &str) -> Result<SessionRecord> {
    let sid = session_id.trim().to_string();
    let path = paths.cli_session_path(&sid);
    let now = now_ts();
    let mut data: SessionRecord = if path.is_file() {
        fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or(SessionRecord {
                session_id: sid.clone(),
                created_at: now,
                updated_at: now,
                transport: "cli".into(),
                extra: Value::Null,
            })
    } else {
        SessionRecord {
            session_id: sid.clone(),
            created_at: now,
            updated_at: now,
            transport: "cli".into(),
            extra: Value::Null,
        }
    };
    data.session_id = sid;
    data.updated_at = now;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(&data)?;
    atomic_write_bytes(&path, json.as_bytes())?;
    Ok(data)
}

pub fn write_latest(paths: &Paths, session_id: &str) -> Result<()> {
    if let Some(parent) = paths.cli_session_latest_path().parent() {
        fs::create_dir_all(parent)?;
    }
    let payload = LatestFile {
        active_session_id: session_id.trim().to_string(),
        updated_at: now_ts(),
    };
    let json = serde_json::to_string_pretty(&payload)?;
    atomic_write_bytes(&paths.cli_session_latest_path(), json.as_bytes())
}

/// Все записи ``data/cli_sessions/*.json`` (кроме ``latest.json``), по убыванию ``updated_at``.
pub fn list_sessions(paths: &Paths) -> Result<Vec<SessionRecord>> {
    let dir = paths.cli_sessions_dir();
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    for entry in fs::read_dir(&dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        if path.file_name().and_then(|n| n.to_str()) == Some("latest.json") {
            continue;
        }
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        if let Ok(rec) = serde_json::from_str::<SessionRecord>(&text) {
            out.push(rec);
        }
    }
    out.sort_by(|a, b| {
        b.updated_at
            .partial_cmp(&a.updated_at)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    Ok(out)
}

pub fn read_latest(paths: &Paths) -> Option<String> {
    let text = fs::read_to_string(paths.cli_session_latest_path()).ok()?;
    let j: LatestFile = serde_json::from_str(&text).ok()?;
    let sid = j.active_session_id.trim();
    if sid.is_empty() {
        None
    } else {
        Some(sid.to_string())
    }
}

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

const BUDGET_HISTORY_KEY: &str = "budget_history";
const BUDGET_HISTORY_MAX: usize = 48;

/// Точка тренда заполнения контекста для сессии (хранится в ``extra`` JSON сессии).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BudgetSnapshot {
    pub ts: f64,
    pub total_chars: u64,
    pub total_budget: u64,
    pub approx_prompt_tokens: u64,
    /// Процент от лимита; ``None`` если бюджет не задан.
    pub fill_pct: Option<f64>,
}

impl BudgetSnapshot {
    pub fn from_usage(total_chars: u64, total_budget: u64, approx_prompt_tokens: u64) -> Self {
        let fill_pct = if total_budget > 0 {
            Some((total_chars as f64 / total_budget as f64) * 100.0)
        } else {
            None
        };
        Self {
            ts: now_ts(),
            total_chars,
            total_budget,
            approx_prompt_tokens,
            fill_pct,
        }
    }
}

/// Добавить снимок в ``data/cli_sessions/<id>.json`` (поле ``budget_history``).
pub fn append_session_budget_snapshot(
    paths: &Paths,
    session_id: &str,
    snap: BudgetSnapshot,
) -> Result<()> {
    let path = paths.cli_session_path(session_id);
    let now = now_ts();
    let mut data: SessionRecord = if path.is_file() {
        fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or(SessionRecord {
                session_id: session_id.to_string(),
                created_at: now,
                updated_at: now,
                transport: "eidos".into(),
                extra: Value::Null,
            })
    } else {
        SessionRecord {
            session_id: session_id.to_string(),
            created_at: now,
            updated_at: now,
            transport: "eidos".into(),
            extra: Value::Null,
        }
    };
    let mut extra = match data.extra {
        Value::Object(map) => Value::Object(map),
        _ => serde_json::Map::new().into(),
    };
    let obj = extra.as_object_mut().expect("object");
    let hist = obj
        .entry(BUDGET_HISTORY_KEY)
        .or_insert_with(|| Value::Array(Vec::new()));
    let arr = hist.as_array_mut().expect("array");
    arr.push(serde_json::to_value(&snap)?);
    if arr.len() > BUDGET_HISTORY_MAX {
        let drop = arr.len() - BUDGET_HISTORY_MAX;
        arr.drain(0..drop);
    }
    data.extra = extra;
    data.updated_at = now;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(&data)?;
    atomic_write_bytes(&path, json.as_bytes())?;
    Ok(())
}

/// История снимков бюджета для сессии (от старых к новым).
pub fn read_session_budget_history(paths: &Paths, session_id: &str) -> Result<Vec<BudgetSnapshot>> {
    let path = paths.cli_session_path(session_id);
    if !path.is_file() {
        return Ok(Vec::new());
    }
    let text = fs::read_to_string(&path)?;
    let data: SessionRecord = serde_json::from_str(&text)?;
    let Some(arr) = data.extra.get(BUDGET_HISTORY_KEY).and_then(|v| v.as_array()) else {
        return Ok(Vec::new());
    };
    let mut out = Vec::new();
    for item in arr {
        if let Ok(s) = serde_json::from_value::<BudgetSnapshot>(item.clone()) {
            out.push(s);
        }
    }
    Ok(out)
}
