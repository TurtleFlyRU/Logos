//! Общий лимит размера промпта (`EIDOS_CHAT_TOTAL_CHARS`) — parity с ``cli.context._apply_total_char_budget``.

use serde_json::Value;

/// Максимум символов по всем сообщениям (0 = без лимита, как в Python по умолчанию).
pub fn total_chat_char_budget() -> usize {
    let raw = std::env::var("EIDOS_CHAT_TOTAL_CHARS").unwrap_or_default();
    let raw = raw.trim();
    if raw.is_empty() {
        return 0;
    }
    raw.parse::<usize>()
        .map(|n| n.min(1_000_000))
        .unwrap_or(0)
}

/// Суммарная длина строковых ``content`` (как ``estimate_messages_chars`` в Python).
pub fn estimate_messages_chars(messages: &[Value]) -> usize {
    messages
        .iter()
        .map(|m| {
            m.get("content")
                .and_then(|v| v.as_str())
                .map(|s| s.chars().count())
                .unwrap_or(0)
        })
        .sum()
}

/// Уложиться в бюджет: удалять сначала самые старые сообщения истории (после system), затем урезать system.
pub fn apply_total_char_budget(mut messages: Vec<Value>, total_budget: usize) -> Vec<Value> {
    if total_budget == 0 || messages.is_empty() {
        return messages;
    }

    while messages.len() > 1 && estimate_messages_chars(&messages) > total_budget {
        messages.remove(1);
    }

    let over = estimate_messages_chars(&messages).saturating_sub(total_budget);
    if over == 0 {
        return messages;
    }

    if let Some(first) = messages.first_mut() {
        let Some(sys_text) = first.get("content").and_then(|v| v.as_str()) else {
            return messages;
        };
        let n_chars = sys_text.chars().count();
        let keep = (n_chars.saturating_sub(over + 20)).max(2000);
        if keep < n_chars {
            let trimmed: String = sys_text.chars().take(keep).collect();
            first["content"] = Value::String(format!("{trimmed}…"));
        }
    }

    messages
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn zero_budget_is_noop() {
        let v = vec![json!({"role":"system","content":"ab"}), json!({"role":"user","content":"cd"})];
        assert_eq!(apply_total_char_budget(v.clone(), 0), v);
    }

    #[test]
    fn drops_oldest_history_first() {
        let v = vec![
            json!({"role":"system","content":"sys"}),
            json!({"role":"user","content":"old"}),
            json!({"role":"assistant","content":"mid"}),
            json!({"role":"user","content":"new"}),
        ];
        let out = apply_total_char_budget(v, 10);
        assert_eq!(out.len(), 3);
        assert_eq!(out[1]["content"], "mid");
        assert_eq!(out[2]["content"], "new");
    }

    #[test]
    fn trims_system_when_still_over() {
        let sys: String = "x".repeat(5000);
        let v = vec![
            json!({"role":"system","content": sys}),
            json!({"role":"user","content":"hi"}),
        ];
        let out = apply_total_char_budget(v, 3000);
        assert_eq!(out.len(), 1);
        let c = out[0]["content"].as_str().unwrap();
        assert!(c.ends_with('…'));
        assert!(estimate_messages_chars(&out) <= 3100);
        assert!(c.chars().count() < 5000);
    }
}
