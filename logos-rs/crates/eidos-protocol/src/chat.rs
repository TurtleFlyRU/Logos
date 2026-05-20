//! Сообщения для OpenAI-compatible chat/completions.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::working::ToolCall;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "role", rename_all = "lowercase")]
pub enum ChatMessage {
    System {
        content: String,
        #[serde(flatten)]
        extra: Value,
    },
    User {
        content: String,
        #[serde(flatten)]
        extra: Value,
    },
    Assistant {
        #[serde(default)]
        content: Option<String>,
        #[serde(default)]
        tool_calls: Option<Vec<ToolCall>>,
        #[serde(flatten)]
        extra: Value,
    },
    Tool {
        tool_call_id: String,
        content: String,
        #[serde(flatten)]
        extra: Value,
    },
}
