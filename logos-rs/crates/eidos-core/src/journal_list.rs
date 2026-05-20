//! Список markdown-файлов журнала (parity ``kernel.journal.Journal`` — только `*.md` в корне ``journal/``).

use std::fs;
use std::path::PathBuf;

use crate::error::{CoreError, Result};
use crate::paths::Paths;

/// Элемент списка: путь относительно `journal_dir` и время модификации (unix sec).
#[derive(Debug, Clone)]
pub struct JournalEntryPath {
    pub relative: PathBuf,
    pub modified_secs: Option<u64>,
}

/// Отсортировано по mtime убыв. (новые первые).
pub fn list_journal_markdown(paths: &Paths, limit: usize) -> Result<Vec<JournalEntryPath>> {
    let dir = paths.journal_dir();
    if !dir.is_dir() {
        return Ok(vec![]);
    }
    let mut items: Vec<JournalEntryPath> = Vec::new();
    for ent in fs::read_dir(&dir).map_err(|e| {
        CoreError::WorkingMemory(format!("journal read_dir: {e}"))
    })? {
        let ent = ent.map_err(|e| CoreError::WorkingMemory(format!("journal entry: {e}")))?;
        let path = ent.path();
        let ext_ok = path
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| e.eq_ignore_ascii_case("md"));
        if !ext_ok {
            continue;
        }
        let meta = fs::metadata(&path).ok();
        let modified_secs = meta.and_then(|m| m.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok().map(|d| d.as_secs())));
        let rel = path
            .strip_prefix(&dir)
            .unwrap_or(path.as_path())
            .to_path_buf();
        items.push(JournalEntryPath {
            relative: rel,
            modified_secs,
        });
    }
    items.sort_by(|a, b| {
        b.modified_secs
            .cmp(&a.modified_secs)
            .then_with(|| a.relative.cmp(&b.relative))
    });
    items.truncate(limit);
    Ok(items)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn lists_md_sorted() {
        let root = std::env::temp_dir().join(format!(
            "eidos_journal_list_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let paths = Paths {
            repo_root: PathBuf::from("/tmp"),
            data_root: root.join("data"),
        };
        let jdir = paths.journal_dir();
        std::fs::create_dir_all(&jdir).unwrap();
        std::fs::File::create(jdir.join("a.md")).unwrap();
        std::thread::sleep(std::time::Duration::from_millis(12));
        std::fs::File::create(jdir.join("b.md")).unwrap();
        let list = list_journal_markdown(&paths, 10).unwrap();
        assert_eq!(list.len(), 2);
        assert!(list[0].modified_secs >= list[1].modified_secs);
    }
}
