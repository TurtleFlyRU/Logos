//! Один ход диалога (общий для CLI и desktop).

use crate::agents::get_llm_runtime_params;
use crate::chat::{cli_chat_llm_reply, handle_pipeline_action, post_public_log, CliChatReply};
use crate::context::build_chat_messages_for_llm;
use crate::error::Result;
use crate::paths::Paths;
use crate::py_sidecar::Sidecar;
use crate::session::touch_session;
use crate::working_memory::{make_cli_chat_event_full, WorkingMemory};

pub struct ChatTurnInput<'a> {
    pub paths: &'a Paths,
    pub wm: &'a mut WorkingMemory,
    pub sidecar: &'a mut Sidecar,
    pub session_id: &'a str,
    pub line: &'a str,
    pub stub: bool,
    pub profile_name: Option<&'a str>,
    /// Дельты финального ответа LLM (desktop / ``EIDOS_STREAM=1``).
    pub on_stream_delta: Option<Box<dyn FnMut(&str) + Send>>,
}

pub struct ChatTurnOutput {
    pub reply: Option<String>,
    pub pipeline_text: Option<String>,
    pub llm_status: Option<String>,
    /// Предупреждение в UI/терминал (не пишется в WM как assistant).
    pub status_warning: Option<String>,
    /// Текст ответа уже выведен по дельтам (CLI stream / desktop).
    pub streamed: bool,
}

const EMPTY_AFTER_TOOLS_MSG: &str = "[eidos] Модель не вернула текст после инструментов (ответ уже в истории WM).";
const EMPTY_REPLY_MSG: &str =
    "[eidos] Модель вернула пустой ответ. Проверьте LLM_MODEL и ответ API.";

/// Обработать одну строку пользователя (не slash exit/env/boot).
pub fn process_chat_turn<'a>(input: ChatTurnInput<'a>) -> Result<ChatTurnOutput> {
    let ChatTurnInput {
        paths,
        wm,
        sidecar,
        session_id,
        line,
        stub,
        profile_name,
        on_stream_delta,
    } = input;

    // Slash `/budget`, `/env`, `/options` не являются пайплайном: Python `pipeline_line` даёт `none`,
    // после чего строка уходит в LLM и попадает в WM. Тогда в чате иногда полный «html» от модели
    // (паритет с ранним `continue` в `chat.rs` до `process_chat_turn`).
    let low = line.to_ascii_lowercase();
    if low == "/env" || low == "/env all" {
        wm.reload();
        let (env, _) = sidecar.startup_reports("env_all")?;
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(env),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }
    if low == "/env active" {
        wm.reload();
        let (env, _) = sidecar.startup_reports("env_active")?;
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(env),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }
    if low.starts_with("/budget") {
        wm.reload();
        let (_, budget) = sidecar.startup_reports("budget")?;
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(budget),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }
    if low == "/options" {
        wm.reload();
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(
                "[eidos] Команда /options открывает панель настроек в Eidos Desktop — обновите клиент."
                    .to_string(),
            ),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }
    if low == "/memory" || low.starts_with("/memory ") {
        wm.reload();
        let text = sidecar
            .memory_help()
            .unwrap_or_else(|_| crate::memory_tools::format_memory_help_rust());
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(text),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }
    if low == "/tools" || low.starts_with("/tools ") {
        wm.reload();
        let text = sidecar
            .tools_help()
            .unwrap_or_else(|_| crate::tools::format_tools_help_rust());
        return Ok(ChatTurnOutput {
            reply: None,
            pipeline_text: Some(text),
            llm_status: None,
            status_warning: None,
            streamed: false,
        });
    }

    let stream_sink_active = on_stream_delta.is_some();
    let mut on_stream_delta = on_stream_delta;

    if let Ok(pipe) = sidecar.pipeline_line(session_id, line, stub) {
        if let Some(text) = handle_pipeline_action(pipe, paths, session_id)? {
            wm.reload();
            return Ok(ChatTurnOutput {
                reply: None,
                pipeline_text: Some(text),
                llm_status: None,
                status_warning: None,
                streamed: false,
            });
        }
    }

    let _ = sidecar.capture_identity(line);
    wm.reload();

    let user_ev = make_cli_chat_event_full(
        "user",
        Some(line.to_string()),
        None,
        None,
        Some(session_id),
    );
    wm.add_event(user_ev.clone())?;
    post_public_log(sidecar, &user_ev);

    let allow_tools = sidecar.tools_allowed(line).unwrap_or(true);
    let llm_params = get_llm_runtime_params(paths, profile_name)?;

    let (reply, llm_status, status_warning) = if stub {
        let text = format!("[stub] {}", line.chars().take(2000).collect::<String>());
        if let Some(ref mut on_delta) = on_stream_delta.as_mut() {
            crate::chat::emit_stream_replay(&text, on_delta);
        }
        (Some(text), None, None)
    } else {
        let status = Some(crate::agents::format_llm_pending_banner(&llm_params));
        let messages = build_chat_messages_for_llm(paths, wm, session_id, line, sidecar);
        match cli_chat_llm_reply(
            paths,
            wm,
            session_id,
            &messages,
            &llm_params,
            allow_tools,
            on_stream_delta
                .as_mut()
                .map(|b| &mut **b as &mut (dyn FnMut(&str) + Send)),
            sidecar,
        )? {
            CliChatReply::Text(t) => (Some(t), status, None),
            CliChatReply::AfterToolsNoText => (None, status, Some(EMPTY_AFTER_TOOLS_MSG.into())),
            CliChatReply::Empty => (None, status, Some(EMPTY_REPLY_MSG.into())),
        }
    };

    if let Some(ref text) = reply {
        if !text.is_empty() {
            let asst_ev = make_cli_chat_event_full(
                "assistant",
                Some(text.clone()),
                None,
                None,
                Some(session_id),
            );
            wm.add_event(asst_ev.clone())?;
            post_public_log(sidecar, &asst_ev);
        }
    }
    touch_session(paths, session_id)?;

    let streamed = stream_sink_active && reply.is_some() && !stub;

    Ok(ChatTurnOutput {
        reply,
        pipeline_text: None,
        llm_status,
        status_warning,
        streamed,
    })
}

/// Boot + seed identity.
pub fn prepare_session_boot(
    paths: &Paths,
    wm: &mut WorkingMemory,
    sidecar: &mut Sidecar,
    no_boot: bool,
) -> Result<()> {
    let _ = sidecar.seed_identity();
    wm.reload();
    if !no_boot {
        let _ = crate::boot::run_cli_chat_boot(paths, wm, sidecar);
        wm.reload();
    }
    Ok(())
}
