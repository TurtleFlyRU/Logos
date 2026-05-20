//! Лексический поиск по `data/journal/*.md` (Rust fallback без torch).

use std::fs;
use std::path::Path;

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::paths::Paths;

#[derive(Debug, Clone)]
pub struct JournalHit {
    pub file: String,
    pub section: String,
    pub snippet: String,
}

pub fn search_journal_lexical(paths: &Paths, query: &str, top_k: usize) -> Result<Vec<JournalHit>> {
    let q = query.trim();
    if q.is_empty() {
        return Err(CoreError::Tool("query required".into()));
    }
    let tokens: Vec<String> = tokenize(q);
    if tokens.is_empty() {
        return Err(CoreError::Tool("query has no searchable tokens".into()));
    }

    let dir = paths.journal_dir();
    if !dir.is_dir() {
        return Ok(Vec::new());
    }

    let mut hits: Vec<JournalHit> = Vec::new();
    for ent in fs::read_dir(&dir).map_err(|e| CoreError::WorkingMemory(e.to_string()))? {
        let ent = ent.map_err(|e| CoreError::WorkingMemory(e.to_string()))?;
        let path = ent.path();
        if path.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        if path.file_name().and_then(|n| n.to_str()) == Some("INDEX.md") {
            continue;
        }
        collect_hits_in_file(&path, &tokens, &mut hits, top_k);
        if hits.len() >= top_k {
            break;
        }
    }
    hits.truncate(top_k);
    Ok(hits)
}

fn collect_hits_in_file(path: &Path, tokens: &[String], hits: &mut Vec<JournalHit>, top_k: usize) {
    let text = fs::read_to_string(path).unwrap_or_default();
    let fname = path.file_name().and_then(|n| n.to_str()).unwrap_or("?").to_string();
    let lower = text.to_lowercase();
    if tokens.iter().any(|t| lower.contains(t)) {
        let snippet = extract_snippet(&text, tokens, 300);
        hits.push(JournalHit {
            file: fname.clone(),
            section: String::new(),
            snippet,
        });
    }
    if hits.len() >= top_k {
        return;
    }

    let mut current_section = String::new();
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix("## ") {
            current_section = rest.trim().to_string();
            continue;
        }
        let ll = line.to_lowercase();
        if tokens.iter().any(|t| ll.contains(t)) {
            hits.push(JournalHit {
                file: fname.clone(),
                section: current_section.clone(),
                snippet: truncate(line, 300),
            });
            if hits.len() >= top_k {
                return;
            }
        }
    }
}

fn extract_snippet(text: &str, tokens: &[String], max: usize) -> String {
    let lower = text.to_lowercase();
    for token in tokens {
        if let Some(pos) = lower.find(token.as_str()) {
            let start = pos.saturating_sub(80);
            let slice = &text[start..];
            return truncate(slice, max);
        }
    }
    truncate(text, max)
}

fn tokenize(query: &str) -> Vec<String> {
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

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}…", &s[..max.saturating_sub(1)])
    }
}

pub fn hits_to_json(hits: &[JournalHit]) -> Vec<Value> {
    hits.iter()
        .map(|h| {
            json!({
                "file": h.file,
                "section": h.section,
                "snippet": h.snippet,
            })
        })
        .collect()
}
