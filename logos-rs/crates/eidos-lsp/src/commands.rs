//! Обработчики ``workspace/executeCommand`` (``eidos.*``).

use eidos_core::{
    list_journal_markdown, list_sessions, read_latest, read_session_budget_history,
    resolve_paths, working_memory::WorkingMemory, JournalEntryPath, Paths,
    VERSION,
};
use serde::Serialize;
use serde_json::{json, Value};

pub const CMD_SESSION_LIST: &str = "eidos.sessionList";
pub const CMD_CONTEXT_PREVIEW: &str = "eidos.contextPreview";
pub const CMD_MEMORY_SEARCH: &str = "eidos.memorySearch";

pub const ALL_COMMANDS: &[&str] = &[
    CMD_SESSION_LIST,
    CMD_CONTEXT_PREVIEW,
    CMD_MEMORY_SEARCH,
];

#[derive(Debug, Serialize)]
pub struct ContextPreviewDto {
    pub version: &'static str,
    pub repo_root: String,
    pub data_root: String,
    pub wm_path: String,
    pub session_id: Option<String>,
    pub wm_event_count: u64,
    pub budget_history_len: usize,
    pub last_budget: Option<eidos_core::BudgetSnapshot>,
}

#[derive(Debug, Serialize)]
pub struct JournalHitDto {
    pub relative: String,
    pub modified_secs: Option<u64>,
}

/// Выполнить команду LSP; ``arguments[0]`` — опциональная строка запроса для memorySearch.
pub fn execute(paths: &Paths, command: &str, arguments: &[Value]) -> Result<Value, String> {
    match command {
        CMD_SESSION_LIST => session_list(paths),
        CMD_CONTEXT_PREVIEW => context_preview(paths),
        CMD_MEMORY_SEARCH => memory_search(paths, arguments),
        other => Err(format!("неизвестная команда: {other}")),
    }
}

fn session_list(paths: &Paths) -> Result<Value, String> {
    let sessions = list_sessions(paths).map_err(|e| e.to_string())?;
    serde_json::to_value(&sessions).map_err(|e| e.to_string())
}

fn context_preview(paths: &Paths) -> Result<Value, String> {
    let wm = WorkingMemory::open(paths);
    let session_id = read_latest(paths).or_else(|| {
        wm.document()
            .context
            .cli_session_id
            .clone()
    });
    let history = session_id
        .as_deref()
        .map(|sid| read_session_budget_history(paths, sid))
        .transpose()
        .map_err(|e| e.to_string())?
        .unwrap_or_default();
    let last_budget = history.last().cloned();
    let dto = ContextPreviewDto {
        version: VERSION,
        repo_root: paths.repo_root.display().to_string(),
        data_root: paths.data_root.display().to_string(),
        wm_path: paths.working_memory_path().display().to_string(),
        session_id,
        wm_event_count: wm.document().events.len() as u64,
        budget_history_len: history.len(),
        last_budget,
    };
    serde_json::to_value(&dto).map_err(|e| e.to_string())
}

fn memory_search(paths: &Paths, arguments: &[Value]) -> Result<Value, String> {
    let query = arguments
        .first()
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let limit = 32usize;
    let entries = list_journal_markdown(paths, limit).map_err(|e| e.to_string())?;
    let hits: Vec<JournalHitDto> = entries
        .into_iter()
        .filter(|e| {
            if query.is_empty() {
                return true;
            }
            e.relative
                .to_string_lossy()
                .to_lowercase()
                .contains(&query)
        })
        .map(journal_hit)
        .collect();
    Ok(json!({
        "query": query,
        "hits": hits,
        "note": "полнотекстовый поиск — Python kernel.journal; здесь список файлов журнала"
    }))
}

fn journal_hit(e: JournalEntryPath) -> JournalHitDto {
    JournalHitDto {
        relative: e.relative.to_string_lossy().into_owned(),
        modified_secs: e.modified_secs,
    }
}

/// Печать путей (режим ``--info``, без LSP).
pub fn print_paths_info() -> Result<(), String> {
    let paths = resolve_paths().map_err(|e| e.to_string())?;
    eprintln!("eidos-lsp {VERSION}");
    eprintln!("  repo: {}", paths.repo_root.display());
    eprintln!("  data: {}", paths.data_root.display());
    eprintln!("  WM:   {}", paths.working_memory_path().display());
    eprintln!();
    eprintln!("Команды LSP (workspace/executeCommand):");
    for cmd in ALL_COMMANDS {
        eprintln!("  {cmd}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use eidos_core::resolve_paths;

    #[test]
    fn session_list_serializes() {
        let paths = match resolve_paths() {
            Ok(p) => p,
            Err(_) => return,
        };
        let v = session_list(&paths).expect("session_list");
        assert!(v.is_array());
    }
}
