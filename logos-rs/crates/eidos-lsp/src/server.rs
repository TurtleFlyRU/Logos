//! ``tower-lsp`` backend (stdio).

use std::sync::Arc;

use eidos_core::{Paths, VERSION};
use serde_json::Value;
use tokio::sync::RwLock;
use tower_lsp::jsonrpc::Result;
use tower_lsp::lsp_types::*;
use tower_lsp::{Client, LanguageServer, LspService, Server};

use crate::commands::{execute, ALL_COMMANDS};
use crate::paths_resolve::resolve_lsp_paths;

pub struct Backend {
    client: Client,
    paths: Arc<RwLock<Option<Paths>>>,
}

impl Backend {
    fn new(client: Client) -> Self {
        Self {
            client,
            paths: Arc::new(RwLock::new(None)),
        }
    }

    async fn paths_or_err(&self) -> std::result::Result<Paths, String> {
        self.paths
            .read()
            .await
            .clone()
            .ok_or_else(|| "eidos-lsp: пути ещё не инициализированы (нет initialize)".into())
    }
}

#[tower_lsp::async_trait]
impl LanguageServer for Backend {
    async fn initialize(&self, params: InitializeParams) -> Result<InitializeResult> {
        let paths = resolve_lsp_paths(&params).map_err(|e| {
            tower_lsp::jsonrpc::Error {
                code: tower_lsp::jsonrpc::ErrorCode::InvalidParams,
                message: e.into(),
                data: None,
            }
        })?;
        *self.paths.write().await = Some(paths);
        Ok(InitializeResult {
            server_info: Some(ServerInfo {
                name: "eidos-lsp".into(),
                version: Some(VERSION.into()),
            }),
            capabilities: ServerCapabilities {
                execute_command_provider: Some(ExecuteCommandOptions {
                    commands: ALL_COMMANDS
                        .iter()
                        .map(|s| (*s).to_string())
                        .collect(),
                    ..Default::default()
                }),
                ..Default::default()
            },
            ..Default::default()
        })
    }

    async fn initialized(&self, _: InitializedParams) {
        let msg = match self.paths.read().await.as_ref() {
            Some(p) => format!(
                "eidos-lsp: repo={} (eidos.sessionList, eidos.contextPreview, eidos.memorySearch)",
                p.repo_root.display()
            ),
            None => "eidos-lsp: готов".into(),
        };
        self.client.log_message(MessageType::INFO, msg).await;
    }

    async fn shutdown(&self) -> Result<()> {
        Ok(())
    }

    async fn execute_command(&self, params: ExecuteCommandParams) -> Result<Option<Value>> {
        let paths = self.paths_or_err().await.map_err(|e| {
            tower_lsp::jsonrpc::Error {
                code: tower_lsp::jsonrpc::ErrorCode::InvalidParams,
                message: e.into(),
                data: None,
            }
        })?;
        let args = params.arguments;
        match execute(&paths, &params.command, &args) {
            Ok(v) => Ok(Some(v)),
            Err(e) => {
                self.client
                    .log_message(MessageType::ERROR, format!("execute_command: {e}"))
                    .await;
                Err(tower_lsp::jsonrpc::Error::invalid_params(e))
            }
        }
    }
}

/// Запуск LSP по stdin/stdout (пути — в ``initialize``, не при spawn).
pub async fn run_stdio() -> std::io::Result<()> {
    let stdin = tokio::io::stdin();
    let stdout = tokio::io::stdout();
    let (service, socket) = LspService::new(Backend::new);
    Server::new(stdin, stdout, socket).serve(service).await;
    Ok(())
}
