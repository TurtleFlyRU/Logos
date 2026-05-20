//! Сборка контекста для chat/completions (фаза 2 — упрощённый parity).

use std::fs;

use eidos_protocol::working::WmEvent;
use serde_json::{json, Value};

use crate::context_budget::{apply_total_char_budget, total_chat_char_budget};
use crate::context_system_extra::{
    build_chat_context_full, build_system_extra_with_budget, layer_budget_enabled,
};
use crate::context_wm_summary::maybe_fold_early_wm_history;
use crate::llm_sanitize::sanitize_assistant_content_for_history;
use crate::paths::Paths;
use crate::py_sidecar;
use crate::working_memory::WorkingMemory;

const DEFAULT_WM_MESSAGES: usize = 40;

/// System + user для `ask` (фаза 1).
pub fn build_ask_messages(paths: &Paths, user_message: &str) -> Vec<Value> {
    let system = load_project_agents_md(paths);
    let system = if system.trim().is_empty() {
        "Ты — Эйдос, ассистент в репозитории Logos.".to_string()
    } else {
        system
    };
    vec![
        json!({ "role": "system", "content": system }),
        json!({ "role": "user", "content": user_message }),
    ]
}

pub fn load_project_agents_md(paths: &Paths) -> String {
    if let Ok(override_path) = std::env::var("EIDOS_CHAT_PERSONA_PATH") {
        let p = override_path.trim();
        if !p.is_empty() {
            if let Ok(text) = fs::read_to_string(std::path::Path::new(p)) {
                let t = text.trim();
                if !t.is_empty() {
                    return t.to_string();
                }
            }
        }
    }
    let path = paths.repo_root.join("AGENTS.md");
    fs::read_to_string(path).unwrap_or_default()
}

fn wm_message_budget() -> usize {
    std::env::var("EIDOS_CHAT_WM_MESSAGES")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .filter(|&n| n > 0)
        .unwrap_or(DEFAULT_WM_MESSAGES)
}

/// События WM с данным `cli_session_id` → сообщения API.
pub fn wm_events_to_chat_messages(events: &[WmEvent], cli_session_id: &str) -> Vec<Value> {
    let mut out = Vec::new();
    for ev in events {
        if ev.cli_session_id.as_deref() != Some(cli_session_id) {
            continue;
        }
        let role = ev.role.as_deref().unwrap_or("");
        if role == "tool" {
            let Some(tid) = ev.tool_call_id.as_deref() else {
                continue;
            };
            let content = ev.content.as_deref().unwrap_or("");
            out.push(json!({
                "role": "tool",
                "tool_call_id": tid,
                "content": content,
            }));
            continue;
        }
        if role == "assistant" {
            if let Some(tc) = &ev.tool_calls {
                let content_field = ev
                    .content
                    .as_deref()
                    .map(sanitize_assistant_content_for_history)
                    .filter(|s| !s.is_empty());
                let mut msg = json!({
                    "role": "assistant",
                    "tool_calls": tc,
                });
                if let Some(c) = content_field {
                    msg["content"] = Value::String(c);
                } else {
                    msg["content"] = Value::Null;
                }
                out.push(msg);
                continue;
            }
            let text = ev
                .text_content()
                .map(sanitize_assistant_content_for_history)
                .unwrap_or_default();
            if text.trim().is_empty() {
                continue;
            }
            out.push(json!({ "role": "assistant", "content": text }));
            continue;
        }
        if role == "user" {
            let text = ev.text_content().unwrap_or("").trim();
            if text.is_empty() {
                continue;
            }
            out.push(json!({ "role": "user", "content": text }));
        }
    }
    let max = wm_message_budget();
    if out.len() > max {
        out.split_off(out.len() - max)
    } else {
        out
    }
}

/// System + история WM для сессии (parity с ``cli.context.build_chat_messages_for_llm``).
pub fn build_chat_messages_for_llm(
    paths: &Paths,
    wm: &WorkingMemory,
    cli_session_id: &str,
    user_message: &str,
    sidecar: &mut py_sidecar::Sidecar,
) -> Vec<Value> {
    if py_sidecar::use_python_context() {
        match sidecar.build_chat_messages(cli_session_id, user_message) {
            Ok(msgs) if !msgs.is_empty() => return msgs,
            Err(e) => {
                eprintln!(
                    "[eidos] Python context недоступен ({e}); упрощённая сборка в Rust."
                );
            }
            Ok(_) => {}
        }
    }
    build_chat_messages_for_llm_rust(paths, wm, cli_session_id, user_message, sidecar)
}

fn build_chat_messages_for_llm_rust(
    paths: &Paths,
    wm: &WorkingMemory,
    cli_session_id: &str,
    user_message: &str,
    sidecar: &mut py_sidecar::Sidecar,
) -> Vec<Value> {
    let persona = load_project_agents_md(paths).trim().to_string();

    let mut hist =
        wm_events_to_chat_messages(&wm.document().events, cli_session_id);
    if !crate::tools::tools_enabled() {
        hist.retain(|m| {
            m.get("role")
                .and_then(|r| r.as_str())
                .is_some_and(|r| r == "user" || r == "assistant")
        });
    }

    let cap = total_chat_char_budget();
    let extra = if layer_budget_enabled(cap) {
        let persona_chars = persona.chars().count();
        let hist_chars = crate::context_budget::estimate_messages_chars(&hist);
        let extra_budget = cap
            .saturating_sub(persona_chars)
            .saturating_sub(hist_chars)
            .saturating_sub(50);
        build_system_extra_with_budget(
            wm,
            &persona,
            cli_session_id,
            user_message,
            extra_budget,
            sidecar,
        )
    } else {
        build_chat_context_full(
            wm,
            &persona,
            cli_session_id,
            user_message,
            sidecar,
        )
    };

    let system_content = if extra.trim().is_empty() {
        persona.clone()
    } else {
        format!("{persona}\n\n{}", extra.trim_end())
    };

    let mut messages = vec![json!({ "role": "system", "content": system_content })];
    messages.append(&mut hist);
    if cap > 0 {
        maybe_fold_early_wm_history(&mut messages, cap);
    }
    apply_total_char_budget(messages, cap)
}

pub fn assistant_message_for_api(msg: &Value) -> Value {
    let mut out = json!({ "role": "assistant" });
    if let Some(tc) = msg.get("tool_calls") {
        out["tool_calls"] = tc.clone();
    }
    if msg.get("content").is_some() {
        out["content"] = msg["content"].clone();
    }
    out
}
