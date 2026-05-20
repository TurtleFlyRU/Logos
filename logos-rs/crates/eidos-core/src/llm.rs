//! OpenAI-compatible chat/completions (аналог `cli/llm.py`).

use reqwest::blocking::Client;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde_json::{json, Value};

use crate::agents::{http_use_proxy, LlmRuntimeParams};
use crate::error::{CoreError, Result};
use crate::llm_sanitize::normalize_assistant_message;

const CONNECT_SEC: u64 = 30;

/// POST /chat/completions → текст ответа (без tool loop).
pub fn chat_completions_text(
    messages: &[Value],
    params: &LlmRuntimeParams,
) -> Result<String> {
    let msg = chat_completion_assistant_message(messages, params, None)?;
    if let Some(tc) = msg.get("tool_calls").and_then(|v| v.as_array()) {
        if !tc.is_empty() {
            return Err(CoreError::LlmConfig(
                "модель вернула tool_calls; в фазе 1 поддерживается только текст (ask)".into(),
            ));
        }
    }
    let content = msg
        .get("content")
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if content.is_empty() {
        return Err(CoreError::LlmConfig(
            "пустой content в ответе API (после санитизации)".into(),
        ));
    }
    Ok(content)
}

/// POST /chat/completions → объект message первого choice.
pub fn chat_completion_assistant_message(
    messages: &[Value],
    params: &LlmRuntimeParams,
    tools: Option<&[Value]>,
) -> Result<Value> {
    if !params.omit_authorization_header && params.api_key.is_empty() {
        return Err(CoreError::LlmConfig(
            "нет API key и не задан omit_authorization_header".into(),
        ));
    }

    let url = format!("{}/chat/completions", params.base_url.trim_end_matches('/'));
    let mut payload = json!({
        "model": params.model,
        "messages": messages,
        "stream": false,
    });
    if let Some(tool_specs) = tools {
        payload["tools"] = json!(tool_specs);
        payload["tool_choice"] = json!("auto");
    }

    let mut builder = Client::builder()
        .connect_timeout(std::time::Duration::from_secs(CONNECT_SEC))
        .timeout(std::time::Duration::from_secs_f64(params.read_timeout_sec));
    if !http_use_proxy() {
        builder = builder.no_proxy();
    }
    let client = builder.build()?;

    let mut req = client
        .post(&url)
        .header(CONTENT_TYPE, "application/json")
        .json(&payload);
    if !params.omit_authorization_header {
        req = req.header(AUTHORIZATION, format!("Bearer {}", params.api_key));
    }

    if std::env::var("LLM_DEBUG").map(|s| !s.trim().is_empty()).unwrap_or(false) {
        eprintln!("[eidos] LLM_DEBUG POST {url} model={}", params.model);
    }

    let response = req.send()?;
    let status = response.status();
    let body = response.text()?;
    if !status.is_success() {
        return Err(CoreError::LlmConfig(format!(
            "HTTP {}: {}",
            status.as_u16(),
            body.chars().take(900).collect::<String>()
        )));
    }

    let data: Value = serde_json::from_str(&body)?;
    let choices = data
        .get("choices")
        .and_then(|c| c.as_array())
        .filter(|c| !c.is_empty())
        .ok_or_else(|| {
            CoreError::LlmConfig(format!(
                "пустой choices: {}",
                body.chars().take(500).collect::<String>()
            ))
        })?;
    let msg = choices[0]
        .get("message")
        .cloned()
        .ok_or_else(|| CoreError::LlmConfig("нет message в choice".into()))?;
    Ok(normalize_assistant_message(msg))
}
