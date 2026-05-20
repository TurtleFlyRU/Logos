//! Санитизация ответов локальных моделей (Gemma thinking, inline tool_call).

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_thought_block() {
        let raw = "<|channel>thought\nsecret\n<|channel>final\nvisible";
        assert_eq!(strip_model_channels(raw), "visible");
    }
}

use std::env;

use eidos_protocol::working::{FunctionCall, ToolCall};
use regex::Regex;
use serde_json::{json, Value};

const TOOL_CALL_MARKER: &str = "<|tool_call>call:";

fn strip_enabled() -> bool {
    let v = env::var("EIDOS_STRIP_MODEL_THOUGHT")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

fn thought_open_re() -> Regex {
    Regex::new(r"(?i)<\|channel>thought\b").expect("regex")
}

fn channel_or_tool_re() -> Regex {
    Regex::new(r"(?i)<\|(?:channel>(?:final|comment|response)|tool_call>|think\|>)").expect("regex")
}

fn channel_final_re() -> Regex {
    Regex::new(r"(?i)<\|channel>(?:final|comment|response)\s*").expect("regex")
}

fn tool_close_re() -> Regex {
    Regex::new(r"(?i)\s*(?:<tool_call\|>|<\|tool_call\|>)").expect("regex")
}

/// Убрать блоки thought и служебные токены.
pub fn strip_model_channels(text: &str) -> String {
    let thought_open = thought_open_re();
    let channel_or_tool = channel_or_tool_re();
    let channel_final = channel_final_re();

    let mut out = text.to_string();
    loop {
        let Some(m) = thought_open.find(&out) else {
            break;
        };
        let start = m.start();
        let tail = &out[m.end()..];
        if let Some(end_m) = channel_or_tool.find(tail) {
            out = format!("{}{}", &out[..start], &tail[end_m.start()..]);
        } else {
            out.truncate(start);
            break;
        }
    }
    out = channel_final.replace_all(&out, "").into_owned();
    let inline = iter_gemma_inline_tool_calls(&out);
    out = remove_inline_spans(&out, &inline);
    for junk in ["<|\"|>", "<|think|>", "<|end|>"] {
        out = out.replace(junk, "");
    }
    out.trim().to_string()
}

fn iter_gemma_inline_tool_calls(text: &str) -> Vec<(String, String, usize, usize)> {
    let mut found = Vec::new();
    let mut pos = 0;
    while let Some(idx) = text[pos..].find(TOOL_CALL_MARKER) {
        let idx = pos + idx;
        let name_start = idx + TOOL_CALL_MARKER.len();
        let Some(rel_brace) = text[name_start..].find('{') else {
            break;
        };
        let brace = name_start + rel_brace;
        let name = text[name_start..brace].trim().to_string();
        let mut depth = 0i32;
        let mut end_brace = None;
        for (j, ch) in text[brace..].char_indices() {
            let j = brace + j;
            match ch {
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        end_brace = Some(j);
                        break;
                    }
                }
                _ => {}
            }
        }
        let Some(end_brace) = end_brace else { break };
        let args_raw = text[brace + 1..end_brace].to_string();
        let close_re = tool_close_re();
        let after = &text[end_brace + 1..];
        let Some(close_m) = close_re.find(after) else {
            pos = end_brace + 1;
            continue;
        };
        let span_end = end_brace + 1 + close_m.end();
        found.push((name, args_raw, idx, span_end));
        pos = span_end;
    }
    found
}

fn remove_inline_spans(text: &str, spans: &[(String, String, usize, usize)]) -> String {
    if spans.is_empty() {
        return text.to_string();
    }
    let mut parts = Vec::new();
    let mut last = 0;
    for (_, _, start, end) in spans {
        parts.push(&text[last..*start]);
        last = *end;
    }
    parts.push(&text[last..]);
    parts.concat()
}

fn parse_pseudo_tool_args(raw: &str) -> Value {
    let s = raw.replace("<|\"|>", "\"");
    let mut out = serde_json::Map::new();
    if let Some(caps) = regex::Regex::new(r"max_chars\s*:\s*(\d+)")
        .unwrap()
        .captures(&s)
    {
        if let Some(m) = caps.get(1) {
            if let Ok(n) = m.as_str().parse::<i64>() {
                out.insert("max_chars".into(), json!(n));
            }
        }
    }
    if let Some(caps) = regex::Regex::new(r"(?is)selector\s*:\s*(.+)\s*$")
        .unwrap()
        .captures(&s)
    {
        let mut val = caps.get(1).map(|m| m.as_str().trim()).unwrap_or("").to_string();
        if val.len() >= 2 && val.starts_with('"') && val.ends_with('"') {
            val = val[1..val.len() - 1].to_string();
        }
        out.insert("selector".into(), json!(val));
        return Value::Object(out);
    }
    if s.trim_start().starts_with('{') {
        if let Ok(v) = serde_json::from_str::<Value>(&s) {
            if v.is_object() {
                return v;
            }
        }
    }
    Value::Object(out)
}

fn to_openai_tool_calls(inline: &[(String, String, usize, usize)]) -> Vec<ToolCall> {
    inline
        .iter()
        .map(|(name, args_raw, _, _)| {
            let args = parse_pseudo_tool_args(args_raw);
            let id = format!(
                "call_{:012x}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_nanos())
                    .unwrap_or(0)
            );
            let arguments = serde_json::to_string(&args).unwrap_or_else(|_| "{}".into());
            ToolCall {
                id,
                call_type: "function".to_string(),
                function: FunctionCall {
                    name: name.clone(),
                    arguments,
                },
            }
        })
        .collect()
}

/// Очистить content и извлечь inline tool_calls.
pub fn sanitize_assistant_text(text: &str) -> (String, Vec<ToolCall>) {
    let inline = iter_gemma_inline_tool_calls(text);
    let body = remove_inline_spans(text, &inline);
    let body = strip_model_channels(&body);
    let tool_calls = to_openai_tool_calls(&inline);
    (body, tool_calls)
}

/// Нормализовать объект message из API.
pub fn normalize_assistant_message(mut msg: Value) -> Value {
    if !strip_enabled() {
        return msg;
    }
    if msg.get("tool_calls").is_some() {
        if let Some(content) = msg.get("content").and_then(|c| c.as_str()) {
            if content.contains("<|channel") || content.contains("<|tool_call>") {
                let (cleaned, _) = sanitize_assistant_text(content);
                if cleaned.is_empty() {
                    msg["content"] = Value::Null;
                } else {
                    msg["content"] = Value::String(cleaned);
                }
            }
        }
        return msg;
    }
    let Some(content) = msg.get("content").and_then(|c| c.as_str()) else {
        return msg;
    };
    if !content.contains("<|channel") && !content.contains("<|tool_call>") && !content.contains("<|think")
    {
        return msg;
    }
    let (cleaned, parsed) = sanitize_assistant_text(content);
    if !parsed.is_empty() {
        msg["tool_calls"] = serde_json::to_value(&parsed).unwrap_or(Value::Null);
        msg["content"] = if cleaned.is_empty() {
            Value::Null
        } else {
            Value::String(cleaned)
        };
    } else {
        msg["content"] = Value::String(cleaned);
    }
    msg
}

/// Только текст для истории WM.
pub fn sanitize_assistant_content_for_history(text: &str) -> String {
    if !strip_enabled() {
        return text.to_string();
    }
    if !text.contains("<|channel") && !text.contains("<|tool_call>") && !text.contains("<|think") {
        return text.to_string();
    }
    let (cleaned, _) = sanitize_assistant_text(text);
    cleaned
}
