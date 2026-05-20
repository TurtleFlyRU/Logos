//! Рабочая память: `data/working/current.json`.

use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use eidos_protocol::working::{AttentionSlot, ToolCall, WmContext, WmEvent, WorkingMemoryDocument};

use crate::paths::Paths;
use serde_json::{json, Value};

use crate::error::{CoreError, Result};

const ATTENTION_SLOT_LIMIT: usize = 4;

pub struct WorkingMemory {
    path: std::path::PathBuf,
    doc: WorkingMemoryDocument,
}

impl WorkingMemory {
    #[must_use]
    pub fn open(paths: &Paths) -> Self {
        let path = paths.working_memory_path();
        let doc = load_document(&path);
        Self { path, doc }
    }

    pub fn document(&self) -> &WorkingMemoryDocument {
        &self.doc
    }

    /// Перечитать ``current.json`` с диска (после Python sidecar).
    pub fn reload(&mut self) {
        self.doc = load_document(&self.path);
    }

    pub fn set_context(&mut self, key: &str, value: Value) {
        match key {
            "cli_session_id" => {
                if let Some(s) = value.as_str() {
                    self.doc.context.cli_session_id = Some(s.to_string());
                }
            }
            "cli_transport" => {
                if let Some(s) = value.as_str() {
                    self.doc.context.cli_transport = Some(s.to_string());
                }
            }
            "user_display_name" => {
                if let Some(s) = value.as_str() {
                    self.doc.context.user_display_name = Some(s.to_string());
                }
            }
            _ => {
                if !self.doc.context.extra.is_object() {
                    self.doc.context.extra = json!({});
                }
                if let Some(obj) = self.doc.context.extra.as_object_mut() {
                    obj.insert(key.to_string(), value);
                }
            }
        }
    }

    /// Добавить событие (упрощённо относительно Python: без episodic/journal).
    pub fn add_event(&mut self, mut event: WmEvent) -> Result<()> {
        event.timestamp = now_ts();
        self.update_attention(&event);
        self.doc.events.push(event);
        self.doc.event_count = self.doc.events.len() as u64;
        self.save()
    }

    fn update_attention(&mut self, event: &WmEvent) {
        let Some(content) = event.text_content() else {
            return;
        };
        if content.is_empty() {
            return;
        }
        let summary: String = content.chars().take(240).collect();
        let role = event
            .role
            .clone()
            .unwrap_or_else(|| "event".to_string());
        self.doc.attention_slots.push(AttentionSlot {
            timestamp: event.timestamp,
            role,
            summary,
        });
        if self.doc.attention_slots.len() > ATTENTION_SLOT_LIMIT {
            let drain = self.doc.attention_slots.len() - ATTENTION_SLOT_LIMIT;
            self.doc.attention_slots.drain(0..drain);
        }
    }

    pub fn save(&self) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let json = serde_json::to_string_pretty(&self.doc)?;
        atomic_write_bytes(&self.path, json.as_bytes())?;
        Ok(())
    }
}

fn load_document(path: &std::path::Path) -> WorkingMemoryDocument {
    if !path.is_file() {
        return default_document();
    }
    let Ok(data) = fs::read_to_string(path) else {
        return default_document();
    };
    if data.trim().is_empty() {
        return default_document();
    }
    match serde_json::from_str::<WorkingMemoryDocument>(&data) {
        Ok(mut doc) => {
            if doc.event_count == 0 && !doc.events.is_empty() {
                doc.event_count = doc.events.len() as u64;
            }
            doc
        }
        Err(_) => default_document(),
    }
}

fn default_document() -> WorkingMemoryDocument {
    WorkingMemoryDocument {
        session_id: None,
        context: WmContext::default(),
        events: Vec::new(),
        event_count: 0,
        attention_slots: Vec::new(),
        suggestions: Vec::new(),
    }
}

fn now_ts() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

pub(crate) fn atomic_write_bytes(path: &std::path::Path, bytes: &[u8]) -> Result<()> {
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, bytes)?;
    fs::rename(tmp, path).map_err(|e| {
        CoreError::WorkingMemory(format!("не удалось сохранить {}: {e}", path.display()))
    })?;
    Ok(())
}

pub fn make_cli_chat_event(role: &str, content: &str, session_id: Option<&str>) -> WmEvent {
    make_cli_chat_event_full(role, Some(content.to_string()), None, None, session_id)
}

pub fn make_cli_chat_event_full(
    role: &str,
    content: Option<String>,
    tool_calls: Option<Vec<ToolCall>>,
    tool_call_id: Option<String>,
    session_id: Option<&str>,
) -> WmEvent {
    WmEvent {
        role: Some(role.to_string()),
        content,
        message: None,
        text: None,
        timestamp: 0.0,
        event_type: Some("cli_chat".to_string()),
        cli_session_id: session_id.map(str::to_string),
        tags: vec!["cli".to_string(), "eidos".to_string(), "rust".to_string()],
        tool_calls,
        tool_call_id,
        extra: Value::Null,
    }
}

pub fn clear_working_memory(paths: &Paths) -> Result<()> {
    let mut wm = WorkingMemory::open(paths);
    wm.doc = default_document();
    wm.save()
}
