//! Ядро Эйдоса на Rust (фаза 1+: memory, llm, context, tools).

pub mod agents;
pub mod ask;
pub mod boot;
pub mod chat;
pub mod chat_turn;
pub mod context;
pub mod context_budget;
pub mod context_system_extra;
pub mod context_wm_summary;
pub mod desktop;
pub mod episodic_store;
pub mod error;
pub mod journal_list;
pub mod llm;
pub mod llm_stream;
pub mod llm_sanitize;
pub mod ml_client;
pub mod paths;
pub mod py_sidecar;
pub mod session;
pub mod semantic_store;
pub mod tools;
pub mod working_memory;

pub use agents::{
    format_llm_banner, format_llm_pending_banner, get_llm_runtime_params, http_use_proxy,
    LlmRuntimeParams,
};
pub use py_sidecar::Sidecar;
pub use ask::run_ask;
pub use boot::run_cli_chat_boot;
pub use chat::{run_chat_interactive, ChatOptions, CliChatReply};
pub use chat_turn::{prepare_session_boot, process_chat_turn, ChatTurnInput, ChatTurnOutput};
pub use desktop::{
    AgentsEditorState, ChatMessageDto, ContextMetricsDto, DesktopRuntime, LlmProfileDto, PathsDto,
    SendMessageResult, SettingsDto, SleepResult,
};
pub use journal_list::{list_journal_markdown, JournalEntryPath};
pub use semantic_store::SemanticStore;
pub use session::{list_sessions, SessionRecord};
pub use episodic_store::EpisodicStore;
pub use error::{CoreError, Result};
pub use ml_client::{ml_sidecar_base_url, ml_sidecar_configured, ml_sidecar_health_check};
pub use paths::{data_root, repo_root, resolve_paths, Paths};
pub use working_memory::WorkingMemory;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
