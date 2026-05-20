//! Интерактивный chat и цикл tool_calls.

use std::io::{self, BufRead, Write};

use eidos_protocol::working::{ToolCall, WmEvent};
use serde_json::{json, Value};

use crate::agents::{get_llm_runtime_params, LlmRuntimeParams};
use crate::boot::run_cli_chat_boot;
use crate::chat_turn::{process_chat_turn, ChatTurnInput};
use crate::context::assistant_message_for_api;
use crate::error::{CoreError, Result};
use crate::llm::chat_completion_assistant_message;
use crate::paths::{resolve_paths, Paths};
use crate::memory_tools::{
    execute_memory_tool, is_memory_tool_name, memory_tool_specs, memory_tools_enabled,
};
use crate::py_sidecar::{self, PipelineAction, Sidecar};
use crate::session::{
    is_uuid, new_session_id, normalize_session_id, read_latest, touch_session, write_latest,
};
use crate::tools::{
    builtin_tool_specs, execute_tool, is_playwright_tool_name, max_tool_rounds,
    playwright_tools_enabled, progress_echo_enabled, tools_enabled,
};
use crate::working_memory::{
    clear_working_memory, make_cli_chat_event_full, WorkingMemory,
};

pub struct ChatOptions {
    pub new_session: bool,
    pub session_id: Option<String>,
    pub stub: bool,
    pub no_boot: bool,
    pub profile_name: Option<String>,
}

pub fn run_chat_interactive(opts: ChatOptions) -> Result<()> {
    let paths = resolve_paths()?;
    let llm_params = get_llm_runtime_params(&paths, opts.profile_name.as_deref())?;
    let mut sidecar = Sidecar::open(paths.clone());

    let session_id = resolve_session_id(&paths, &opts)?;
    touch_session(&paths, &session_id)?;
    write_latest(&paths, &session_id)?;

    let mut wm = WorkingMemory::open(&paths);
    if opts.new_session {
        clear_working_memory(&paths)?;
        wm = WorkingMemory::open(&paths);
    }
    wm.set_context("cli_session_id", Value::String(session_id.clone()));
    wm.set_context("cli_transport", Value::String("eidos".into()));
    wm.save()?;

    if let Err(e) = sidecar.seed_identity() {
        eprintln!("[eidos] Имя пользователя из AGENTS.md: {e}");
    }
    wm.reload();

    if !opts.no_boot {
        if let Err(e) = run_cli_chat_boot(&paths, &mut wm, &mut sidecar) {
            eprintln!("[eidos] Boot не выполнен: {e}");
        } else {
            wm.reload();
        }
    }

    let short = format!("{}…", &session_id[..8.min(session_id.len())]);
    println!(
        "Сессия CLI {short} ({session_id}). Команды: /exit, /quit \
         | /env | /budget | /pipeline, /run, /review (см. /pipeline help)"
    );

    match sidecar.startup_reports("full") {
        Ok((env, budget)) => {
            if !env.is_empty() {
                println!("{env}");
            }
            if !budget.is_empty() {
                println!("{budget}");
            }
        }
        Err(e) => eprintln!("[eidos] Отчёты /env и /budget: {e}"),
    }

    if opts.stub {
        println!("[stub] Режим без вызова LLM (--stub).");
    }

    let stdin = io::stdin();
    let mut interrupt_times: Vec<std::time::Instant> = Vec::new();
    let ki_window = std::time::Duration::from_secs_f64(1.6);

    loop {
        print!("> ");
        io::stdout().flush().ok();
        let mut line = String::new();
        match stdin.lock().read_line(&mut line) {
            Ok(0) => {
                println!();
                break;
            }
            Ok(_) => {}
            Err(e) if e.kind() == io::ErrorKind::Interrupted => {
                let now = std::time::Instant::now();
                interrupt_times.retain(|t| now.duration_since(*t) < ki_window);
                interrupt_times.push(now);
                if interrupt_times.len() >= 2 {
                    println!("\n[eidos] Выход по двойному Ctrl+C.");
                    break;
                }
                println!(
                    "\n[eidos] Прервано на приглашении. Выход: /exit или /quit \
                     (или второй Ctrl+C в течение {:.1} с).",
                    ki_window.as_secs_f64()
                );
                continue;
            }
            Err(e) => return Err(CoreError::Io(e)),
        }

        let line = line.trim().to_string();
        if line.is_empty() {
            continue;
        }
        let low = line.to_ascii_lowercase();
        if matches!(low.as_str(), "/exit" | "/quit") {
            break;
        }
        if low == "/boot" {
            match run_cli_chat_boot(&paths, &mut wm, &mut sidecar) {
                Ok(text) => println!("{text}"),
                Err(e) => eprintln!("[eidos] Boot: {e}"),
            }
            wm.reload();
            continue;
        }
        if low == "/env" || low == "/env all" {
            match sidecar.startup_reports("env_all") {
                Ok((env, _)) => println!("{env}"),
                Err(e) => print_env_summary(&paths, &llm_params, &e),
            }
            continue;
        }
        if low == "/env active" {
            match sidecar.startup_reports("env_active") {
                Ok((env, _)) => println!("{env}"),
                Err(e) => eprintln!("[eidos] /env active: {e}"),
            }
            continue;
        }
        if low == "/budget" || low == "/budget now" || low == "/budget all" {
            match sidecar.startup_reports("budget") {
                Ok((_, budget)) => println!("{budget}"),
                Err(e) => eprintln!("[eidos] /budget: {e}"),
            }
            continue;
        }

        let turn = process_chat_turn(ChatTurnInput {
            paths: &paths,
            wm: &mut wm,
            sidecar: &mut sidecar,
            session_id: &session_id,
            line: &line,
            stub: opts.stub,
            profile_name: opts.profile_name.as_deref(),
            on_stream_delta: cli_stream_delta_cb(),
        })?;
        if let Some(status) = turn.llm_status {
            println!("{status}");
        }
        if let Some(text) = turn.pipeline_text {
            println!("{text}");
        }
        if let Some(w) = turn.status_warning {
            println!("{w}");
        }
        if let Some(reply) = turn.reply {
            if turn.streamed {
                println!();
            } else {
                println!("{reply}");
            }
        }
    }

    Ok(())
}

/// Текст для UI/терминала после slash-пайплайна.
pub fn handle_pipeline_action(
    action: PipelineAction,
    paths: &Paths,
    session_id: &str,
) -> Result<Option<String>> {
    match action {
        PipelineAction::None => Ok(None),
        PipelineAction::Help(text) | PipelineAction::Error(text) => Ok(Some(text)),
        PipelineAction::Run { code, text } => {
            touch_session(paths, session_id)?;
            let mut out = text;
            if code != 0 {
                out.push_str(&format!(
                    "\n[eidos] пайплайн завершился с кодом {code} (см. вывод выше)."
                ));
            }
            Ok(Some(out))
        }
    }
}

pub(crate) fn post_public_log(sidecar: &mut Sidecar, event: &WmEvent) {
    let payload = wm_event_to_json(event);
    if let Err(e) = sidecar.post_public_log(&payload) {
        eprintln!("[eidos] repo public log: {e}");
    }
}

fn wm_event_to_json(event: &WmEvent) -> Value {
    json!({
        "role": event.role,
        "content": event.content,
        "message": event.message,
        "text": event.text,
        "event_type": event.event_type,
        "cli_session_id": event.cli_session_id,
        "tool_calls": event.tool_calls,
    })
}

fn resolve_session_id(paths: &Paths, opts: &ChatOptions) -> Result<String> {
    if let Some(ref sid) = opts.session_id {
        if !is_uuid(sid) {
            return Err(CoreError::WorkingMemory(
                "аргумент --session должен быть UUID".into(),
            ));
        }
        return normalize_session_id(sid);
    }
    if opts.new_session {
        return Ok(new_session_id());
    }
    Ok(read_latest(paths).unwrap_or_else(new_session_id))
}

/// Исход одного LLM-хода с опциональными инструментами (parity с Python ``_cli_chat_llm_reply``).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliChatReply {
    /// Финальный текст (событие assistant ещё не добавлено вызывающим кодом).
    Text(String),
    /// Tool round прошёл, события assistant/tool уже в WM; финальный content пуст.
    AfterToolsNoText,
    /// Ни tool_calls, ни текста.
    Empty,
}

pub(crate) fn cli_chat_llm_reply(
    paths: &Paths,
    wm: &mut WorkingMemory,
    session_id: &str,
    messages: &[Value],
    params: &LlmRuntimeParams,
    allow_tools: bool,
    mut on_stream_delta: Option<&mut (dyn FnMut(&str) + Send)>,
    sidecar: &mut Sidecar,
) -> Result<CliChatReply> {
    if !allow_tools || !tools_enabled() {
        let text = if let Some(on_delta) = on_stream_delta.as_mut() {
            match crate::llm_stream::chat_completions_stream_text(messages, params, on_delta) {
                Ok(crate::llm_stream::StreamTextOutcome::Text(t)) => t,
                Ok(crate::llm_stream::StreamTextOutcome::ToolCallsInStream)
                | Err(_) => crate::llm::chat_completions_text(messages, params)?,
            }
        } else {
            crate::llm::chat_completions_text(messages, params)?
        };
        return Ok(if text.trim().is_empty() {
            CliChatReply::Empty
        } else {
            CliChatReply::Text(text)
        });
    }

    let mut tool_specs = builtin_tool_specs();
    if memory_tools_enabled() {
        if py_sidecar::env_no_sidecar() {
            tool_specs.extend(memory_tool_specs());
        } else {
            match sidecar.memory_tool_specs() {
                Ok(mut extra) => tool_specs.append(&mut extra),
                Err(e) => eprintln!("[eidos] memory_tool_specs: {e}"),
            }
        }
    }
    if playwright_tools_enabled() {
        match sidecar.playwright_tool_specs() {
            Ok(mut extra) => tool_specs.append(&mut extra),
            Err(e) => eprintln!("[eidos] playwright_tool_specs: {e}"),
        }
    }

    let max_r = max_tool_rounds();
    let mut messages = messages.to_vec();
    let mut had_tool_rounds = false;

    for _round in 0..max_r {
        let amsg =
            chat_completion_assistant_message(messages.as_slice(), params, Some(&tool_specs))?;
        if let Some(tcalls_val) = amsg.get("tool_calls").and_then(|v| v.as_array()) {
            if !tcalls_val.is_empty() {
                had_tool_rounds = true;
                let tcalls: Vec<ToolCall> =
                    serde_json::from_value(Value::Array(tcalls_val.clone())).unwrap_or_default();
                let content = amsg
                    .get("content")
                    .and_then(|c| c.as_str())
                    .map(str::to_string);
                wm.add_event(make_cli_chat_event_full(
                    "assistant",
                    content,
                    Some(tcalls.clone()),
                    None,
                    Some(session_id),
                ))?;
                messages.push(assistant_message_for_api(&amsg));

                for tc in &tcalls {
                    let name = &tc.function.name;
                    let args = &tc.function.arguments;
                    if progress_echo_enabled() {
                        eprintln!("[eidos] tool {name}");
                    }
                    let result = if is_playwright_tool_name(name) {
                        match sidecar.playwright_execute(name, args) {
                            Ok(s) => s,
                            Err(e) => json!({ "error": format!("{e}") }).to_string(),
                        }
                    } else if is_memory_tool_name(name) {
                        if py_sidecar::env_no_sidecar() {
                            execute_memory_tool(paths, name, args)
                        } else {
                            match sidecar.memory_execute(name, args) {
                                Ok(s) => s,
                                Err(e) => json!({ "error": format!("{e}") }).to_string(),
                            }
                        }
                    } else {
                        execute_tool(paths, name, args)
                    };
                    wm.add_event(make_cli_chat_event_full(
                        "tool",
                        Some(result.clone()),
                        None,
                        Some(tc.id.clone()),
                        Some(session_id),
                    ))?;
                    messages.push(json!({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }));
                }
                continue;
            }
        }
        let text = amsg
            .get("content")
            .and_then(|c| c.as_str())
            .unwrap_or("")
            .trim()
            .to_string();
        if !text.is_empty() {
            if let Some(on_delta) = on_stream_delta.as_mut() {
                emit_stream_replay(&text, on_delta);
            }
        }
        return Ok(if text.is_empty() {
            if had_tool_rounds {
                CliChatReply::AfterToolsNoText
            } else {
                CliChatReply::Empty
            }
        } else {
            CliChatReply::Text(text)
        });
    }

    Ok(CliChatReply::Text(
        "[eidos] Лимит раундов инструментов (EIDOS_TOOL_ROUNDS).".into(),
    ))
}

/// Показать уже полученный текст чанками (после tool round без SSE).
///
/// Без паузы WebKit в Tauri часто рисует все дельты за один кадр. Используйте
/// ``EIDOS_STREAM_REPLAY_MS`` (мс между чанками); в desktop выставляется default в ``run``.
pub(crate) fn emit_stream_replay(text: &str, on_delta: &mut dyn FnMut(&str)) {
    const CHUNK: usize = 32;
    let ms = std::env::var("EIDOS_STREAM_REPLAY_MS")
        .ok()
        .and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(0);
    let chars: Vec<char> = text.chars().collect();
    for piece in chars.chunks(CHUNK) {
        let s: String = piece.iter().collect();
        on_delta(&s);
        if ms > 0 {
            std::thread::sleep(std::time::Duration::from_millis(ms));
        }
    }
}

fn cli_stream_enabled() -> bool {
    matches!(
        std::env::var("EIDOS_STREAM").as_deref(),
        Ok("1") | Ok("true") | Ok("yes") | Ok("on")
    )
}

/// Callback для печати дельт в stdout (CLI + ``EIDOS_STREAM=1``).
fn cli_stream_delta_cb() -> Option<Box<dyn FnMut(&str) + Send>> {
    if !cli_stream_enabled() {
        return None;
    }
    Some(Box::new(|delta: &str| {
        print!("{delta}");
        let _ = io::stdout().flush();
    }))
}

fn print_env_summary(paths: &Paths, params: &LlmRuntimeParams, err: &CoreError) {
    eprintln!("[eidos] {err}");
    println!("EIDOS_AGENT_PROFILE={}", params.profile_name);
    println!("LLM model={} base={}", params.model, params.base_url);
    if let Some(cfg) = paths.find_agents_config() {
        println!("agents_cfg={}", cfg.display());
    }
    println!("EIDOS_TOOLS={}", tools_enabled());
}
