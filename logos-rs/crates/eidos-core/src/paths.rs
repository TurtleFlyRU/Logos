//! Пути репозитория и данных (аналог `kernel/config.py`).

use std::env;
use std::path::{Path, PathBuf};

use thiserror::Error;

#[derive(Debug, Clone)]
pub struct Paths {
    pub repo_root: PathBuf,
    pub data_root: PathBuf,
}

#[derive(Debug, Error)]
pub enum PathsError {
    #[error("не удалось определить корень репозитория (задайте LOGOS_REPO_ROOT)")]
    RepoRootNotFound,
}

/// Корень git-репозитория Logos: `LOGOS_REPO_ROOT` или обход вверх от cwd до `eidos.py`.
#[must_use]
pub fn repo_root() -> Option<PathBuf> {
    if let Ok(raw) = env::var("LOGOS_REPO_ROOT") {
        let p = PathBuf::from(raw);
        if p.join("eidos.py").is_file() {
            return Some(p);
        }
    }
    let mut dir = env::current_dir().ok()?;
    loop {
        if dir.join("eidos.py").is_file() && dir.join("kernel").is_dir() {
            return Some(dir);
        }
        if !dir.pop() {
            break;
        }
    }
    None
}

/// `LOGOS_DATA_ROOT` или `<repo>/data`.
#[must_use]
pub fn data_root(repo: &Path) -> PathBuf {
    env::var("LOGOS_DATA_ROOT")
        .map(|s| PathBuf::from(s))
        .unwrap_or_else(|_| repo.join("data"))
}

/// Подставить ``<repo>/.env`` (не перезаписывает уже заданные переменные).
pub fn load_repo_dotenv(repo: &Path) {
    let path = repo.join(".env");
    if path.is_file() {
        let _ = dotenvy::from_path(&path);
    }
}

/// Разрешить пути для текущего процесса.
pub fn resolve_paths() -> Result<Paths, PathsError> {
    let repo_root = repo_root().ok_or(PathsError::RepoRootNotFound)?;
    load_repo_dotenv(&repo_root);
    let data_root = data_root(&repo_root);
    Ok(Paths {
        repo_root,
        data_root,
    })
}

impl Paths {
  /// `data/working/current.json`
    #[must_use]
    pub fn working_memory_path(&self) -> PathBuf {
        self.data_root.join("working").join("current.json")
    }

    pub fn cli_sessions_dir(&self) -> PathBuf {
        self.data_root.join("cli_sessions")
    }

    pub fn cli_session_latest_path(&self) -> PathBuf {
        self.cli_sessions_dir().join("latest.json")
    }

    pub fn cli_session_path(&self, session_id: &str) -> PathBuf {
        self.cli_sessions_dir().join(format!("{session_id}.json"))
    }

    pub fn sleep_last_words_path(&self) -> PathBuf {
        self.data_root.join("sleep").join("last_words.json")
    }

    /// `data/episodic/episodes.db` (как ``kernel.config.EPISODIC_DB_PATH``).
    #[must_use]
    pub fn episodic_db_path(&self) -> PathBuf {
        self.data_root.join("episodic").join("episodes.db")
    }

    /// `data/semantic/knowledge.db` (как ``kernel.config.SEMANTIC_DB_PATH``).
    #[must_use]
    pub fn semantic_db_path(&self) -> PathBuf {
        self.data_root.join("semantic").join("knowledge.db")
    }

    /// `data/journal/` (markdown-энтри, как ``kernel.config.JOURNAL_DIR``).
    #[must_use]
    pub fn journal_dir(&self) -> PathBuf {
        self.data_root.join("journal")
    }

    /// `data/external/documents.db`
    #[must_use]
    pub fn external_db_path(&self) -> PathBuf {
        self.data_root.join("external").join("documents.db")
    }

    /// Кандидаты agents.yaml (порядок как в Python `cli/agent_backends.py`).
    #[must_use]
    pub fn agents_config_candidates(&self) -> Vec<PathBuf> {
        let mut out = Vec::new();
        if let Ok(raw) = env::var("EIDOS_AGENTS_CONFIG") {
            out.push(PathBuf::from(raw));
        }
        out.push(self.data_root.join("config").join("agents.yaml"));
        out.push(self.repo_root.join("config").join("agents.yaml"));
        out.push(
            self.repo_root
                .join("config")
                .join("agents.defaults.yaml"),
        );
        out
    }

    /// Первый существующий файл конфигурации агентов.
    #[must_use]
    pub fn find_agents_config(&self) -> Option<PathBuf> {
        self.agents_config_candidates()
            .into_iter()
            .find(|p| p.is_file())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_paths_from_repo() {
        let Some(repo) = repo_root() else {
            return;
        };
        let paths = resolve_paths().expect("paths");
        assert_eq!(paths.repo_root, repo);
        assert!(paths.data_root.ends_with("data") || env::var("LOGOS_DATA_ROOT").is_ok());
    }
}
