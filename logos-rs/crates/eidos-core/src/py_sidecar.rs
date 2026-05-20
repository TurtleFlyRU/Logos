//! Python parity: долгоживущий ``kernel/eidos_sidecar.py`` (JSON-lines) или one-shot fallback.

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};

use serde_json::{json, Value};

use crate::error::{CoreError, Result};
use crate::paths::Paths;

pub(crate) fn env_no_sidecar() -> bool {
    matches!(
        std::env::var("EIDOS_RUST_NO_SIDECAR").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

pub fn use_python_boot() -> bool {
    !matches!(
        std::env::var("EIDOS_RUST_BOOT").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

pub fn use_python_context() -> bool {
    !matches!(
        std::env::var("EIDOS_RUST_CONTEXT").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

/// Клиент sidecar на время ``eidos chat``.
pub struct Sidecar {
    paths: Paths,
    daemon: Option<SidecarDaemon>,
}

struct SidecarDaemon {
    child: Child,
    stdin: std::process::ChildStdin,
    reader: BufReader<std::process::ChildStdout>,
}

impl Sidecar {
    pub fn open(paths: Paths) -> Self {
        let mut s = Self {
            paths,
            daemon: None,
        };
        if !env_no_sidecar() {
            if let Ok(d) = SidecarDaemon::spawn(&s.paths) {
                s.daemon = Some(d);
            }
        }
        s
    }

    fn call(&mut self, req: Value) -> Result<Value> {
        if let Some(d) = self.daemon.as_mut() {
            d.call(&req)
        } else {
            oneshot_call(&self.paths, &req)
        }
    }

    pub fn seed_identity(&mut self) -> Result<()> {
        self.call(json!({"op": "seed_identity"}))?;
        Ok(())
    }

    pub fn run_cli_chat_boot(&mut self) -> Result<()> {
        self.call(json!({"op": "boot"}))?;
        Ok(())
    }

    pub fn context_metrics(
        &mut self,
        session_id: &str,
        user_message: Option<&str>,
    ) -> Result<serde_json::Value> {
        let mut req = json!({
            "op": "context_metrics",
            "session_id": session_id,
        });
        if let Some(u) = user_message.filter(|s| !s.is_empty()) {
            req["user_message"] = json!(u);
        }
        self.call(req)
    }

    pub fn startup_reports(&mut self, mode: &str) -> Result<(String, String)> {
        let r = self.call(json!({"op": "startup_reports", "mode": mode}))?;
        let env = r.get("env").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let budget = r
            .get("budget")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        Ok((env, budget))
    }

    pub fn active_memory_block(
        &mut self,
        session_id: &str,
        user_message: &str,
        max_chars: usize,
    ) -> Result<String> {
        let mut req = json!({
            "op": "active_memory_block",
            "session_id": session_id,
            "max_chars": max_chars,
        });
        if !user_message.trim().is_empty() {
            req["user_message"] = json!(user_message);
        }
        let r = self.call(req)?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    /// Блок семантических принципов (parity ``format_semantic_principles_block``).
    pub fn semantic_principles_block(&mut self, limit: usize, min_confidence: f64) -> Result<String> {
        let r = self.call(json!({
            "op": "semantic_principles_block",
            "limit": limit,
            "min_confidence": min_confidence,
        }))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn playwright_tool_specs(&mut self) -> Result<Vec<Value>> {
        let r = self.call(json!({"op": "playwright_tool_specs"}))?;
        let specs = r.get("specs").cloned().unwrap_or(Value::Array(vec![]));
        match specs {
            Value::Array(arr) => Ok(arr),
            _ => Ok(vec![]),
        }
    }

    /// Выполнить браузерный инструмент Playwright (stateful в процессе sidecar).
    pub fn playwright_execute(&mut self, name: &str, arguments_json: &str) -> Result<String> {
        let r = self.call(json!({
            "op": "playwright_execute",
            "name": name,
            "arguments_json": arguments_json,
        }))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn memory_tool_specs(&mut self) -> Result<Vec<Value>> {
        let r = self.call(json!({"op": "memory_tool_specs"}))?;
        let specs = r.get("specs").cloned().unwrap_or(Value::Array(vec![]));
        match specs {
            Value::Array(arr) => Ok(arr),
            _ => Ok(vec![]),
        }
    }

    pub fn memory_execute(&mut self, name: &str, arguments_json: &str) -> Result<String> {
        let r = self.call(json!({
            "op": "memory_execute",
            "name": name,
            "arguments_json": arguments_json,
        }))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn memory_help(&mut self) -> Result<String> {
        let r = self.call(json!({"op": "memory_help"}))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn tools_help(&mut self) -> Result<String> {
        let r = self.call(json!({"op": "tools_help"}))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn tools_catalog_block(&mut self, line: &str, max_chars: u64) -> Result<String> {
        let r = self.call(json!({
            "op": "tools_catalog_block",
            "line": line,
            "max_chars": max_chars,
        }))?;
        Ok(r.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string())
    }

    pub fn tool_search_build_specs(&mut self, loaded: &[String]) -> Result<Vec<Value>> {
        let r = self.call(json!({
            "op": "tool_search_build_specs",
            "loaded": loaded,
        }))?;
        let specs = r
            .get("specs")
            .cloned()
            .unwrap_or(Value::Array(vec![]));
        serde_json::from_value(specs).map_err(|e| CoreError::Sidecar(format!("specs: {e}")))
    }

    pub fn tool_search_execute(
        &mut self,
        loaded: &[String],
        arguments_json: &str,
    ) -> Result<(String, Vec<String>)> {
        let r = self.call(json!({
            "op": "tool_search_execute",
            "loaded": loaded,
            "arguments_json": arguments_json,
        }))?;
        let text = r
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let loaded_out: Vec<String> = r
            .get("loaded")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        Ok((text, loaded_out))
    }

    pub fn build_chat_messages(
        &mut self,
        session_id: &str,
        user_message: &str,
    ) -> Result<Vec<Value>> {
        let r = self.call(json!({
            "op": "build_messages",
            "session_id": session_id,
            "user_message": user_message,
        }))?;
        let msgs = r
            .get("messages")
            .cloned()
            .unwrap_or(Value::Array(vec![]));
        serde_json::from_value(msgs).map_err(|e| CoreError::Sidecar(format!("messages: {e}")))
    }

    pub fn capture_identity(&mut self, line: &str) -> Result<()> {
        self.call(json!({"op": "capture_identity", "line": line}))?;
        Ok(())
    }

    pub fn tools_allowed(&mut self, line: &str) -> Result<bool> {
        let r = self.call(json!({"op": "tools_allowed", "line": line}))?;
        Ok(r.get("allowed").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub fn post_public_log(&mut self, event: &Value) -> Result<()> {
        self.call(json!({"op": "post_public_log", "event": event}))?;
        Ok(())
    }

    pub fn pipeline_line(
        &mut self,
        session_id: &str,
        line: &str,
        stub: bool,
    ) -> Result<PipelineAction> {
        let r = self.call(json!({
            "op": "pipeline_line",
            "session_id": session_id,
            "line": line,
            "stub": stub,
        }))?;
        let action = r
            .get("action")
            .and_then(|v| v.as_str())
            .unwrap_or("none");
        Ok(match action {
            "help" => PipelineAction::Help(
                r.get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            ),
            "error" => PipelineAction::Error(
                r.get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            ),
            "run" => PipelineAction::Run {
                code: r.get("code").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
                text: r
                    .get("text")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            },
            _ => PipelineAction::None,
        })
    }
}

pub enum PipelineAction {
    None,
    Help(String),
    Error(String),
    Run { code: i32, text: String },
}

impl SidecarDaemon {
    fn spawn(paths: &Paths) -> Result<Self> {
        let script = paths.repo_root.join("kernel/eidos_sidecar.py");
        if !script.is_file() {
            return Err(CoreError::Sidecar(format!(
                "нет скрипта {}",
                script.display()
            )));
        }
        let mut child = Command::new("python3")
            .current_dir(&paths.repo_root)
            .env("PYTHONPATH", &paths.repo_root)
            .arg(&script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| CoreError::Sidecar(format!("python3: {e}")))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| CoreError::Sidecar("sidecar stdin".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| CoreError::Sidecar("sidecar stdout".into()))?;

        let mut daemon = Self {
            child,
            stdin,
            reader: BufReader::new(stdout),
        };
        daemon.call(&json!({"op": "ping"}))?;
        Ok(daemon)
    }

    fn call(&mut self, req: &Value) -> Result<Value> {
        let line = serde_json::to_string(req)?;
        writeln!(self.stdin, "{line}")
            .map_err(|e| CoreError::Sidecar(format!("sidecar write: {e}")))?;
        self.stdin
            .flush()
            .map_err(|e| CoreError::Sidecar(format!("sidecar flush: {e}")))?;

        let mut resp = String::new();
        self.reader
            .read_line(&mut resp)
            .map_err(|e| CoreError::Sidecar(format!("sidecar read: {e}")))?;

        parse_sidecar_response(resp.trim())
    }
}

impl Drop for SidecarDaemon {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn oneshot_call(paths: &Paths, req: &Value) -> Result<Value> {
    let script = paths.repo_root.join("kernel/eidos_sidecar.py");
    let mut child = Command::new("python3")
        .current_dir(&paths.repo_root)
        .env("PYTHONPATH", &paths.repo_root)
        .arg(&script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| CoreError::Sidecar(format!("python3: {e}")))?;

    {
        let mut stdin = child
            .stdin
            .take()
            .ok_or_else(|| CoreError::Sidecar("stdin".into()))?;
        let line = serde_json::to_string(req)?;
        writeln!(stdin, "{line}")
            .map_err(|e| CoreError::Sidecar(format!("write: {e}")))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|e| CoreError::Sidecar(format!("wait: {e}")))?;

    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr);
        return Err(CoreError::Sidecar(format!(
            "python {}: {}",
            output.status, detail.trim()
        )));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let first = stdout.lines().next().unwrap_or("").trim();
    parse_sidecar_response(first)
}

fn parse_sidecar_response(line: &str) -> Result<Value> {
    if line.is_empty() {
        return Err(CoreError::Sidecar("пустой ответ sidecar".into()));
    }
    let v: Value = serde_json::from_str(line)
        .map_err(|e| CoreError::Sidecar(format!("JSON ответа: {e}; raw={line:.200}")))?;
    if v.get("ok").and_then(|x| x.as_bool()) != Some(true) {
        let msg = v
            .get("error")
            .and_then(|e| e.as_str())
            .unwrap_or("sidecar error");
        return Err(CoreError::Sidecar(msg.to_string()));
    }
    Ok(v.get("result").cloned().unwrap_or(Value::Null))
}

// --- Legacy one-shot helpers (boot subcommand без Sidecar) ---

pub fn seed_user_display_name(paths: &Paths) -> Result<()> {
    let mut s = Sidecar::open(paths.clone());
    s.seed_identity()
}

pub fn run_cli_chat_boot_python(paths: &Paths) -> Result<()> {
    let mut s = Sidecar::open(paths.clone());
    s.run_cli_chat_boot()
}

pub fn chat_startup_reports(paths: &Paths) -> Result<(String, String)> {
    let mut s = Sidecar::open(paths.clone());
    s.startup_reports("full")
}

pub fn build_chat_messages_for_llm_python(
    paths: &Paths,
    cli_session_id: &str,
    user_message: &str,
) -> Result<Vec<Value>> {
    let mut s = Sidecar::open(paths.clone());
    s.build_chat_messages(cli_session_id, user_message)
}
