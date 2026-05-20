//! Семантическая память (строка SQLite `principles`).

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Принцип из таблицы ``principles`` (parity ``kernel.memory.SemanticMemory``).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticPrinciple {
    #[serde(default)]
    pub id: Option<i64>,
    pub principle: String,
    #[serde(default)]
    pub source_episode_ids: Vec<i64>,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default)]
    pub created_at: Option<f64>,
    #[serde(default)]
    pub updated_at: Option<f64>,
    #[serde(default)]
    pub last_retrieved_at: Option<f64>,
    #[serde(default)]
    pub retrieval_count: Option<i64>,
    #[serde(default)]
    pub success_count: Option<i64>,
    #[serde(default)]
    pub next_review_at: Option<f64>,
    #[serde(default)]
    pub decay: Option<f64>,
    #[serde(flatten)]
    pub extra: Value,
}
