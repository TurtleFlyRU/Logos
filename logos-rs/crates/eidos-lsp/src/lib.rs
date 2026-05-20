//! LSP-сервер Эйдос: stdio + команды ``eidos.*`` через ``workspace/executeCommand``.

pub mod commands;
pub mod paths_resolve;
pub mod server;

pub use commands::{
    execute, print_paths_info, ALL_COMMANDS, CMD_CONTEXT_PREVIEW, CMD_MEMORY_SEARCH,
    CMD_SESSION_LIST,
};
