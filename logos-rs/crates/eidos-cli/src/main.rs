//! Бинарь `eidos` — headless CLI Эйдоса (Rust).

use clap::{Parser, Subcommand};
use eidos_core::{
    list_journal_markdown, ml_sidecar_health_check, resolve_paths, run_ask, run_chat_interactive,
    run_cli_chat_boot, ChatOptions, CoreError, EpisodicStore, SemanticStore, Sidecar, VERSION,
    WorkingMemory,
};
use std::process::Command;

#[derive(Parser)]
#[command(
    name = "eidos",
    version = VERSION,
    about = "Эйдос — CLI поверх eidos-core (Rust)",
    long_about = "Переписка Python CLI: см. docs/MIGRATION_RUST_TAURI.md"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Интерактивный диалог (фаза 2).
    Chat {
        #[arg(long, help = "Новая сессия (очистить WM)")]
        new: bool,
        #[arg(long, help = "UUID сессии")]
        session: Option<String>,
        #[arg(long, help = "Без вызова LLM")]
        stub: bool,
        #[arg(long, help = "Не выполнять boot при входе")]
        no_boot: bool,
        #[arg(long, help = "Профиль из agents.yaml")]
        agent_profile: Option<String>,
    },
    /// Один вопрос к LLM (фаза 1).
    Ask {
        #[arg(required = true)]
        question: Vec<String>,
        #[arg(long)]
        stub: bool,
        #[arg(long)]
        agent_profile: Option<String>,
        #[arg(long, help = "Не писать в data/working/current.json")]
        no_wm: bool,
    },
    /// Boot-контекст (краткий).
    Boot {
        #[arg(long, help = "Профиль из agents.yaml")]
        agent_profile: Option<String>,
    },
    /// Sleep-пайплайн памяти — `python3 eidos.py sleep` (полная логика в Python).
    Sleep {
        #[arg(long, help = "Игнорировать lock-файл")]
        force: bool,
    },
    /// Именованный пайплайн — тот же `python3 eidos.py run …` (research, experiment, code_review).
    Run {
        #[arg(long, help = "Профиль из agents.yaml")]
        agent_profile: Option<String>,
        /// Аргументы для `eidos.py run` (имя пайплайна, тема, --stub, --paths …).
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        passthrough: Vec<String>,
    },
    /// Сокращение для `run code_review` — делегирует `python3 eidos.py review …`.
    Review {
        #[arg(long, help = "Профиль из agents.yaml")]
        agent_profile: Option<String>,
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        passthrough: Vec<String>,
    },
    /// Эпизодическая память SQLite (`data/episodic/episodes.db`) — чтение из Rust.
    Episodic {
        #[command(subcommand)]
        cmd: EpisodicCmd,
    },
    /// Семантическая память `knowledge.db` (Rust).
    Semantic {
        #[command(subcommand)]
        cmd: SemanticCmd,
    },
    /// Журнал `data/journal/*.md` (список файлов).
    Journal {
        #[command(subcommand)]
        cmd: JournalCmd,
    },
    /// Импорт OpenCode → episodic (`python3 eidos.py import-opencode …`).
    #[command(name = "import-opencode")]
    ImportOpencode {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        passthrough: Vec<String>,
    },
    /// Проверка Python-пакета Playwright (без запуска браузера).
    Playwright {
        #[command(subcommand)]
        cmd: PlaywrightCmd,
    },
    /// ML sidecar HTTP (`EIDOS_ML_SIDECAR_URL`).
    Ml {
        #[command(subcommand)]
        cmd: MlCmd,
    },
    /// Пути и активный agents.yaml.
    Paths,
}

#[derive(Subcommand)]
enum EpisodicCmd {
    /// Последние эпизоды (как `EpisodicMemory.query` в Python).
    List {
        #[arg(long, default_value_t = 20)]
        limit: usize,
        #[arg(long, default_value_t = 0.0)]
        min_salience: f64,
    },
}

#[derive(Subcommand)]
enum SemanticCmd {
    /// Принципы с фильтром по confidence.
    List {
        #[arg(long, default_value_t = 0.1)]
        min_confidence: f64,
        #[arg(long, default_value_t = 100usize)]
        limit: usize,
    },
}

#[derive(Subcommand)]
enum JournalCmd {
    /// Список `*.md` в каталоге журнала (новые сверху).
    List {
        #[arg(long, default_value_t = 50usize)]
        limit: usize,
    },
}

#[derive(Subcommand)]
enum PlaywrightCmd {
    /// Проверить, что пакет `playwright` импортируется в том же Python, что и `python3`.
    Doctor,
}

#[derive(Subcommand)]
enum MlCmd {
    /// GET `{EIDOS_ML_SIDECAR_URL}/health`.
    Health,
}

fn main() {
    let code = run(std::env::args_os());
    std::process::exit(code);
}

fn run<I, T>(args: I) -> i32
where
    I: IntoIterator<Item = T>,
    T: Into<std::ffi::OsString> + Clone,
{
    let cli = match Cli::try_parse_from(args) {
        Ok(c) => c,
        Err(e) => {
            e.print().ok();
            return i32::from(e.exit_code());
        }
    };

    if let Some(profile) = cli_agent_profile(&cli) {
        std::env::set_var("EIDOS_AGENT_PROFILE", profile);
    }

    match cli.command {
        Commands::Paths => cmd_paths(),
        Commands::Ask {
            question,
            stub,
            agent_profile,
            no_wm,
        } => cmd_ask(&question, stub, agent_profile.as_deref(), !no_wm),
        Commands::Chat {
            new,
            session,
            stub,
            no_boot,
            agent_profile,
        } => cmd_chat(new, session, stub, no_boot, agent_profile.as_deref()),
        Commands::Boot { .. } => cmd_boot(),
        Commands::Sleep { force } => {
            let mut a: Vec<String> = Vec::new();
            if force {
                a.push("--force".to_string());
            }
            cmd_python_pipeline("sleep", &a)
        }
        Commands::Run { passthrough, .. } => cmd_python_pipeline("run", &passthrough),
        Commands::Review { passthrough, .. } => cmd_python_pipeline("review", &passthrough),
        Commands::Episodic { cmd } => match cmd {
            EpisodicCmd::List {
                limit,
                min_salience,
            } => cmd_episodic_list(limit, min_salience),
        },
        Commands::Semantic { cmd } => match cmd {
            SemanticCmd::List {
                min_confidence,
                limit,
            } => cmd_semantic_list(min_confidence, limit),
        },
        Commands::Journal { cmd } => match cmd {
            JournalCmd::List { limit } => cmd_journal_list(limit),
        },
        Commands::ImportOpencode { passthrough } => {
            cmd_python_pipeline("import-opencode", &passthrough)
        },
        Commands::Playwright { cmd } => match cmd {
            PlaywrightCmd::Doctor => cmd_playwright_doctor(),
        },
        Commands::Ml { cmd } => match cmd {
            MlCmd::Health => cmd_ml_health(),
        },
    }
}

fn cmd_ml_health() -> i32 {
    match ml_sidecar_health_check() {
        Ok(body) => {
            println!("{body}");
            0
        }
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cmd_playwright_doctor() -> i32 {
    let paths = match resolve_paths() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("eidos: {e}");
            return 1;
        }
    };
    let code = r#"import importlib.util, sys
spec = importlib.util.find_spec("playwright")
if spec is None:
    print("Пакет playwright не найден. Установите: pip install playwright && python3 -m playwright install chromium", file=sys.stderr)
    sys.exit(1)
print("playwright: Python package OK")
"#;
    let st = match Command::new("python3")
        .arg("-c")
        .arg(code)
        .current_dir(&paths.repo_root)
        .status()
    {
        Ok(s) => s,
        Err(e) => {
            eprintln!("eidos: python3: {e}");
            return 1;
        }
    };
    st.code().unwrap_or(1)
}

fn cmd_journal_list(limit: usize) -> i32 {
    match resolve_paths() {
        Ok(paths) => match list_journal_markdown(&paths, limit) {
            Ok(entries) => {
                for e in entries {
                    let v = serde_json::json!({
                        "path": e.relative,
                        "modified_secs": e.modified_secs,
                    });
                    if let Ok(line) = serde_json::to_string(&v) {
                        println!("{line}");
                    }
                }
                0
            }
            Err(e) => {
                eprintln!("eidos: {e}");
                1
            }
        },
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cmd_semantic_list(min_confidence: f64, limit: usize) -> i32 {
    match resolve_paths() {
        Ok(paths) => match SemanticStore::open(&paths) {
            Ok(store) => match store.get_principles(min_confidence, limit) {
                Ok(rows) => {
                    for r in rows {
                        match serde_json::to_string(&r) {
                            Ok(line) => println!("{line}"),
                            Err(e) => eprintln!("eidos: JSON: {e}"),
                        }
                    }
                    0
                }
                Err(e) => {
                    eprintln!("eidos: {e}");
                    1
                }
            },
            Err(e) => {
                eprintln!("eidos: {e}");
                1
            }
        },
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cmd_episodic_list(limit: usize, min_salience: f64) -> i32 {
    match resolve_paths() {
        Ok(paths) => match EpisodicStore::open(&paths) {
            Ok(store) => match store.query(limit, min_salience) {
                Ok(rows) => {
                    for r in rows {
                        match serde_json::to_string(&r) {
                            Ok(line) => println!("{line}"),
                            Err(e) => eprintln!("eidos: JSON: {e}"),
                        }
                    }
                    0
                }
                Err(e) => {
                    eprintln!("eidos: {e}");
                    1
                }
            },
            Err(e) => {
                eprintln!("eidos: {e}");
                1
            }
        },
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cli_agent_profile(cli: &Cli) -> Option<String> {
    match &cli.command {
        Commands::Chat { agent_profile, .. }
        | Commands::Ask { agent_profile, .. }
        | Commands::Boot { agent_profile, .. }
        | Commands::Run { agent_profile, .. }
        | Commands::Review { agent_profile, .. } => agent_profile.clone(),
        _ => None,
    }
}

fn cmd_paths() -> i32 {
    match resolve_paths() {
        Ok(p) => {
            println!("repo_root:  {}", p.repo_root.display());
            println!("data_root:  {}", p.data_root.display());
            println!("working_wm: {}", p.working_memory_path().display());
            println!("episodic_db: {}", p.episodic_db_path().display());
            println!("semantic_db: {}", p.semantic_db_path().display());
            println!("journal_dir: {}", p.journal_dir().display());
            println!("external_db: {}", p.external_db_path().display());
            match p.find_agents_config() {
                Some(cfg) => println!("agents_cfg: {}", cfg.display()),
                None => println!("agents_cfg: <не найден>"),
            }
            0
        }
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cmd_boot() -> i32 {
    match resolve_paths() {
        Ok(paths) => {
            let mut wm = WorkingMemory::open(&paths);
            let mut sidecar = Sidecar::open(paths.clone());
            match run_cli_chat_boot(&paths, &mut wm, &mut sidecar) {
                Ok(text) => {
                    println!("{text}");
                    0
                }
                Err(e) => {
                    eprintln!("eidos: {e}");
                    1
                }
            }
        }
        Err(e) => {
            eprintln!("eidos: {e}");
            1
        }
    }
}

fn cmd_chat(new: bool, session: Option<String>, stub: bool, no_boot: bool, profile: Option<&str>) -> i32 {
    if new && session.is_some() {
        eprintln!("eidos: нельзя --new и --session вместе.");
        return 2;
    }
    match run_chat_interactive(ChatOptions {
        new_session: new,
        session_id: session,
        stub,
        no_boot,
        profile_name: profile.map(str::to_string),
    }) {
        Ok(()) => 0,
        Err(e) => {
            print_error(&e);
            exit_code_for(&e)
        }
    }
}

fn cmd_ask(question: &[String], stub: bool, profile: Option<&str>, record_wm: bool) -> i32 {
    let q = question.join(" ").trim().to_string();
    if q.is_empty() {
        eprintln!("eidos: передайте текст вопроса.");
        return 1;
    }
    if stub {
        println!("[stub] {q}");
        return 0;
    }
    match run_ask(&q, profile, record_wm) {
        Ok(text) => {
            println!("{text}");
            0
        }
        Err(e) => {
            print_error(&e);
            exit_code_for(&e)
        }
    }
}

fn print_error(e: &CoreError) {
    eprintln!("eidos: {e}");
    if matches!(e, CoreError::LlmConfig(_)) {
        eprintln!(
            "Подсказка: ключ в <repo>/.env (DEEPSEEK_API_KEY); по умолчанию профиль deepseek. \
             Локальная модель: EIDOS_AGENT_PROFILE=openai_compatible_local"
        );
    }
}

fn exit_code_for(e: &CoreError) -> i32 {
    match e {
        CoreError::LlmConfig(_) => 2,
        CoreError::Http(_) => 3,
        _ => 1,
    }
}

/// Делегирование в `python3 <repo>/eidos.py <sub>` (полная логика пайплайнов в Python).
fn cmd_python_pipeline(sub: &str, passthrough: &[String]) -> i32 {
    let paths = match resolve_paths() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("eidos: {e}");
            return 1;
        }
    };
    let eidos_py = paths.repo_root.join("eidos.py");
    if !eidos_py.is_file() {
        eprintln!("eidos: не найден {}", eidos_py.display());
        return 1;
    }
    let st = match Command::new("python3")
        .arg(&eidos_py)
        .arg(sub)
        .args(passthrough)
        .current_dir(&paths.repo_root)
        .env("PYTHONPATH", &paths.repo_root)
        .status()
    {
        Ok(s) => s,
        Err(e) => {
            eprintln!("eidos: не удалось запустить python3: {e}");
            return 1;
        }
    };
    st.code().unwrap_or(1)
}
