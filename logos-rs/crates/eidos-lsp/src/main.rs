//! ``eidos-lsp`` — stdio LSP (по умолчанию) или ``--info`` для путей.

use clap::Parser;
use eidos_lsp::server::run_stdio;
use eidos_lsp::print_paths_info;

#[derive(Debug, Parser)]
#[command(name = "eidos-lsp", about = "LSP-сервер Эйдос (stdio)")]
struct Args {
    /// Печать путей и списка команд без запуска LSP.
    #[arg(long)]
    info: bool,
    /// Флаг от glspc / generic LSP clients (режим всегда stdio).
    #[arg(long)]
    stdio: bool,
    /// Прочие аргументы клиента — игнорируем.
    #[arg(trailing_var_arg = true, allow_hyphen_values = true, hide = true)]
    _rest: Vec<String>,
}

#[tokio::main]
async fn main() {
    eprintln!(
        "eidos-lsp: start pid={} args={:?}",
        std::process::id(),
        std::env::args().collect::<Vec<_>>()
    );
    let args = Args::parse();
    if args.info {
        if let Err(e) = print_paths_info() {
            eprintln!("eidos-lsp: {e}");
            std::process::exit(1);
        }
        return;
    }

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("warn")),
        )
        .with_writer(std::io::stderr)
        .init();

    if let Err(e) = run_stdio().await {
        eprintln!("eidos-lsp: {e}");
        std::process::exit(1);
    }
}
