//! Клиент ML sidecar (HTTP). См. ``sidecars/eidos-ml/`` и ``docs/MIGRATION_RUST_TAURI.md``.

use std::time::Duration;

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::external_store::search_external_lexical;
use crate::journal_search::{hits_to_json, search_journal_lexical};
use crate::paths::Paths;

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

fn http_client() -> Result<reqwest::blocking::Client> {
    let mut builder = reqwest::blocking::Client::builder().timeout(Duration::from_secs(60));
    if !crate::agents::http_use_proxy() {
        builder = builder.no_proxy();
    }
    builder
        .build()
        .map_err(|e| CoreError::Tool(format!("http client: {e}")))
}

fn ml_post_json(path: &str, body: &Value) -> Result<Value> {
    let base = ml_sidecar_base_url()
        .ok_or_else(|| CoreError::Tool("не задан EIDOS_ML_SIDECAR_URL".into()))?;
    let url = format!("{base}{path}");
    let client = http_client()?;
    let resp = client
        .post(&url)
        .json(body)
        .send()
        .map_err(|e| CoreError::Tool(format!("ML sidecar POST {url}: {e}")))?;
    if !resp.status().is_success() {
        return Err(CoreError::Tool(format!(
            "ML sidecar {}: {}",
            resp.status(),
            resp.text().unwrap_or_default()
        )));
    }
    resp.json()
        .map_err(|e| CoreError::Tool(format!("ML sidecar JSON: {e}")))
}

/// `GET {base}/health` — текст ответа или ошибка сети/HTTP.
pub fn ml_sidecar_health_check() -> Result<String> {
    let base = ml_sidecar_base_url()
        .ok_or_else(|| CoreError::Tool("не задан EIDOS_ML_SIDECAR_URL".into()))?;
    let url = format!("{base}/health");
    let client = http_client()?;
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

/// Journal search: ML sidecar → лексический fallback.
pub fn search_journal_hits(paths: &Paths, query: &str, top_k: usize) -> Result<Vec<Value>> {
    if ml_sidecar_configured() {
        if let Ok(v) = ml_post_json(
            "/search/journal",
            &json!({ "query": query, "top_k": top_k }),
        ) {
            if let Some(arr) = v.get("hits").and_then(|h| h.as_array()) {
                if !arr.is_empty() {
                    return Ok(arr.clone());
                }
            }
        }
    }
    let hits = search_journal_lexical(paths, query, top_k)?;
    Ok(hits_to_json(&hits))
}

/// External search: ML sidecar → лексический fallback.
pub fn search_external_hits(
    paths: &Paths,
    query: &str,
    top_k: usize,
    min_score: f64,
) -> Result<Value> {
    if ml_sidecar_configured() {
        if let Ok(v) = ml_post_json(
            "/search/external",
            &json!({ "query": query, "top_k": top_k, "min_score": min_score }),
        ) {
            if v.get("hits")
                .and_then(|h| h.as_array())
                .is_some_and(|a| !a.is_empty())
            {
                return Ok(v);
            }
        }
    }
    let mut out = search_external_lexical(paths, query, top_k)?;
    if let Some(hits) = out.get_mut("hits").and_then(|h| h.as_array_mut()) {
        hits.retain(|h| {
            h.get("score")
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0)
                >= min_score
        });
        out["count"] = json!(hits.len());
    }
    Ok(out)
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
