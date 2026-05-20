//! Эпизодическая память (строка SQLite `episodes`).

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EpisodicEpisode {
    #[serde(default)]
    pub id: Option<i64>,
    pub timestamp: f64,
    #[serde(default)]
    pub session_id: Option<String>,
    #[serde(default)]
    pub salience: f64,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub summary: String,
    pub raw_text: String,
    #[serde(default)]
    pub compressed: String,
    #[serde(default)]
    pub linked_episodes: Vec<i64>,
    #[serde(default)]
    pub context_keys: Vec<String>,
    #[serde(default)]
    pub project: Option<String>,
    #[serde(default)]
    pub task: Option<String>,
    #[serde(default)]
    pub outcome: Option<String>,
    #[serde(default)]
    pub tools: Option<Value>,
    #[serde(default)]
    pub tools_used: Option<Value>,
    #[serde(default)]
    pub valid_until: Option<f64>,
    #[serde(default)]
    pub access_count: Option<i64>,
    #[serde(default)]
    pub last_accessed_at: Option<f64>,
    #[serde(default)]
    pub archived_at: Option<f64>,
    #[serde(default)]
    pub forget_reason: Option<String>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub source_id: Option<String>,
    #[serde(flatten)]
    pub extra: Value,
}
