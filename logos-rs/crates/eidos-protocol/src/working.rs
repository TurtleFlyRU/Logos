//! Рабочая память: `data/working/current.json`.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Одно событие в `events[]`.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct WmEvent {
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub content: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub text: Option<String>,
    pub timestamp: f64,
    #[serde(default)]
    pub event_type: Option<String>,
    #[serde(default)]
    pub cli_session_id: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub tool_calls: Option<Vec<ToolCall>>,
    #[serde(default)]
    pub tool_call_id: Option<String>,
    #[serde(flatten)]
    pub extra: Value,
}

/// OpenAI-style tool call на сообщении assistant.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub id: String,
    #[serde(rename = "type")]
    pub call_type: String,
    pub function: FunctionCall,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FunctionCall {
    pub name: String,
    pub arguments: String,
}

/// Документ `current.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkingMemoryDocument {
    #[serde(default)]
    pub session_id: Option<String>,
    #[serde(default)]
    pub context: WmContext,
    #[serde(default)]
    pub events: Vec<WmEvent>,
    #[serde(default)]
    pub event_count: u64,
    #[serde(default)]
    pub attention_slots: Vec<AttentionSlot>,
    #[serde(default)]
    pub suggestions: Vec<Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WmContext {
    #[serde(default)]
    pub cli_session_id: Option<String>,
    #[serde(default)]
    pub cli_transport: Option<String>,
    #[serde(default)]
    pub session_title: Option<String>,
    #[serde(default)]
    pub session_tags: Option<Vec<String>>,
    #[serde(default)]
    pub user_display_name: Option<String>,
    #[serde(flatten)]
    pub extra: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AttentionSlot {
    pub timestamp: f64,
    pub role: String,
    pub summary: String,
}

impl WmEvent {
    /// Текст события (как в Python: content → message → text).
    #[must_use]
    pub fn text_content(&self) -> Option<&str> {
        self.content
            .as_deref()
            .or(self.message.as_deref())
            .or(self.text.as_deref())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wm_event_roundtrip() {
        let ev = WmEvent {
            role: Some("user".into()),
            content: Some("привет".into()),
            message: None,
            text: None,
            timestamp: 1.0,
            event_type: Some("cli_chat".into()),
            cli_session_id: Some("00000000-0000-0000-0000-000000000000".into()),
            tags: vec!["cli".into()],
            tool_calls: None,
            tool_call_id: None,
            extra: Value::Null,
        };
        let json = serde_json::to_string(&ev).unwrap();
        let back: WmEvent = serde_json::from_str(&json).unwrap();
        assert_eq!(back.text_content(), Some("привет"));
    }
}
