//! On-demand memory tools (P2): Rust fallback when Python sidecar unavailable.

use std::fs;
use serde_json::{json, Value};

use crate::episodic_store::EpisodicStore;
use crate::error::{CoreError, Result};
use crate::paths::Paths;
use crate::semantic_store::SemanticStore;

const MAX_EPISODE_BODY: usize = 48_000;
const MAX_JOURNAL_FILE: usize = 64_000;

pub fn memory_tools_enabled() -> bool {
    let v = std::env::var("EIDOS_TOOLS")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    if matches!(v.as_str(), "0" | "false" | "no" | "off") {
        return false;
    }
    let m = std::env::var("EIDOS_MEMORY_TOOLS")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    !matches!(m.as_str(), "0" | "false" | "no" | "off")
}

pub fn is_memory_tool_name(name: &str) -> bool {
    name.starts_with("memory_")
}

pub fn memory_tool_specs() -> Vec<Value> {
    vec![
        json!({
            "type": "function",
            "function": {
                "name": "memory_search_episodic",
                "description": "Поиск в episodic SQLite (Rust fallback; без external vectors).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": { "type": "string" },
                        "limit": { "type": "integer" }
                    }
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "memory_get_episode",
                "description": "Эпизод по id.",
                "parameters": {
                    "type": "object",
                    "properties": { "episode_id": { "type": "integer" } },
                    "required": ["episode_id"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "memory_list_semantic",
                "description": "Список принципов semantic DB.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": { "type": "string" },
                        "limit": { "type": "integer" }
                    }
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "memory_search_journal",
                "description": "Лексический поиск по journal/*.md (Rust).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": { "type": "string" },
                        "top_k": { "type": "integer" }
                    },
                    "required": ["query"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "memory_read_journal",
                "description": "Прочитать файл дневника.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": { "type": "string" },
                        "max_chars": { "type": "integer" }
                    },
                    "required": ["filename"]
                }
            }
        }),
    ]
}

pub fn execute_memory_tool(paths: &Paths, name: &str, arguments_json: &str) -> String {
    match execute_memory_tool_inner(paths, name, arguments_json) {
        Ok(v) => serde_json::to_string(&v).unwrap_or_else(|e| json!({ "error": e.to_string() }).to_string()),
        Err(e) => json!({ "error": e.to_string() }).to_string(),
    }
}

fn execute_memory_tool_inner(paths: &Paths, name: &str, arguments_json: &str) -> Result<Value> {
    let args: Value = serde_json::from_str(arguments_json).unwrap_or(json!({}));
    match name {
        "memory_search_episodic" => search_episodic(paths, &args),
        "memory_get_episode" => get_episode(paths, &args),
        "memory_list_semantic" => list_semantic(paths, &args),
        "memory_search_journal" => search_journal(paths, &args),
        "memory_read_journal" => read_journal(paths, &args),
        "memory_search_external" => Ok(json!({
            "error": "external search requires Python sidecar (vectors)",
            "hits": []
        })),
        _ => Err(CoreError::Tool(format!("неизвестный memory tool: {name}"))),
    }
}

fn search_episodic(paths: &Paths, args: &Value) -> Result<Value> {
    let store = EpisodicStore::open(paths)?;
    let limit = args
        .get("limit")
        .and_then(|v| v.as_u64())
        .unwrap_or(20)
        .clamp(1, 80) as usize;
    let query = args
        .get("query")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let mut hits = if query.is_empty() {
        store.query(limit, 0.0)?
    } else {
        let pool = store.query(5000, 0.0)?;
        pool.into_iter()
            .filter(|ep| {
                let body = format!("{} {}", ep.summary, ep.raw_text).to_lowercase();
                body.contains(&query)
            })
            .take(limit)
            .collect()
    };
    let episodes: Vec<Value> = hits
        .drain(..)
        .map(|ep| {
            json!({
                "id": ep.id,
                "timestamp": ep.timestamp,
                "salience": ep.salience,
                "summary": truncate_str(&ep.summary, 1200),
                "raw_text": truncate_str(&ep.raw_text, 1200),
            })
        })
        .collect();
    Ok(json!({ "count": episodes.len(), "episodes": episodes, "backend": "rust" }))
}

fn get_episode(paths: &Paths, args: &Value) -> Result<Value> {
    let id = args
        .get("episode_id")
        .and_then(|v| v.as_i64())
        .ok_or_else(|| CoreError::Tool("episode_id required".into()))?;
    let store = EpisodicStore::open(paths)?;
    let ep = store
        .get_by_id(id)?
        .ok_or_else(|| CoreError::Tool(format!("episode {id} not found")))?;
    Ok(json!({
        "episode": {
            "id": ep.id,
            "timestamp": ep.timestamp,
            "summary": truncate_str(&ep.summary, MAX_EPISODE_BODY),
            "raw_text": truncate_str(&ep.raw_text, MAX_EPISODE_BODY),
        },
        "backend": "rust"
    }))
}

fn list_semantic(paths: &Paths, args: &Value) -> Result<Value> {
    let store = SemanticStore::open(paths)?;
    let limit = args
        .get("limit")
        .and_then(|v| v.as_u64())
        .unwrap_or(24)
        .clamp(1, 100) as usize;
    let query = args
        .get("query")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let mut rows = store.get_principles(0.0, 500)?;
    if !query.is_empty() {
        rows.retain(|r| r.principle.to_lowercase().contains(&query));
    }
    rows.truncate(limit);
    let principles: Vec<Value> = rows
        .iter()
        .map(|r| {
            json!({
                "id": r.id,
                "principle": truncate_str(&r.principle, 2000),
                "confidence": r.confidence,
            })
        })
        .collect();
    Ok(json!({ "count": principles.len(), "principles": principles, "backend": "rust" }))
}

fn search_journal(paths: &Paths, args: &Value) -> Result<Value> {
    let query = args
        .get("query")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    if query.is_empty() {
        return Err(CoreError::Tool("query required".into()));
    }
    let top_k = args
        .get("top_k")
        .and_then(|v| v.as_u64())
        .unwrap_or(12)
        .clamp(1, 30) as usize;
    let dir = paths.journal_dir();
    let mut hits: Vec<Value> = Vec::new();
    if dir.is_dir() {
        for ent in fs::read_dir(&dir).map_err(|e| CoreError::WorkingMemory(e.to_string()))? {
            let ent = ent.map_err(|e| CoreError::WorkingMemory(e.to_string()))?;
            let path = ent.path();
            if path.extension().and_then(|e| e.to_str()) != Some("md") {
                continue;
            }
            if path.file_name().and_then(|n| n.to_str()) == Some("INDEX.md") {
                continue;
            }
            let text = fs::read_to_string(&path).unwrap_or_default().to_lowercase();
            if text.contains(&query) {
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("?");
                hits.push(json!({ "file": name, "snippet": query }));
            }
            if hits.len() >= top_k {
                break;
            }
        }
    }
    Ok(json!({ "count": hits.len(), "hits": hits, "backend": "rust_lexical" }))
}

fn read_journal(paths: &Paths, args: &Value) -> Result<Value> {
    let mut name = args
        .get("filename")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .replace('\\', "/");
    if name.is_empty() || name.contains("..") {
        return Err(CoreError::Tool("filename required".into()));
    }
    if !name.ends_with(".md") {
        name.push_str(".md");
    }
    let path = paths.journal_dir().join(&name);
    let canon = path.canonicalize().map_err(|_| CoreError::NotFound(path.clone()))?;
    let dir = paths
        .journal_dir()
        .canonicalize()
        .unwrap_or_else(|_| paths.journal_dir());
    if !canon.starts_with(&dir) {
        return Err(CoreError::Tool("path outside journal".into()));
    }
    let text = fs::read_to_string(&canon).map_err(|_| CoreError::NotFound(path))?;
    let max_chars = args
        .get("max_chars")
        .and_then(|v| v.as_u64())
        .unwrap_or(MAX_JOURNAL_FILE as u64)
        .clamp(1000, 200_000) as usize;
    let truncated = text.len() > max_chars;
    let content = if truncated {
        format!("{}…", &text[..max_chars.saturating_sub(1)])
    } else {
        text
    };
    Ok(json!({
        "filename": name,
        "chars": content.len(),
        "truncated": truncated,
        "content": content,
        "backend": "rust"
    }))
}

fn truncate_str(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max.saturating_sub(1)])
    }
}

/// Краткая справка для ``/memory`` (без Python).
pub fn format_memory_help_rust() -> String {
    let tools = memory_tools_enabled();
    let mut lines = vec![
        "Память Эйдос (справка)".to_string(),
        String::new(),
        "Пассивно: блок active_memory в system (Python sidecar при обычном чате).".to_string(),
        format!("Tools memory_*: {}", if tools { "вкл." } else { "выкл." }),
        String::new(),
        "Документация: docs/MEMORY_AGENT_ACCESS.md".to_string(),
    ];
    if tools {
        for spec in memory_tool_specs() {
            if let Some(name) = spec
                .get("function")
                .and_then(|f| f.get("name"))
                .and_then(|v| v.as_str())
            {
                lines.push(format!("  · {name}"));
            }
        }
    }
    lines.join("\n")
}
