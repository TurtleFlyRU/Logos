//! Инструменты CLI (фаза 2: read_workspace_file, eidos_echo).

use std::fs;
use std::path::{Component, Path, PathBuf};

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::paths::Paths;

const MAX_READ_FILE_BYTES: u64 = 65_536;

pub fn tool_search_enabled() -> bool {
    if !tools_enabled() {
        return false;
    }
    let v = std::env::var("EIDOS_TOOL_SEARCH")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

pub const TOOL_SEARCH_FN: &str = "eidos_tool_search";

pub fn is_tool_search_meta_name(name: &str) -> bool {
    name.trim() == TOOL_SEARCH_FN
}

/// Краткая справка для ``/tools`` без Python sidecar.
pub fn format_tools_help_rust() -> String {
    let tools = tools_enabled();
    let search = tool_search_enabled();
    format!(
        "Инструменты Эйдос\n\nEIDOS_TOOLS={}\nEIDOS_TOOL_SEARCH={}\n\n\
         Полный каталог: запустите с Python sidecar или ``/tools`` в CLI.\n",
        if tools { "on" } else { "off" },
        if search { "on" } else { "off" },
    )
}

pub fn tools_enabled() -> bool {
    let v = std::env::var("EIDOS_TOOLS")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

pub fn max_tool_rounds() -> u32 {
    std::env::var("EIDOS_TOOL_ROUNDS")
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .map(|n: u32| n.clamp(1, 32))
        .unwrap_or(8)
}

pub fn progress_echo_enabled() -> bool {
    let v = std::env::var("LLM_PROGRESS")
        .unwrap_or_else(|_| "1".into())
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

pub fn builtin_tool_specs() -> Vec<Value> {
    let mut specs = vec![
        json!({
            "type": "function",
            "function": {
                "name": "eidos_echo",
                "description": "Вернуть переданный текст (отладка цикла инструментов).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": { "type": "string" }
                    },
                    "required": ["text"]
                }
            }
        }),
        json!({
            "type": "function",
            "function": {
                "name": "read_workspace_file",
                "description": "Прочитать текстовый файл внутри корня репозитория Logos (относительный путь).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": { "type": "string", "description": "например README.md" }
                    },
                    "required": ["path"]
                }
            }
        }),
    ];
    if http_fetch_enabled() {
        specs.push(json!({
            "type": "function",
            "function": {
                "name": "fetch_https_url",
                "description": "GET по публичному http(s) URL (по умолчанию вкл.; выкл. EIDOS_HTTP_FETCH=0).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": { "type": "string" }
                    },
                    "required": ["url"]
                }
            }
        }));
    }
    specs
}

/// HTTP fetch tool; по умолчанию вкл. (как ``EIDOS_TOOLS`` / Python ``http_fetch_tool_enabled``).
pub fn http_fetch_enabled() -> bool {
    let v = std::env::var("EIDOS_HTTP_FETCH")
        .unwrap_or_else(|_| "1".into())
        .trim()
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

/// Playwright-инструменты (как ``cli.browser_tools``); по умолчанию вкл.;
/// долгоживущий sidecar нужен для сохранения сессии браузера.
pub fn playwright_tools_enabled() -> bool {
    let v = std::env::var("EIDOS_PLAYWRIGHT")
        .unwrap_or_else(|_| "1".into())
        .trim()
        .to_ascii_lowercase();
    !matches!(v.as_str(), "0" | "false" | "no" | "off")
}

#[must_use]
pub fn is_playwright_tool_name(name: &str) -> bool {
    matches!(
        name,
        "browser_open"
            | "browser_close"
            | "browser_navigate"
            | "browser_snapshot"
            | "browser_click"
            | "browser_fill"
            | "browser_press"
            | "browser_screenshot"
    )
}

pub fn execute_tool(paths: &Paths, name: &str, arguments_json: &str) -> String {
    match execute_tool_inner(paths, name, arguments_json) {
        Ok(s) => s,
        Err(e) => json!({ "error": e.to_string() }).to_string(),
    }
}

fn execute_tool_inner(paths: &Paths, name: &str, arguments_json: &str) -> Result<String> {
    let args: Value = serde_json::from_str(arguments_json).unwrap_or(json!({}));
    match name {
        "eidos_echo" => {
            let text = args
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Ok(text)
        }
        "read_workspace_file" => read_workspace_file(paths, &args),
        "fetch_https_url" => fetch_https_url(paths, &args),
        _ => Err(CoreError::Tool(format!("неизвестный инструмент: {name}"))),
    }
}

fn read_workspace_file(paths: &Paths, args: &Value) -> Result<String> {
    let rel = args
        .get("path")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if rel.is_empty() {
        return Err(CoreError::Tool("path required".into()));
    }
    let target = resolve_under_repo(&paths.repo_root, rel)?;
    if !target.is_file() {
        return Err(CoreError::NotFound(target));
    }
    let data = fs::read(&target)?;
    if data.len() as u64 > MAX_READ_FILE_BYTES {
        return Err(CoreError::Tool(format!(
            "файл больше {MAX_READ_FILE_BYTES} байт"
        )));
    }
    Ok(String::from_utf8_lossy(&data).into_owned())
}

fn fetch_https_url(_paths: &Paths, args: &Value) -> Result<String> {
    if !http_fetch_enabled() {
        return Err(CoreError::Tool(
            "fetch_https_url выключен (EIDOS_HTTP_FETCH=0/false/no/off)".into(),
        ));
    }
    let url = args
        .get("url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if url.is_empty() {
        return Err(CoreError::Tool("url обязателен".into()));
    }
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err(CoreError::Tool("только http/https".into()));
    }
    let host = url
        .split('/')
        .nth(2)
        .unwrap_or("")
        .split(':')
        .next()
        .unwrap_or("")
        .to_lowercase();
    if host == "localhost" || host.starts_with("127.") {
        return Err(CoreError::Tool("локальные хосты запрещены".into()));
    }

    let mut builder = reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(15));
    if !crate::agents::http_use_proxy() {
        builder = builder.no_proxy();
    }
    let client = builder.build()?;
    let resp = client.get(url).send()?;
    let status = resp.status();
    let bytes = resp.bytes()?;
    let max = 384 * 1024;
    let slice = if bytes.len() > max { &bytes[..max] } else { &bytes[..] };
    let text = String::from_utf8_lossy(slice);
    Ok(format!("HTTP {status}\n{text}"))
}

fn resolve_under_repo(repo_root: &Path, rel: &str) -> Result<PathBuf> {
    let rel = rel.replace('\\', "/");
    let rel = rel.trim_start_matches('/');
    let path = Path::new(rel);
    for comp in path.components() {
        if matches!(comp, Component::ParentDir) {
            return Err(CoreError::Tool("path must not contain '..'".into()));
        }
    }
    let root = repo_root.canonicalize().unwrap_or_else(|_| repo_root.to_path_buf());
    let target = root.join(path);
    let target = target.canonicalize().unwrap_or(target);
    target
        .strip_prefix(&root)
        .map_err(|_| CoreError::Tool("path outside repository".into()))?;
    Ok(target)
}
