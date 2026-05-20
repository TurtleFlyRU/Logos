//! LSP-сервер Эйдос (фаза 6). Сейчас — каркас: пути, версия, план custom requests.

use eidos_core::{resolve_paths, VERSION};

fn main() {
    match resolve_paths() {
        Ok(paths) => {
            eprintln!("eidos-lsp {VERSION}");
            eprintln!("  repo: {}", paths.repo_root.display());
            eprintln!("  data: {}", paths.data_root.display());
            eprintln!("  WM:   {}", paths.working_memory_path().display());
            eprintln!();
            eprintln!("Следующий шаг: tower-lsp (stdio), custom requests:");
            eprintln!("  eidos/sessionList, eidos/contextPreview, eidos/memorySearch");
            eprintln!("См. crates/eidos-lsp/README.md");
        }
        Err(e) => {
            eprintln!("eidos-lsp: ошибка путей: {e}");
            std::process::exit(1);
        }
    }
}
