//! External memory documents (`data/external/documents.db`) — Rust fallback без векторов.

use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::paths::Paths;

#[derive(Debug, Clone)]
struct ExternalDoc {
    id: i64,
    source: String,
    title: String,
    url: Option<String>,
    content: String,
}

/// Лексический поиск по title+content (без rubert; parity с journal fallback).
pub fn search_external_lexical(paths: &Paths, query: &str, top_k: usize) -> Result<Value> {
    let q = query.trim();
    if q.is_empty() {
        return Err(CoreError::Tool("query required".into()));
    }
    let db_path = paths.external_db_path();
    if !db_path.is_file() {
        return Ok(json!({
            "count": 0,
            "hits": [],
            "backend": "rust_lexical",
            "note": "documents.db not found; ingest via Python ExternalMemory"
        }));
    }

    let tokens = tokenize_query(q);
    if tokens.is_empty() {
        return Err(CoreError::Tool("query has no searchable tokens".into()));
    }

    let conn = Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let mut stmt = conn.prepare(
        "SELECT id, source, title, url, content FROM documents ORDER BY timestamp DESC",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(ExternalDoc {
            id: row.get(0)?,
            source: row.get::<_, String>(1)?,
            title: row.get::<_, String>(2)?,
            url: row.get::<_, Option<String>>(3)?,
            content: row.get::<_, String>(4)?,
        })
    })?;

    let mut scored: Vec<(f64, ExternalDoc)> = Vec::new();
    for row in rows {
        let doc = row?;
        let hay = format!("{} {}", doc.title, doc.content).to_lowercase();
        let matched = tokens.iter().filter(|t| hay.contains(t.as_str())).count();
        if matched == 0 {
            continue;
        }
        let score = matched as f64 / tokens.len() as f64;
        scored.push((score, doc));
    }
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    scored.truncate(top_k);

    let hits: Vec<Value> = scored
        .into_iter()
        .map(|(score, doc)| {
            json!({
                "id": doc.id,
                "source": doc.source,
                "title": doc.title,
                "url": doc.url,
                "score": (score * 10000.0).round() / 10000.0,
                "snippet": truncate_str(&doc.content, 200),
            })
        })
        .collect();

    Ok(json!({
        "count": hits.len(),
        "hits": hits,
        "backend": "rust_lexical",
        "note": "vector search needs Python sidecar or EIDOS_ML_SIDECAR_URL (future)"
    }))
}

pub fn external_stats(paths: &Paths) -> Result<Value> {
    let db_path = paths.external_db_path();
    if !db_path.is_file() {
        return Ok(json!({ "documents": 0, "unique_sources": 0, "size_bytes": 0 }));
    }
    let conn = Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let documents: i64 = conn.query_row("SELECT COUNT(*) FROM documents", [], |r| r.get(0))?;
    let sources: i64 =
        conn.query_row("SELECT COUNT(DISTINCT source) FROM documents", [], |r| r.get(0))?;
    let size_bytes = std::fs::metadata(&db_path)
        .map(|m| m.len())
        .unwrap_or(0);
    Ok(json!({
        "documents": documents,
        "unique_sources": sources,
        "size_bytes": size_bytes,
    }))
}

fn tokenize_query(query: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    for ch in query.to_lowercase().chars() {
        if ch.is_alphanumeric() || ch == '_' || ('\u{0400}'..='\u{04FF}').contains(&ch) {
            cur.push(ch);
        } else if !cur.is_empty() {
            if cur.len() >= 2 {
                out.push(cur.clone());
            }
            cur.clear();
        }
    }
    if cur.len() >= 2 {
        out.push(cur);
    }
    out
}

fn truncate_str(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max.saturating_sub(1)])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn temp_paths() -> Paths {
        let repo = std::env::temp_dir().join(format!(
            "eidos-ext-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&repo).unwrap();
        fs::write(repo.join("eidos.py"), "").unwrap();
        fs::create_dir(repo.join("kernel")).unwrap();
        let data = repo.join("data");
        fs::create_dir_all(data.join("external")).unwrap();
        Paths {
            repo_root: repo.clone(),
            data_root: data,
        }
    }

    #[test]
    fn lexical_finds_document() {
        let paths = temp_paths();
        let db = paths.external_db_path();
        let conn = Connection::open(&db).unwrap();
        conn.execute_batch(
            "CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                url TEXT,
                title TEXT,
                timestamp REAL NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT UNIQUE
            );",
        )
        .unwrap();
        conn.execute(
            "INSERT INTO documents (source, title, timestamp, content, content_hash)
             VALUES ('test', 'Память Эйдос', 1.0, 'Как работает episodic memory', 'abc')",
            [],
        )
        .unwrap();

        let out = search_external_lexical(&paths, "память episodic", 5).unwrap();
        assert_eq!(out.get("count").and_then(|v| v.as_u64()), Some(1));
        let hits = out.get("hits").and_then(|v| v.as_array()).unwrap();
        assert_eq!(hits[0].get("title").and_then(|v| v.as_str()), Some("Память Эйдос"));
    }
}
