//! Tauri 2 shell для ``eidos-core`` (фаза 3 v1).

use std::env;
use std::sync::{Arc, Mutex};

use eidos_core::{
    append_session_budget_snapshot, read_session_budget_history, AgentsEditorState,
    BudgetSnapshot, ChatMessageDto, ContextMetricsDto, DesktopRuntime, LlmProfileDto, PathsDto,
    SendMessageResult, SessionRecord, SettingsDto, SleepResult,
};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

struct AppState {
    runtime: DesktopRuntime,
}

#[derive(Serialize)]
struct AppStateDto {
    session_id: String,
    paths: PathsDto,
    profile: LlmProfileDto,
    messages: Vec<ChatMessageDto>,
    stub: bool,
}

fn profile_from_env() -> Option<String> {
    env::var("EIDOS_AGENT_PROFILE")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn stub_from_env() -> bool {
    matches!(
        env::var("EIDOS_DESKTOP_STUB").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

fn state_dto(rt: &DesktopRuntime) -> Result<AppStateDto, String> {
    Ok(AppStateDto {
        session_id: rt.session_id.clone(),
        paths: rt.paths_dto(),
        profile: rt.llm_profile_dto().map_err(|e| e.to_string())?,
        messages: rt.messages(),
        stub: rt.stub,
    })
}

#[tauri::command]
fn get_app_state(state: State<Mutex<AppState>>) -> Result<AppStateDto, String> {
    let rt = state.lock().map_err(|e| e.to_string())?;
    state_dto(&rt.runtime)
}

#[tauri::command]
fn list_sessions(state: State<Mutex<AppState>>) -> Result<Vec<SessionRecord>, String> {
    let rt = state.lock().map_err(|e| e.to_string())?;
    rt.runtime.list_sessions().map_err(|e| e.to_string())
}

#[derive(Clone, Serialize)]
struct ChatStreamPayload {
    session_id: String,
    delta: String,
}

#[derive(Clone, Serialize)]
struct ChatStreamEndPayload {
    session_id: String,
    result: SendMessageResult,
}

struct StreamEmitter {
    app: AppHandle,
    session_id: String,
}

impl StreamEmitter {
    fn emit_start(&self) {
        let _ = self.app.emit(
            "chat-stream-start",
            serde_json::json!({ "session_id": self.session_id }),
        );
    }

    fn emit_delta(&self, delta: &str) {
        let _ = self.app.emit(
            "chat-stream-delta",
            ChatStreamPayload {
                session_id: self.session_id.clone(),
                delta: delta.to_string(),
            },
        );
    }

    fn emit_end(&self, result: SendMessageResult) {
        let _ = self.app.emit(
            "chat-stream-end",
            ChatStreamEndPayload {
                session_id: self.session_id.clone(),
                result,
            },
        );
    }

    fn emit_error(&self, message: String) {
        let _ = self.app.emit(
            "chat-stream-error",
            serde_json::json!({
                "session_id": self.session_id,
                "message": message,
            }),
        );
    }
}

#[tauri::command]
fn send_message(
    app: AppHandle,
    state: State<Mutex<AppState>>,
    text: String,
) -> Result<(), String> {
    let session_id = {
        let guard = state.lock().map_err(|e| e.to_string())?;
        guard.runtime.session_id.clone()
    };
    let emitter = Arc::new(StreamEmitter {
        app: app.clone(),
        session_id,
    });
    emitter.emit_start();

    let app_bg = app.clone();
    std::thread::spawn(move || {
        let outcome = (|| -> Result<SendMessageResult, String> {
            let state = app_bg.state::<Mutex<AppState>>();
            let mut guard = state.lock().map_err(|e| e.to_string())?;
            let em = Arc::clone(&emitter);
            let on_delta: Box<dyn FnMut(&str) + Send> =
                Box::new(move |delta: &str| em.emit_delta(delta));
            guard
                .runtime
                .send_message(text, Some(on_delta))
                .map_err(|e| e.to_string())
        })();
        match outcome {
            Ok(res) => emitter.emit_end(res),
            Err(e) => emitter.emit_error(e),
        }
    });

    Ok(())
}

#[tauri::command]
fn run_boot(state: State<Mutex<AppState>>) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard.runtime.run_boot().map_err(|e| e.to_string())
}

#[tauri::command]
fn new_session(
    state: State<Mutex<AppState>>,
    clear_wm: bool,
    run_boot: bool,
) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .new_session(clear_wm, run_boot)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn switch_session(state: State<Mutex<AppState>>, session_id: String) -> Result<(), String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .switch_session(session_id)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_env_report(state: State<Mutex<AppState>>, active_only: bool) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .env_report(active_only)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_budget_report(state: State<Mutex<AppState>>) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .budget_report()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_context_metrics(
    state: State<Mutex<AppState>>,
    user_message: Option<String>,
) -> Result<ContextMetricsDto, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .context_metrics(user_message.as_deref())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_pipeline_help(state: State<Mutex<AppState>>) -> Result<String, String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .pipeline_help()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn run_sleep(state: State<Mutex<AppState>>, force: bool) -> Result<SleepResult, String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    guard.runtime.run_sleep(force).map_err(|e| e.to_string())
}

#[tauri::command]
fn get_settings(state: State<Mutex<AppState>>) -> Result<SettingsDto, String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    guard.runtime.settings().map_err(|e| e.to_string())
}

#[tauri::command]
fn get_agents_editor_state(state: State<Mutex<AppState>>) -> Result<AgentsEditorState, String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .read_agents_editor_state()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn record_budget_snapshot(state: State<Mutex<AppState>>) -> Result<(), String> {
    let mut guard = state.lock().map_err(|e| e.to_string())?;
    let m = guard
        .runtime
        .context_metrics(None)
        .map_err(|e| e.to_string())?;
    let snap = BudgetSnapshot::from_usage(m.total_chars, m.total_budget, m.approx_prompt_tokens);
    append_session_budget_snapshot(&guard.runtime.paths, &guard.runtime.session_id, snap)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_session_budget_history(
    state: State<Mutex<AppState>>,
    session_id: Option<String>,
) -> Result<Vec<BudgetSnapshot>, String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    let sid = session_id
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| guard.runtime.session_id.clone());
    read_session_budget_history(&guard.runtime.paths, &sid).map_err(|e| e.to_string())
}

#[tauri::command]
fn save_agents_config(state: State<Mutex<AppState>>, content: String) -> Result<(), String> {
    let guard = state.lock().map_err(|e| e.to_string())?;
    guard
        .runtime
        .write_agents_config_file(&content)
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // После tool round ответ показывается через replay-chunkи; без паузы WebKit
    // часто отрисовывает всё сразу. CLI не трогаем: переменная задаётся только здесь по умолчанию.
    if env::var("EIDOS_STREAM_REPLAY_MS").is_err() {
        env::set_var("EIDOS_STREAM_REPLAY_MS", "6");
    }

    let runtime = DesktopRuntime::open(profile_from_env(), stub_from_env(), false, true)
        .expect("desktop runtime");

    tauri::Builder::default()
        .manage(Mutex::new(AppState { runtime }))
        .invoke_handler(tauri::generate_handler![
            get_app_state,
            list_sessions,
            send_message,
            run_boot,
            new_session,
            switch_session,
            get_env_report,
            get_budget_report,
            get_context_metrics,
            get_pipeline_help,
            run_sleep,
            get_settings,
            get_agents_editor_state,
            save_agents_config,
            record_budget_snapshot,
            get_session_budget_history,
        ])
        .run(tauri::generate_context!())
        .expect("tauri run");
}
