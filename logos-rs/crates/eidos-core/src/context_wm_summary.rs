//! Сжатие ранней истории WM в system (``EIDOS_CHAT_SUMMARIZE_OLD_WM``) — только при ``EIDOS_CHAT_TOTAL_CHARS`` > 0, как в Python.

use serde_json::Value;

fn summarize_old_wm_enabled() -> bool {
    matches!(
        std::env::var("EIDOS_CHAT_SUMMARIZE_OLD_WM").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

pub(crate) fn keep_last_messages() -> usize {
    let raw = std::env::var("EIDOS_CHAT_KEEP_LAST_MESSAGES").unwrap_or_default();
    let raw = raw.trim();
    if raw.is_empty() {
        return 16;
    }
    raw.parse::<usize>()
        .map(|n| n.clamp(4, 120))
        .unwrap_or(16)
}

pub(crate) fn summary_char_budget() -> usize {
    let raw = std::env::var("EIDOS_CHAT_SUMMARY_CHARS").unwrap_or_default();
    let raw = raw.trim();
    if raw.is_empty() {
        return 6000;
    }
    raw.parse::<usize>()
        .map(|n| n.clamp(800, 120_000))
        .unwrap_or(6000)
}

fn history_snippet_timeline(body: &str, max_body: usize) -> String {
    let cleaned: String = body.trim().replace('\n', " ");
    if cleaned.chars().count() <= max_body {
        cleaned
    } else {
        cleaned.chars().take(max_body.saturating_sub(1)).collect::<String>() + "…"
    }
}

/// Компактный текст ранних реплик (режим ``timeline``; ``compress`` — только в Python).
pub fn render_compact_history_summary(early: &[Value], max_chars: usize) -> String {
    let header = "— Сжатая история (ранние реплики):";
    let mut lines = vec![header.to_string()];
    let mut used = header.chars().count() + 1;
    const MAX_BODY: usize = 240;

    for m in early {
        let role = m.get("role").and_then(|v| v.as_str()).unwrap_or("?");
        let Some(content) = m.get("content").and_then(|v| v.as_str()) else {
            continue;
        };
        let t = content.trim();
        if t.is_empty() {
            continue;
        }
        let snippet = history_snippet_timeline(t, MAX_BODY);
        let line = format!("  [{role}] {snippet}");
        if used + line.chars().count() + 1 > max_chars {
            lines.push("  … (обрезано по бюджету summary)".to_string());
            break;
        }
        used += line.chars().count() + 1;
        lines.push(line);
    }

    let mut text = lines.join("\n");
    if text.chars().count() > max_chars {
        text = text.chars().take(max_chars.saturating_sub(1)).collect::<String>() + "…";
    }
    text
}

/// Влить раннюю историю в ``system``, оставив хвост из ``keep_last`` сообщений.
pub fn maybe_fold_early_wm_history(messages: &mut Vec<Value>, total_budget: usize) {
    if total_budget == 0 || !summarize_old_wm_enabled() || messages.len() <= 1 {
        return;
    }

    let keep = keep_last_messages();
    let hist_count = messages.len() - 1;
    if hist_count <= keep + 4 {
        return;
    }

    let mut hist: Vec<Value> = messages.split_off(1);
    let split_at = hist.len() - keep;
    let tail = hist.split_off(split_at);
    let summary = render_compact_history_summary(&hist, summary_char_budget());
    if summary.trim().is_empty() {
        messages.extend(tail);
        return;
    }

    let Some(sys) = messages.get_mut(0) else {
        messages.extend(tail);
        return;
    };
    let base = sys
        .get("content")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let merged = format!("{}\n\n{}", base.trim_end(), summary.trim());
    sys["content"] = Value::String(merged);

    messages.extend(tail);
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn summary_truncates_roles() {
        let early = vec![
            json!({"role":"user","content":"hello world line"}),
            json!({"role":"assistant","content":"reply"}),
        ];
        let s = render_compact_history_summary(&early, 500);
        assert!(s.contains("[user]"));
        assert!(s.contains("[assistant]"));
    }

    #[test]
    fn fold_requires_budget() {
        let mut v = vec![
            json!({"role":"system","content":"base"}),
            json!({"role":"user","content":"1"}),
        ];
        maybe_fold_early_wm_history(&mut v, 0);
        assert_eq!(v.len(), 2);
    }
}
