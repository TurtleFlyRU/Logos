//! Boot для CLI: полный ``kernel.boot`` через Python sidecar (по умолчанию).

use std::fs;

use serde_json::Value;

use crate::error::Result;
use crate::paths::Paths;
use crate::py_sidecar::{self, Sidecar};
use crate::working_memory::WorkingMemory;

const BOOK_SNIPPET_CHARS: usize = 6000;

/// Сформировать boot-текст и сохранить в ``working.context.boot_context``.
pub fn run_cli_chat_boot(
    paths: &Paths,
    wm: &mut WorkingMemory,
    sidecar: &mut Sidecar,
) -> Result<String> {
    if py_sidecar::use_python_boot() {
        match sidecar.run_cli_chat_boot() {
            Ok(()) => {
                wm.reload();
                return Ok(boot_context_text_from_wm(wm));
            }
            Err(e) => {
                eprintln!("[eidos] Python boot недоступен ({e}); краткий Rust-boot.");
            }
        }
    }
    run_cli_chat_boot_rust(paths, wm)
}

fn boot_context_text_from_wm(wm: &WorkingMemory) -> String {
    wm.document()
        .context
        .extra
        .get("boot_context")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

/// Упрощённый boot — ``EIDOS_RUST_BOOT=1`` или сбой Python.
fn run_cli_chat_boot_rust(paths: &Paths, wm: &mut WorkingMemory) -> Result<String> {
    let mut parts = Vec::new();
    parts.push("## Boot (Rust CLI, краткий)\n".to_string());

    let book_path = paths.repo_root.join("BOOK.md");
    if book_path.is_file() {
        if let Ok(text) = fs::read_to_string(&book_path) {
            let snip: String = text.chars().take(BOOK_SNIPPET_CHARS).collect();
            parts.push(format!("### Из BOOK.md\n{snip}"));
        }
    }

    let lw_path = paths.sleep_last_words_path();
    if lw_path.is_file() {
        if let Ok(raw) = fs::read_to_string(&lw_path) {
            if let Ok(v) = serde_json::from_str::<Value>(&raw) {
                if let Some(words) = v.get("words").and_then(|w| w.as_str()) {
                    parts.push(format!("### Последние слова (sleep)\n{words}"));
                }
            }
        }
    }

    if let Some(cfg) = paths.find_agents_config() {
        parts.push(format!("### Конфиг LLM\n`{}`", cfg.display()));
    }

    let boot_text = parts.join("\n\n");
    wm.set_context("boot_context", Value::String(boot_text.clone()));
    wm.save()?;
    Ok(boot_text)
}
