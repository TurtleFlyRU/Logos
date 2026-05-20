//! Интеграция WM: запись событий ask совместима по полям с Python.

use eidos_core::working_memory::{make_cli_chat_event, WorkingMemory};
use eidos_core::resolve_paths;
use std::fs;

#[test]
fn ask_events_append_to_working_memory() {
    let paths = match resolve_paths() {
        Ok(p) => p,
        Err(_) => return,
    };
    let wm_path = paths.working_memory_path();
    let backup = fs::read_to_string(&wm_path).ok();

    let mut wm = WorkingMemory::open(&paths);
    let before = wm.document().events.len();
    wm.add_event(make_cli_chat_event(
        "user",
        "rust phase1 test ping",
        Some("test-session"),
    ))
    .expect("user event");
    wm.add_event(make_cli_chat_event(
        "assistant",
        "rust phase1 pong",
        Some("test-session"),
    ))
    .expect("assistant event");

    let wm2 = WorkingMemory::open(&paths);
    assert!(wm2.document().events.len() >= before + 2);
    let last = wm2.document().events.last().expect("last");
    assert_eq!(last.role.as_deref(), Some("assistant"));
    assert_eq!(last.event_type.as_deref(), Some("cli_chat"));

    if let Some(b) = backup {
        fs::write(&wm_path, b).ok();
    }
}
