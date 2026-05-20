//! OpenAI-compatible SSE streaming (`stream: true`).

use std::time::Duration;

use futures_util::StreamExt;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use reqwest::Client;
use serde_json::{json, Value};

use crate::agents::{http_use_proxy, LlmRuntimeParams};
use crate::error::{CoreError, Result};
use crate::llm_sanitize::strip_model_channels;

const CONNECT_SEC: u64 = 30;

/// Результат потокового запроса без tools.
pub enum StreamTextOutcome {
    Text(String),
    /// В потоке появились tool_calls — нужен обычный non-stream запрос.
    ToolCallsInStream,
}

/// POST /chat/completions с ``stream: true``; дельты в ``on_delta``, финальный текст после санитизации.
pub fn chat_completions_stream_text(
    messages: &[Value],
    params: &LlmRuntimeParams,
    on_delta: &mut dyn FnMut(&str),
) -> Result<StreamTextOutcome> {
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| CoreError::LlmConfig(format!("tokio runtime: {e}")))?;
    rt.block_on(chat_completions_stream_text_async(messages, params, on_delta))
}

async fn chat_completions_stream_text_async(
    messages: &[Value],
    params: &LlmRuntimeParams,
    on_delta: &mut dyn FnMut(&str),
) -> Result<StreamTextOutcome> {
    if !params.omit_authorization_header && params.api_key.is_empty() {
        return Err(CoreError::LlmConfig(
            "нет API key и не задан omit_authorization_header".into(),
        ));
    }

    let url = format!("{}/chat/completions", params.base_url.trim_end_matches('/'));
    let payload = json!({
        "model": params.model,
        "messages": messages,
        "stream": true,
    });

    let mut builder = Client::builder()
        .connect_timeout(Duration::from_secs(CONNECT_SEC))
        .timeout(Duration::from_secs_f64(params.read_timeout_sec));
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

    if std::env::var("LLM_DEBUG")
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false)
    {
        eprintln!("[eidos] LLM_DEBUG POST {url} model={} stream=1", params.model);
    }

    let response = req.send().await?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().await.unwrap_or_default();
        return Err(CoreError::LlmConfig(format!(
            "HTTP {}: {}",
            status.as_u16(),
            body.chars().take(900).collect::<String>()
        )));
    }

    let mut raw = String::new();
    let mut saw_tool = false;
    let mut buffer = String::new();
    let mut stream = response.bytes_stream();

    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|e| CoreError::LlmConfig(format!("stream read: {e}")))?;
        buffer.push_str(&String::from_utf8_lossy(&chunk));

        while let Some(newline) = buffer.find('\n') {
            let line: String = buffer.drain(..=newline).collect();
            let line = line.trim_end_matches(['\r', '\n']);
            if line.is_empty() || line.starts_with(':') {
                continue;
            }
            let Some(data) = line.strip_prefix("data: ") else {
                continue;
            };
            let data = data.trim();
            if data == "[DONE]" {
                break;
            }
            let Ok(parsed) = serde_json::from_str::<Value>(data) else {
                continue;
            };
            let choice = parsed
                .get("choices")
                .and_then(|c| c.as_array())
                .and_then(|c| c.first());
            let Some(choice) = choice else {
                continue;
            };
            if choice.get("finish_reason").and_then(|v| v.as_str()) == Some("tool_calls") {
                saw_tool = true;
            }
            let delta = choice.get("delta").unwrap_or(&Value::Null);
            if delta.get("tool_calls").is_some() {
                saw_tool = true;
            }
            if let Some(content) = delta.get("content").and_then(|c| c.as_str()) {
                if !content.is_empty() {
                    raw.push_str(content);
                    on_delta(content);
                }
            }
        }
    }

    if saw_tool {
        return Ok(StreamTextOutcome::ToolCallsInStream);
    }
    let text = strip_model_channels(&raw);
    Ok(StreamTextOutcome::Text(text))
}
