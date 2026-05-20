//! Разрешение ``Paths`` для LSP: workspace из клиента, cwd, каталог бинарника.

use std::env;
use std::path::PathBuf;

use eidos_core::{repo_root_from_dir, resolve_paths, resolve_paths_from_repo, Paths};
use tower_lsp::lsp_types::{InitializeParams, Url};

/// Найти корень Logos для сессии LSP (не падает при старте процесса — только в ``initialize``).
pub fn resolve_lsp_paths(params: &InitializeParams) -> Result<Paths, String> {
    if let Ok(raw) = env::var("LOGOS_REPO_ROOT") {
        let p = PathBuf::from(raw.trim());
        if let Ok(paths) = resolve_paths_from_repo(&p) {
            return Ok(paths);
        }
    }

    if let Some(folders) = &params.workspace_folders {
        for folder in folders {
            if let Some(dir) = url_to_dir(&folder.uri) {
                if let Ok(paths) = paths_from_start_dir(dir) {
                    return Ok(paths);
                }
            }
        }
    }

    if let Some(uri) = &params.root_uri {
        if let Some(dir) = url_to_dir(uri) {
            if let Ok(paths) = paths_from_start_dir(dir) {
                return Ok(paths);
            }
        }
    }

    if let Ok(paths) = resolve_paths() {
        return Ok(paths);
    }

    if let Ok(exe) = env::current_exe() {
        if let Some(dir) = exe.parent() {
            if let Some(repo) = repo_root_from_dir(dir.to_path_buf()) {
                return resolve_paths_from_repo(&repo).map_err(|e| e.to_string());
            }
        }
    }

    Err(
        "не найден корень Logos (eidos.py): откройте workspace = корень репозитория \
         или задайте LOGOS_REPO_ROOT"
            .into(),
    )
}

fn paths_from_start_dir(start: PathBuf) -> Result<Paths, String> {
    let repo = repo_root_from_dir(start).ok_or_else(|| {
        "в workspace нет eidos.py — откройте папку Logos, а не только logos-rs".to_string()
    })?;
    resolve_paths_from_repo(&repo).map_err(|e| e.to_string())
}

fn url_to_dir(url: &Url) -> Option<PathBuf> {
    url.to_file_path().ok()
}
