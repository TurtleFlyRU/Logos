//! Ошибки ядра.

use std::path::PathBuf;

use thiserror::Error;

#[derive(Debug, Error)]
pub enum CoreError {
    #[error("конфигурация LLM: {0}")]
    LlmConfig(String),

    #[error("HTTP: {0}")]
    Http(#[from] reqwest::Error),

    #[error("JSON: {0}")]
    Json(#[from] serde_json::Error),

    #[error("YAML: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("IO: {0}")]
    Io(#[from] std::io::Error),

    #[error("пути: {0}")]
    Paths(#[from] crate::paths::PathsError),

    #[error("инструмент: {0}")]
    Tool(String),

    #[error("рабочая память: {0}")]
    WorkingMemory(String),

    #[error("файл не найден: {0}")]
    NotFound(PathBuf),

    #[error("Python sidecar: {0}")]
    Sidecar(String),

    #[error("SQLite: {0}")]
    Sqlite(#[from] rusqlite::Error),
}

pub type Result<T> = std::result::Result<T, CoreError>;
