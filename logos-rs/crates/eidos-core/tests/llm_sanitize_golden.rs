//! Golden-сэмплы санитизации (parity с ``cli/llm_sanitize.py``).

use eidos_core::llm_sanitize::{
    normalize_assistant_message, sanitize_assistant_content_for_history, strip_model_channels,
};
use serde_json::json;

#[test]
fn strips_gemma_channel_thought() {
    let raw = "<|channel>thought\nsecret reasoning\n<|channel>final\nHello user";
    let out = strip_model_channels(raw);
    assert!(out.contains("Hello user"));
    assert!(!out.contains("secret reasoning"));
}

#[test]
fn sanitize_history_strips_channels() {
    let raw = "<|channel>thought\nx\n<|channel>final\nok";
    let out = sanitize_assistant_content_for_history(raw);
    assert_eq!(out, "ok");
}

#[test]
fn normalize_assistant_message_object() {
    let msg = json!({
        "role": "assistant",
        "content": "<|channel>thought\nx\n<|channel>final\nok",
    });
    let n = normalize_assistant_message(msg);
    let c = n.get("content").and_then(|v| v.as_str()).unwrap_or("");
    assert_eq!(c, "ok");
}
