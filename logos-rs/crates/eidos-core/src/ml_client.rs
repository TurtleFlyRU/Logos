//! Заготовка клиента ML sidecar (HTTP). См. ``docs/MIGRATION_RUST_TAURI.md`` — ``eidos-ml``.

use std::time::Duration;

use crate::error::{CoreError, Result};

/// Базовый URL, например `http://127.0.0.1:8765` (без завершающего `/`).
pub fn ml_sidecar_base_url() -> Option<String> {
    let raw = std::env::var("EIDOS_ML_SIDECAR_URL")
        .or_else(|_| std::env::var("EIDOS_ML_BASE"))
        .unwrap_or_default();
    let t = raw.trim();
    if t.is_empty() {
        return None;
    }
    Some(t.trim_end_matches('/').to_string())
}

/// Настроен ли URL sidecar.
#[must_use]
pub fn ml_sidecar_configured() -> bool {
    ml_sidecar_base_url().is_some()
}

/// `GET {base}/health` — текст ответа или ошибка сети/HTTP.
pub fn ml_sidecar_health_check() -> Result<String> {
    let base = ml_sidecar_base_url()
        .ok_or_else(|| CoreError::Tool("не задан EIDOS_ML_SIDECAR_URL".into()))?;
    let url = format!("{base}/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| CoreError::Tool(format!("http client: {e}")))?;
    let resp = client
        .get(&url)
        .send()
        .map_err(|e| CoreError::Tool(format!("ML sidecar GET {url}: {e}")))?;
    if !resp.status().is_success() {
        return Err(CoreError::Tool(format!(
            "ML sidecar {}: {}",
            resp.status(),
            resp.text().unwrap_or_default()
        )));
    }
    resp.text()
        .map_err(|e| CoreError::Tool(format!("ML sidecar body: {e}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn not_configured_by_default() {
        std::env::remove_var("EIDOS_ML_SIDECAR_URL");
        std::env::remove_var("EIDOS_ML_BASE");
        assert!(!ml_sidecar_configured());
    }
}
