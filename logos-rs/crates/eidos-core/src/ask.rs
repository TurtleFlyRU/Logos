//! Один ход ask: LLM + запись в WM.

use crate::agents::get_llm_runtime_params;
use crate::context::build_ask_messages;
use crate::error::Result;
use crate::llm::chat_completions_text;
use crate::paths::{resolve_paths, Paths};
use crate::working_memory::{make_cli_chat_event, WorkingMemory};

/// Выполнить один запрос; при `record_wm` — user/assistant в `current.json`.
pub fn run_ask(
    question: &str,
    profile_name: Option<&str>,
    record_wm: bool,
) -> Result<String> {
    let paths = resolve_paths()?;
    let params = get_llm_runtime_params(&paths, profile_name)?;
    let messages = build_ask_messages(&paths, question);
    let reply = chat_completions_text(&messages, &params)?;
    if record_wm {
        record_ask_in_wm(&paths, question, &reply)?;
    }
    Ok(reply)
}

fn record_ask_in_wm(paths: &Paths, question: &str, reply: &str) -> Result<()> {
    let mut wm = WorkingMemory::open(paths);
    let sid = wm
        .document()
        .context
        .cli_session_id
        .clone()
        .or_else(|| std::env::var("EIDOS_CLI_SESSION_ID").ok());
    wm.set_context("cli_transport", serde_json::json!("eidos"));
    wm.add_event(make_cli_chat_event("user", question, sid.as_deref()))?;
    wm.add_event(make_cli_chat_event("assistant", reply, sid.as_deref()))?;
    Ok(())
}
