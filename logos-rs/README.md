# logos-rs — Rust workspace Эйдоса

Фаза 0–2: контракты, headless CLI (`ask`, `chat`).  
План: [docs/MIGRATION_RUST_TAURI.md](../docs/MIGRATION_RUST_TAURI.md)

## Crate’ы

| Crate | Назначение |
|-------|------------|
| `eidos-protocol` | Типы WM, chat, agents.yaml |
| `eidos-core` | Пути, WM, LLM, context, episodic SQLite, tools, sidecar |
| `eidos-cli` | Бинарь `eidos` |
| `eidos-lsp` | stdio LSP + `eidos.sessionList` / `contextPreview` / `memorySearch` (фаза 6) |

## `eidos chat` (фаза 2)

```bash
# Один раз: cp .env.example .env и DEEPSEEK_API_KEY=...
cd logos-rs
cargo run -p eidos-cli -- chat --new
```

Команды: `/exit`, `/quit`, `/boot`, `/env`, `/env active`, `/budget`, `/pipeline`, `/run`, `/review`. Вне REPL: **`eidos run …`** и **`eidos review …`** — делегирование в `python3 <repo>/eidos.py` (полные пайплайны).

**Parity с Python:** долгоживущий `python3 kernel/eidos_sidecar.py` (JSON-lines) — boot, контекст, пайплайны, public log.

| Переменная | Эффект |
|------------|--------|
| `EIDOS_RUST_NO_SIDECAR=1` | без долгоживущего Python sidecar: `memory_*` в Rust (episodic/semantic/journal + **лексический** `memory_search_external`); **браузер** `browser_*` не держит сессию между вызовами |
| `EIDOS_PLAYWRIGHT` | по умолчанию **вкл.** — инструменты `browser_*` в Rust-чате через sidecar; `0`/`false`/`no`/`off` — выкл.; нужны `playwright` + браузерные зависимости |
| `EIDOS_HTTP_FETCH` | по умолчанию **вкл.** — инструмент `fetch_https_url` (GET публичных URL); `0`/`false`/`no`/`off` — выкл. |
| `EIDOS_RUST_BOOT=1` | краткий Rust-boot |
| `EIDOS_RUST_CONTEXT=1` | упрощённый system prompt в Rust |
| `EIDOS_CHAT_SUMMARIZE_OLD_WM=1` | при **Rust**-контексте и `EIDOS_CHAT_TOTAL_CHARS` > 0 — сжать ранний хвост WM в system (timeline) |
| `EIDOS_CHAT_ACTIVE_MEMORY=0` | не вызывать `active_memory_block` в Rust-ветке (по умолчанию вкл.) |
| `EIDOS_MEMORY_TOOLS=0` | не передавать LLM tools `memory_*` (по умолчанию вкл. при `EIDOS_TOOLS=1`) |
| `EIDOS_CHAT_TOTAL_CHARS` | лимит символов промпта в **Rust**-сборке |
| `EIDOS_CHAT_LAYER_BUDGET` | при заданном `EIDOS_CHAT_TOTAL_CHARS` по умолчанию **вкл.** — extra system собирается по слоям с остаточным бюджетом (как Python 8.1); `0` — полные блоки как в `build_chat_context` |
| `EIDOS_STREAM` | `1` — SSE-дельты в stdout (CLI) |
| `EIDOS_STREAM_REPLAY_MS` | пауза между чанками replay после tool round (мс); desktop по умолчанию 6 |

**Фаза 5 (headless):** `eidos sleep`; `eidos episodic list`; **`eidos semantic list`**; **`eidos journal list`**; **`eidos import-opencode`**; **`eidos playwright doctor`**; **`eidos ml health`** (нужен `EIDOS_ML_SIDECAR_URL`). См. `eidos --help`.

## `eidos ask` (фаза 1)

```bash
cargo run -p eidos-cli -- ask "Вопрос" --agent-profile openai_compatible_local
cargo run -p eidos-cli -- ask "тест" --stub
```

## Сборка

```bash
cd logos-rs
cargo build
cargo test -p eidos-core
```

Бинарь: `target/debug/eidos`
