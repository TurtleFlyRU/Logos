//! Блоки system поверх персоны — parity с ``cli.context.build_chat_context`` и
//! ``_build_system_extra_with_budget`` (слойная деградация при ``EIDOS_CHAT_TOTAL_CHARS``).

use std::sync::OnceLock;

use regex::Regex;
use serde_json::Value;

use crate::py_sidecar::Sidecar;
use crate::working_memory::WorkingMemory;
use eidos_protocol::working::WmContext;

const USER_IDENTITY_CALIBRATION: &str = "— Интерфейс CLI: указанное здесь имя и текст persona (AGENTS.md) считаются надёжной \
опорой для обращения к собеседнику; блок «Активное извлечение…» может быть пустым \
или не совпасть по ключевым словам короткой реплики — этого недостаточно, чтобы \
«отрицать» имя пользователя или утверждать, что память «пуста» именно про личность.\n";

const DEFAULT_BOOT_SNIPPET_CHARS: usize = 12_000;
const DEFAULT_PRINCIPLES_LIMIT: usize = 5;
const DEFAULT_PRINCIPLES_MIN_CONF: f64 = 0.7;

fn env_flag(name: &str, default_on: bool) -> bool {
    let raw = std::env::var(name).unwrap_or_default();
    let raw = raw.trim().to_ascii_lowercase();
    if raw.is_empty() {
        return default_on;
    }
    !matches!(raw.as_str(), "0" | "false" | "no" | "off")
}

/// Включить бюджет по слоям (8.1): по умолчанию вместе с ненулевым ``EIDOS_CHAT_TOTAL_CHARS``.
pub fn layer_budget_enabled(total_budget: usize) -> bool {
    let default_on = total_budget > 0;
    env_flag("EIDOS_CHAT_LAYER_BUDGET", default_on)
}

pub fn user_identity_enabled() -> bool {
    env_flag("EIDOS_CHAT_USER_IDENTITY", true)
}

pub fn cli_plan_enabled() -> bool {
    env_flag("EIDOS_CHAT_CLI_PLAN", true)
}

pub fn attention_enabled() -> bool {
    env_flag("EIDOS_CHAT_ATTENTION", true)
}

pub fn active_memory_flag() -> bool {
    env_flag("EIDOS_CHAT_ACTIVE_MEMORY", true)
}

pub fn boot_snippet_enabled() -> bool {
    env_flag("EIDOS_CHAT_BOOT_SNIPPET", true)
}

pub fn principles_enabled() -> bool {
    env_flag("EIDOS_CHAT_PRINCIPLES", true)
}

pub fn tools_catalog_enabled() -> bool {
    env_flag("EIDOS_TOOLS", true)
}

fn cli_wm_plan_max_chars() -> usize {
    std::env::var("EIDOS_CHAT_CLI_PLAN_CHARS")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: usize| n.clamp(200, 15_000))
        .unwrap_or(2800)
}

fn boot_snippet_char_cap() -> usize {
    std::env::var("EIDOS_CHAT_BOOT_SNIPPET_CHARS")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: usize| n.clamp(800, 120_000))
        .unwrap_or(DEFAULT_BOOT_SNIPPET_CHARS)
}

pub fn active_memory_budget_chars() -> usize {
    std::env::var("EIDOS_CHAT_ACTIVE_MEMORY_CHARS")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: usize| n.clamp(1500, 50_000))
        .unwrap_or(12_000)
}

fn identity_from_persona(persona: &str) -> Option<String> {
    let re = IDENTITY_RE.get_or_init(|| {
        Regex::new(
            r"\((?:[^,)]{2,64}),\s*([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{1,48})\)",
        )
        .expect("identity regex")
    });
    re.captures(persona)?
        .get(1)
        .map(|m| m.as_str().trim().to_string())
        .filter(|s| !s.is_empty())
}

/// Усечь текст по символам (Unicode), как ``_truncate_block`` в Python.
pub fn truncate_block(text: &str, max_chars: usize) -> String {
    if max_chars == 0 {
        return String::new();
    }
    let s = text.trim();
    if s.is_empty() {
        return String::new();
    }
    let n = s.chars().count();
    if n <= max_chars {
        return s.to_string();
    }
    if max_chars < 4 {
        return s.chars().take(max_chars).collect();
    }
    let mut out: String = s.chars().take(max_chars - 1).collect();
    out.push('…');
    out
}

fn resolved_cli_plan_text(ctx: &WmContext) -> String {
    for key in ["cli_current_plan", "cli_task_plan"] {
        if let Some(Value::String(s)) = ctx.extra.get(key) {
            let t = s.trim();
            if !t.is_empty() {
                return t.to_string();
            }
        }
    }
    String::new()
}

fn session_tags_plain(ctx: &WmContext) -> String {
    if let Some(tags) = &ctx.session_tags {
        let parts: Vec<&str> = tags
            .iter()
            .map(|t| t.trim())
            .filter(|t| !t.is_empty())
            .collect();
        return parts.join(", ");
    }
    if let Some(Value::String(s)) = ctx.extra.get("session_tags") {
        let t = s.trim();
        if !t.is_empty() {
            return t.to_string();
        }
    }
    String::new()
}

/// Блок «фокус и план» из WM context (parity ``format_cli_wm_plan_and_session_block``).
pub fn format_cli_wm_plan_and_session_block(wm: &WorkingMemory, max_chars: Option<usize>) -> String {
    let cap = max_chars.unwrap_or_else(cli_wm_plan_max_chars);
    let ctx = &wm.document().context;
    let plan = resolved_cli_plan_text(ctx);
    let title = ctx
        .session_title
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("");
    let tags = session_tags_plain(ctx);
    if plan.is_empty() && title.is_empty() {
        return String::new();
    }

    let mut inner_lines: Vec<String> = Vec::new();
    if !title.is_empty() {
        let tcap = 480_usize.min(cap);
        inner_lines.push(format!(
            "  Заголовок сессии: {}",
            truncate_block(title, tcap)
        ));
    }
    if !tags.is_empty() {
        let tcap = 400_usize.min(cap);
        inner_lines.push(format!("  Теги: {}", truncate_block(&tags, tcap)));
    }
    if !plan.is_empty() {
        let plan_cap = cap.saturating_sub(120).max(200);
        let trimmed = truncate_block(&plan, plan_cap);
        let indented = trimmed
            .lines()
            .map(|line| format!("  {line}"))
            .collect::<Vec<_>>()
            .join("\n");
        inner_lines.push("  Текущий план:".to_string());
        inner_lines.push(if indented.is_empty() {
            "  …".to_string()
        } else {
            indented
        });
    }

    let body = inner_lines.join("\n").trim().to_string();
    let block = format!("— Фокус и план (CLI, WM):\n{body}\n");
    let mut out = truncate_block(&block, cap);
    if !out.ends_with('\n') {
        out.push('\n');
    }
    out
}

pub fn format_user_identity_block(wm: &WorkingMemory, persona: &str) -> String {
    if !user_identity_enabled() {
        return String::new();
    }
    let ctx = &wm.document().context;
    if let Some(name) = ctx
        .user_display_name
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .or_else(|| {
            ctx.extra
                .get("user_display_name")
                .and_then(|v| v.as_str())
                .map(str::trim)
                .filter(|s| !s.is_empty())
        })
    {
        return format!(
            "— Пользователь (CLI, явно указано в диалоге): имя — {name}.\n{USER_IDENTITY_CALIBRATION}"
        );
    }
    if let Some(name) = identity_from_persona(persona) {
        return format!(
            "— Пользователь (из AGENTS.md): имя — {name}.\n{USER_IDENTITY_CALIBRATION}"
        );
    }
    String::new()
}

/// Слоты внимания (parity ``format_attention_slots_block``).
pub fn format_attention_slots_block(wm: &WorkingMemory) -> String {
    let slots = &wm.document().attention_slots;
    if slots.is_empty() {
        return String::new();
    }
    let start = slots.len().saturating_sub(4);
    let mut lines = vec!["— Слоты внимания (WM):".to_string()];
    for slot in &slots[start..] {
        let summary: String = slot.summary.chars().take(200).collect();
        lines.push(format!("  • [{}] {summary}", slot.role));
    }
    lines.join("\n") + "\n"
}

/// Фрагмент boot из WM (parity ``format_boot_context_snippet``).
pub fn format_boot_context_snippet(wm: &WorkingMemory, max_chars: usize) -> String {
    let ctx = &wm.document().context;
    let Some(Value::String(raw)) = ctx.extra.get("boot_context") else {
        return String::new();
    };
    let text = raw.trim();
    if text.is_empty() {
        return String::new();
    }
    let text = truncate_block(text, max_chars);
    format!(
        "— Фрагмент сохранённого boot-контекста (из WM, без повторного boot):\n{text}\n\n"
    )
}

fn add_layer(parts: &mut Vec<String>, rem: &mut usize, block: &str) {
    let b = block.trim();
    if b.is_empty() || *rem == 0 {
        return;
    }
    let b2 = truncate_block(b, *rem);
    if b2.is_empty() {
        return;
    }
    *rem = rem.saturating_sub(b2.chars().count());
    parts.push(b2);
}

/// Собрать extra с деградацией по слоям (``_build_system_extra_with_budget``).
pub fn build_system_extra_with_budget(
    wm: &WorkingMemory,
    persona: &str,
    cli_session_id: &str,
    user_message: &str,
    budget_chars: usize,
    sidecar: &mut Sidecar,
) -> String {
    let mut rem = budget_chars;
    let mut parts: Vec<String> = Vec::new();

    add_layer(&mut parts, &mut rem, &format_user_identity_block(wm, persona));

    if tools_catalog_enabled() && rem > 0 {
        let cap = rem.min(4000);
        match sidecar.tools_catalog_block(user_message, cap as u64) {
            Ok(block) => add_layer(&mut parts, &mut rem, &block),
            Err(e) => eprintln!("[eidos] tools_catalog_block: {e}"),
        }
    }

    if cli_plan_enabled() && rem > 0 {
        let cap = rem.min(cli_wm_plan_max_chars());
        add_layer(
            &mut parts,
            &mut rem,
            &format_cli_wm_plan_and_session_block(wm, Some(cap)),
        );
    }

    if attention_enabled() {
        add_layer(&mut parts, &mut rem, &format_attention_slots_block(wm));
    }

    if active_memory_flag() && rem > 0 {
        let cap_am = rem.min(active_memory_budget_chars());
        match sidecar.active_memory_block(cli_session_id, user_message, cap_am) {
            Ok(block) => add_layer(&mut parts, &mut rem, &block),
            Err(e) => eprintln!("[eidos] active_memory_block: {e}"),
        }
    }

    if boot_snippet_enabled() && rem > 0 {
        let cap_boot = rem.min(boot_snippet_char_cap());
        add_layer(
            &mut parts,
            &mut rem,
            &format_boot_context_snippet(wm, cap_boot),
        );
    }

    if principles_enabled() && rem > 0 {
        match sidecar.semantic_principles_block(DEFAULT_PRINCIPLES_LIMIT, DEFAULT_PRINCIPLES_MIN_CONF)
        {
            Ok(block) => add_layer(&mut parts, &mut rem, &block),
            Err(e) => eprintln!("[eidos] semantic_principles_block: {e}"),
        }
    }

    parts.join("\n\n")
}

/// Полный extra без послойного остатка (``build_chat_context``).
pub fn build_chat_context_full(
    wm: &WorkingMemory,
    persona: &str,
    cli_session_id: &str,
    user_message: &str,
    sidecar: &mut Sidecar,
) -> String {
    let mut parts: Vec<String> = Vec::new();
    if user_identity_enabled() {
        let s = format_user_identity_block(wm, persona);
        if !s.is_empty() {
            parts.push(s);
        }
    }
    if tools_catalog_enabled() {
        match sidecar.tools_catalog_block(user_message, 4000) {
            Ok(block) => {
                let t = block.trim();
                if !t.is_empty() {
                    parts.push(t.to_string());
                }
            }
            Err(e) => eprintln!("[eidos] tools_catalog_block: {e}"),
        }
    }
    if cli_plan_enabled() {
        let s = format_cli_wm_plan_and_session_block(wm, None);
        if !s.is_empty() {
            parts.push(s);
        }
    }
    if attention_enabled() {
        let s = format_attention_slots_block(wm);
        if !s.is_empty() {
            parts.push(s);
        }
    }
    if active_memory_flag() {
        let cap = active_memory_budget_chars();
        match sidecar.active_memory_block(cli_session_id, user_message, cap) {
            Ok(block) => {
                let t = block.trim();
                if !t.is_empty() {
                    parts.push(t.to_string());
                }
            }
            Err(e) => eprintln!("[eidos] active_memory_block: {e}"),
        }
    }
    if boot_snippet_enabled() {
        let s = format_boot_context_snippet(wm, boot_snippet_char_cap());
        if !s.trim().is_empty() {
            parts.push(s);
        }
    }
    if principles_enabled() {
        match sidecar.semantic_principles_block(DEFAULT_PRINCIPLES_LIMIT, DEFAULT_PRINCIPLES_MIN_CONF)
        {
            Ok(block) => {
                let t = block.trim();
                if !t.is_empty() {
                    parts.push(t.to_string());
                }
            }
            Err(e) => eprintln!("[eidos] semantic_principles_block: Sidecar: {e}"),
        }
    }
    parts.join("\n\n")
}

static IDENTITY_RE: OnceLock<Regex> = OnceLock::new();

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncate_block_edges() {
        assert_eq!(truncate_block("  hi  ", 10), "hi");
        assert_eq!(truncate_block("abcde", 3), "abc");
        assert_eq!(truncate_block("ab", 2), "ab");
        assert_eq!(truncate_block("x", 0), "");
    }

    #[test]
    fn layer_budget_env_default_off_without_total() {
        std::env::remove_var("EIDOS_CHAT_LAYER_BUDGET");
        assert!(!layer_budget_enabled(0));
        assert!(layer_budget_enabled(1000));
    }
}
