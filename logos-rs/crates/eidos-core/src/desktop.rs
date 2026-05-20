//! API для Tauri desktop (фаза 3).

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use eidos_protocol::agents::AgentsConfig;
use eidos_protocol::working::WmEvent;
use serde::{Deserialize, Serialize};

use crate::agents::get_llm_runtime_params;
use crate::boot::run_cli_chat_boot;
use crate::chat_turn::{prepare_session_boot, process_chat_turn, ChatTurnInput};
use crate::error::{CoreError, Result};
use crate::paths::{resolve_paths, Paths};
use crate::py_sidecar::Sidecar;
use crate::session::{
    list_sessions, new_session_id, read_latest, touch_session, write_latest, SessionRecord,
};
use crate::working_memory::{clear_working_memory, WorkingMemory};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathsDto {
    pub repo_root: String,
    pub data_root: String,
    pub working_wm: String,
    pub agents_cfg: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmProfileDto {
    pub profile_name: String,
    pub model: String,
    pub base_url: String,
    pub read_timeout_sec: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessageDto {
    pub role: String,
    pub content: String,
    pub timestamp: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SendMessageResult {
    pub reply: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pipeline_text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub status_warning: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SleepResult {
    pub output: String,
    pub exit_code: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextMetricsDto {
    pub total_budget: u64,
    pub total_chars: u64,
    pub approx_prompt_tokens: u64,
    pub system_messages: u64,
    pub history_messages: u64,
    pub tool_messages: u64,
    pub layers: std::collections::HashMap<String, bool>,
    pub layer_chars: std::collections::HashMap<String, u64>,
    pub layer_tokens: std::collections::HashMap<String, u64>,
    pub budget_report: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentsEditorState {
    /// Текущее содержимое для редактирования (фактический файл, из которого читает рантайм).
    pub content: String,
    /// Путь прочитанного файла (для подписи в UI).
    pub active_file: String,
    /// Куда сохранится при «Сохранить» (`data/config/agents.yaml` или `EIDOS_AGENTS_CONFIG`).
    pub save_target: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SettingsDto {
    pub paths: PathsDto,
    pub profile: LlmProfileDto,
    pub session_id: String,
    pub stub: bool,
    pub agent_profile_env: Option<String>,
    pub desktop_stub_env: bool,
    pub rust_boot: bool,
    pub rust_context: bool,
    pub sidecar_disabled: bool,
}

pub struct DesktopRuntime {
    pub paths: Paths,
    pub session_id: String,
    pub sidecar: Sidecar,
    pub wm: WorkingMemory,
    pub profile_name: Option<String>,
    pub stub: bool,
}

impl DesktopRuntime {
    pub fn open(
        profile_name: Option<String>,
        stub: bool,
        new_session: bool,
        run_boot: bool,
    ) -> Result<Self> {
        let paths = resolve_paths()?;
        let session_id = if new_session {
            let sid = new_session_id();
            clear_working_memory(&paths)?;
            sid
        } else {
            read_latest(&paths).unwrap_or_else(new_session_id)
        };

        touch_session(&paths, &session_id)?;
        write_latest(&paths, &session_id)?;

        let mut wm = WorkingMemory::open(&paths);
        wm.set_context(
            "cli_session_id",
            serde_json::Value::String(session_id.clone()),
        );
        wm.set_context(
            "cli_transport",
            serde_json::Value::String("eidos".into()),
        );
        wm.save()?;

        let mut sidecar = Sidecar::open(paths.clone());
        if run_boot {
            prepare_session_boot(&paths, &mut wm, &mut sidecar, false)?;
        } else {
            let _ = sidecar.seed_identity();
            wm.reload();
        }

        Ok(Self {
            paths,
            session_id,
            sidecar,
            wm,
            profile_name,
            stub,
        })
    }

    pub fn paths_dto(&self) -> PathsDto {
        PathsDto {
            repo_root: self.paths.repo_root.display().to_string(),
            data_root: self.paths.data_root.display().to_string(),
            working_wm: self.paths.working_memory_path().display().to_string(),
            agents_cfg: self
                .paths
                .find_agents_config()
                .map(|p| p.display().to_string()),
        }
    }

    pub fn llm_profile_dto(&self) -> Result<LlmProfileDto> {
        let p = get_llm_runtime_params(&self.paths, self.profile_name.as_deref())?;
        Ok(LlmProfileDto {
            profile_name: p.profile_name,
            model: p.model,
            base_url: p.base_url,
            read_timeout_sec: p.read_timeout_sec,
        })
    }

    pub fn list_sessions(&self) -> Result<Vec<SessionRecord>> {
        list_sessions(&self.paths)
    }

    pub fn messages(&self) -> Vec<ChatMessageDto> {
        session_messages(&self.wm, &self.session_id)
    }

    pub fn send_message(
        &mut self,
        text: String,
        on_stream_delta: Option<Box<dyn FnMut(&str) + Send>>,
    ) -> Result<SendMessageResult> {
        let line = text.trim();
        if line.is_empty() {
            return Err(crate::error::CoreError::WorkingMemory(
                "пустое сообщение".into(),
            ));
        }
        let turn = process_chat_turn(ChatTurnInput {
            paths: &self.paths,
            wm: &mut self.wm,
            sidecar: &mut self.sidecar,
            session_id: &self.session_id,
            line,
            stub: self.stub,
            profile_name: self.profile_name.as_deref(),
            on_stream_delta,
        })?;
        self.wm.reload();
        let reply = turn.reply.clone().or(turn.pipeline_text.clone()).unwrap_or_default();
        Ok(SendMessageResult {
            reply,
            llm_status: turn.llm_status,
            pipeline_text: turn.pipeline_text,
            status_warning: turn.status_warning,
        })
    }

    pub fn run_boot(&mut self) -> Result<String> {
        run_cli_chat_boot(&self.paths, &mut self.wm, &mut self.sidecar)?;
        self.wm.reload();
        Ok(self
            .wm
            .document()
            .context
            .extra
            .get("boot_context")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string())
    }

    pub fn new_session(&mut self, clear_wm: bool, run_boot: bool) -> Result<String> {
        let sid = new_session_id();
        if clear_wm {
            clear_working_memory(&self.paths)?;
        }
        self.session_id = sid.clone();
        self.wm = WorkingMemory::open(&self.paths);
        self.wm.set_context(
            "cli_session_id",
            serde_json::Value::String(sid.clone()),
        );
        self.wm.set_context(
            "cli_transport",
            serde_json::Value::String("eidos".into()),
        );
        self.wm.save()?;
        touch_session(&self.paths, &sid)?;
        write_latest(&self.paths, &sid)?;
        if run_boot {
            prepare_session_boot(&self.paths, &mut self.wm, &mut self.sidecar, false)?;
        }
        Ok(sid)
    }

    pub fn switch_session(&mut self, session_id: String) -> Result<()> {
        self.session_id = session_id;
        write_latest(&self.paths, &self.session_id)?;
        touch_session(&self.paths, &self.session_id)?;
        self.wm.reload();
        Ok(())
    }

    /// Отчёт ``/env`` (как в CLI).
    pub fn env_report(&mut self, active_only: bool) -> Result<String> {
        self.wm.reload();
        let mode = if active_only { "env_active" } else { "env_all" };
        let (env, _) = self.sidecar.startup_reports(mode)?;
        Ok(env)
    }

    /// Отчёт ``/budget``.
    pub fn budget_report(&mut self) -> Result<String> {
        self.wm.reload();
        let (_, budget) = self.sidecar.startup_reports("budget")?;
        Ok(budget)
    }

    /// Структурированные метрики контекста (слои, токены) + текст ``/budget``.
    pub fn context_metrics(&mut self, user_message: Option<&str>) -> Result<ContextMetricsDto> {
        self.wm.reload();
        let r = self
            .sidecar
            .context_metrics(&self.session_id, user_message)?;
        parse_context_metrics(r)
    }

    /// Справка по пайплайнам (``/pipeline help``).
    pub fn pipeline_help(&mut self) -> Result<String> {
        let r = self.sidecar.pipeline_line(&self.session_id, "/pipeline help", self.stub)?;
        match r {
            crate::py_sidecar::PipelineAction::Help(text) => Ok(text),
            crate::py_sidecar::PipelineAction::Error(text) => Ok(text),
            _ => Ok("См. /pipeline research|experiment|code_review в поле ввода.".into()),
        }
    }

    /// Запуск ``python3 eidos.py sleep`` (пайплайн памяти, как в CLI).
    pub fn run_sleep(&self, force: bool) -> Result<SleepResult> {
        let eidos = self.paths.repo_root.join("eidos.py");
        if !eidos.is_file() {
            return Err(crate::error::CoreError::WorkingMemory(format!(
                "не найден {}",
                eidos.display()
            )));
        }
        let mut cmd = Command::new("python3");
        cmd.arg(&eidos).arg("sleep");
        if force {
            cmd.arg("--force");
        }
        cmd.current_dir(&self.paths.repo_root);
        let out = cmd.output().map_err(|e| {
            crate::error::CoreError::WorkingMemory(format!("sleep subprocess: {e}"))
        })?;
        let stdout = String::from_utf8_lossy(&out.stdout);
        let stderr = String::from_utf8_lossy(&out.stderr);
        let mut text = stdout.into_owned();
        if !stderr.is_empty() {
            if !text.is_empty() {
                text.push('\n');
            }
            text.push_str(stderr.trim_end());
        }
        Ok(SleepResult {
            output: text.trim().to_string(),
            exit_code: out.status.code().unwrap_or(-1),
        })
    }

    /// Настройки сессии (без секретов; профиль LLM — только публичные поля).
    pub fn settings(&self) -> Result<SettingsDto> {
        Ok(SettingsDto {
            paths: self.paths_dto(),
            profile: self.llm_profile_dto()?,
            session_id: self.session_id.clone(),
            stub: self.stub,
            agent_profile_env: std::env::var("EIDOS_AGENT_PROFILE")
                .ok()
                .filter(|s| !s.trim().is_empty()),
            desktop_stub_env: env_flag("EIDOS_DESKTOP_STUB"),
            rust_boot: env_flag("EIDOS_RUST_BOOT"),
            rust_context: env_flag("EIDOS_RUST_CONTEXT"),
            sidecar_disabled: env_flag("EIDOS_RUST_NO_SIDECAR"),
        })
    }

    /// Текст конфигурации агентов для редактора (читается тот же файл, что и рантайм).
    pub fn read_agents_editor_state(&self) -> Result<AgentsEditorState> {
        let active = self.paths.find_agents_config().ok_or_else(|| {
            CoreError::WorkingMemory(
                "Не найден agents.yaml (EIDOS_AGENTS_CONFIG, data/config, config/, defaults)."
                    .into(),
            )
        })?;
        let content = fs::read_to_string(&active).map_err(|e| {
            CoreError::WorkingMemory(format!("чтение {}: {e}", active.display()))
        })?;
        let save_target = agents_yaml_save_path(&self.paths)?;
        assert_save_parent_allowed(&self.paths, &save_target)?;
        Ok(AgentsEditorState {
            content,
            active_file: active.display().to_string(),
            save_target: save_target.display().to_string(),
        })
    }

    /// Атомарно записать конфигурацию (цель — `data/config/agents.yaml` или `EIDOS_AGENTS_CONFIG`).
    ///
    /// Перед записью YAML проверяется как `AgentsConfig`. Параметры LLM для чата читаются с диска на каждый ход (кэша нет).
    pub fn write_agents_config_file(&self, content: &str) -> Result<()> {
        let _: AgentsConfig = serde_yaml::from_str(content).map_err(|e| {
            CoreError::WorkingMemory(format!("agents.yaml: невалидная структура: {e}"))
        })?;
        let save_target = agents_yaml_save_path(&self.paths)?;
        assert_save_parent_allowed(&self.paths, &save_target)?;
        if let Some(parent) = save_target.parent() {
            fs::create_dir_all(parent).map_err(|e| {
                CoreError::WorkingMemory(format!("mkdir {}: {e}", parent.display()))
            })?;
        }
        let name = save_target
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("agents.yaml");
        let tmp = save_target.with_file_name(format!("{name}.tmp"));
        fs::write(&tmp, content.as_bytes()).map_err(|e| {
            CoreError::WorkingMemory(format!("запись {}: {e}", tmp.display()))
        })?;
        fs::rename(&tmp, &save_target).map_err(|e| {
            let _ = fs::remove_file(&tmp);
            CoreError::WorkingMemory(format!("commit {}: {e}", save_target.display()))
        })?;
        Ok(())
    }
}

fn parse_context_metrics(r: serde_json::Value) -> Result<ContextMetricsDto> {
    let m = r.get("metrics").cloned().unwrap_or(serde_json::Value::Null);
    let num_u64 = |key: &str| -> u64 {
        m.get(key)
            .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|n| n.max(0) as u64)))
            .unwrap_or(0)
    };
    let map_u64 = |key: &str| -> std::collections::HashMap<String, u64> {
        m.get(key)
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| {
                        v.as_u64()
                            .or_else(|| v.as_i64().map(|n| n.max(0) as u64))
                            .map(|n| (k.clone(), n))
                    })
                    .collect()
            })
            .unwrap_or_default()
    };
    let layers = m
        .get("layers")
        .and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b)))
                .collect()
        })
        .unwrap_or_default();
    let budget_report = r
        .get("budget_report")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Ok(ContextMetricsDto {
        total_budget: num_u64("budget_total_chars"),
        total_chars: num_u64("total_chars"),
        approx_prompt_tokens: num_u64("approx_prompt_tokens"),
        system_messages: num_u64("system_messages"),
        history_messages: num_u64("history_messages"),
        tool_messages: num_u64("tool_messages"),
        layers,
        layer_chars: map_u64("layer_chars"),
        layer_tokens: map_u64("approx_layer_tokens"),
        budget_report,
    })
}

fn env_flag(name: &str) -> bool {
    matches!(
        std::env::var(name).as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

fn agents_yaml_save_path(paths: &Paths) -> Result<PathBuf> {
    if let Ok(raw) = std::env::var("EIDOS_AGENTS_CONFIG") {
        let t = raw.trim();
        if !t.is_empty() {
            return Ok(PathBuf::from(t));
        }
    }
    Ok(paths.data_root.join("config").join("agents.yaml"))
}

/// Разрешить запись только под корнем репозитория или `data_root`.
fn assert_save_parent_allowed(paths: &Paths, target: &Path) -> Result<()> {
    let repo = paths
        .repo_root
        .canonicalize()
        .unwrap_or_else(|_| paths.repo_root.clone());
    let data = paths
        .data_root
        .canonicalize()
        .unwrap_or_else(|_| paths.data_root.clone());
    let Some(parent) = target.parent() else {
        return Err(CoreError::WorkingMemory(
            "agents: у целевого пути нет родительского каталога".into(),
        ));
    };
    if parent.as_os_str().is_empty() {
        return Err(CoreError::WorkingMemory(
            "agents: некорректный путь сохранения".into(),
        ));
    }
    let mut p = parent.to_path_buf();
    while !p.as_os_str().is_empty() && !p.is_dir() {
        if let Some(pp) = p.parent() {
            p = pp.to_path_buf();
        } else {
            break;
        }
    }
    let p = p
        .canonicalize()
        .unwrap_or_else(|_| p.clone());
    if !(p.starts_with(&repo) || p.starts_with(&data)) {
        return Err(CoreError::WorkingMemory(format!(
            "сохранение agents.yaml только под {} или {}",
            repo.display(),
            data.display()
        )));
    }
    Ok(())
}

fn session_messages(wm: &WorkingMemory, session_id: &str) -> Vec<ChatMessageDto> {
    let mut out = Vec::new();
    for ev in &wm.document().events {
        if ev.cli_session_id.as_deref() != Some(session_id) {
            continue;
        }
        push_event(&mut out, ev);
    }
    out
}

fn push_event(out: &mut Vec<ChatMessageDto>, ev: &WmEvent) {
    let role = ev.role.as_deref().unwrap_or("");
    if role == "tool" {
        let content = ev.text_content().unwrap_or("").to_string();
        if content.is_empty() {
            return;
        }
        out.push(ChatMessageDto {
            role: "tool".into(),
            content,
            timestamp: ev.timestamp,
            tool_call_id: ev.tool_call_id.clone(),
        });
        return;
    }
    if role != "user" && role != "assistant" {
        return;
    }
    let content = ev.text_content().unwrap_or("").trim();
    if content.is_empty() && ev.tool_calls.is_none() {
        return;
    }
    let mut text = content.to_string();
    if let Some(tc) = &ev.tool_calls {
        let names: Vec<_> = tc
            .iter()
            .map(|t| t.function.name.as_str())
            .collect();
        if !text.is_empty() {
            text.push_str("\n");
        }
        text.push_str(&format!("[tools: {}]", names.join(", ")));
    }
    out.push(ChatMessageDto {
        role: role.to_string(),
        content: text,
        timestamp: ev.timestamp,
        tool_call_id: None,
    });
}
