# План переписки: Rust + Tauri (+ LSP)

Статус: **фаза 3 (Tauri desktop v1) закрыта**; **фаза 4 в работе** (контекст и пайплайны в Rust).  
Не рефакторинг текущего Python-кода, а **новый стек рядом** с сохранением форматов `data/` и конфигов.

**Решение по ML (зафиксировано):** `torch`, rubert, индексация journal/external — на первых фазах **Python sidecar** (отдельный процесс/HTTP). В Rust — вызов sidecar по контракту; перенос в ONNX/нативный код — позже, если понадобится.

**Размещение в репо (ещё не решено):** отдельный каталог `logos-rs/` внутри `Logos/` *или* соседний репозиторий с submodule — зафиксировать в Фазе 0 (ADR).

---

## Зачем

- Улучшить **UX** CLI-агента: сессии, стриминг, tool-трейсы, бюджет контекста, настройки профилей.
- Единый `**eidos-core`** для desktop (Tauri), headless CLI и будущего **LSP**.
- Python остаётся эталоном поведения и регрессией до достижения parity.

---

## Принципы

1. **Strangler, не big bang** — текущий `eidos.py` / `kernel/`* работают до зелёной матрицы parity.
2. **Общие данные** — `LOGOS_DATA_ROOT`, `data/working/current.json`, SQLite episodic/semantic, `config/agents*.yaml`.
3. **Контракты важнее кода** — JSON Schema / serde-типы для WM events, chat messages, tool specs.
4. **ML в sidecar** — Rust не тянет torch в v1; sidecar: embed, semantic search, reindex journal/external.
5. **Конфиг LLM как сейчас** — в desktop те же правила, что в CLI (см. ниже); UI редактирует `data/config/agents.yaml`, не только шаблон из репо.

### Конфигурация агентов (переносим 1:1)

Порядок поиска `agents.yaml` (уже в `cli/agent_backends.py`):

1. `EIDOS_AGENTS_CONFIG` — явный путь
2. `$LOGOS_DATA_ROOT/config/agents.yaml`
3. `<repo>/config/agents.yaml`
4. `<repo>/config/agents.defaults.yaml`

Правка только `config/agents.defaults.yaml` **не меняет** поведение, если существует `data/config/agents.yaml`. В Tauri: экран «Профили LLM» должен показывать **какой файл активен** и предупреждать о приоритете.

### Локальный LLM (WSL + Windows)

Типичный кейс: LM Studio / Ollama на **Windows**, CLI в **WSL**.

- В профиле `base_url` — IP хоста Windows, не `127.0.0.1` (для WSL это сам Linux).
- IP: `grep nameserver /etc/resolv.conf` (может меняться после перезагрузки).
- Эндпоинт чата: `POST …/v1/chat/completions` с `messages`, не `/v1/responses` с `input`.
- Санитизация Gemma thinking / inline `tool_call` — **P0** в `eidos-core` (см. `cli/llm_sanitize.py`).

---

## Целевая структура репозитория

```text
logos/                          # монорепо (вариант: подкаталог logos-rs/)
├── crates/
│   ├── eidos-protocol/         # Event, Message, ToolCall, SessionId (serde)
│   ├── eidos-core/             # config, memory, context, llm, tools, pipelines
│   ├── eidos-lsp/              # tower-lsp → тонкая обёртка над core
│   └── eidos-cli/              # headless REPL (parity с eidos.py)
├── apps/
│   └── eidos-desktop/          # Tauri 2: UI → invoke → core
├── sidecars/
│   └── eidos-ml/               # Python: torch, rubert, pickle-индексы (HTTP или stdio JSON-RPC)
├── python/                     # текущий Logos (freeze + golden tests)
└── data/                       # без смены путей
```

**Правило:** UI и LSP не дублируют логику — только вызывают `eidos-core`.

### Задел под LSP

- `eidos-protocol` — общие типы для чата, памяти, инструментов.
- `eidos-lsp` (позже): стандартные возможности + custom requests, например:
  - `eidos/memorySearch`
  - `eidos/sessionList`
  - `eidos/contextPreview`
- Чат — продуктовый UI; LSP — навигация по репозиторию и подсказки из памяти.

---

## Инвентарь parity (что повторить)

### CLI / транспорт


| Функция                                              | Модуль (Python)                                    | Приоритет     |
| ---------------------------------------------------- | -------------------------------------------------- | ------------- |
| `chat`, `ask`, `boot`, `sleep`                       | `cli/app.py`, `kernel/memory.py`, `kernel/boot.py` | P0            |
| `import-opencode`                                    | `kernel/opencode_adapter.py`                       | P2            |
| `run` / `review` (research, experiment, code_review) | `cli/pipelines/`                                   | P1–P2         |
| Сессии UUID, `cli_sessions/`, WM `cli_session_id`    | `cli/session.py`                                   | P0            |
| LLM OpenAI-compatible, профили YAML                  | `cli/llm.py`, `cli/agent_backends.py`              | P0            |
| Per-tool routing профилей                            | `cli/tool_routing.py`                              | P1            |
| Multi-turn tools, лимиты                             | `cli/runtime.py`, `cli/tools.py`                   | P0            |
| Сборка контекста, бюджеты, active memory             | `cli/context.py`                                   | P1 (по слоям) |
| Санитизация Gemma (`channel` / inline `tool_call`)   | `cli/llm_sanitize.py`                              | P0            |
| `/env`, metrics, identity                            | `cli/env_view.py`, `cli/identity.py`               | P1 (в UI)     |
| Публичный лог в репо                                 | `kernel/repo_public_log.py`                        | P2            |


### Инструменты


| Инструмент                             | Приоритет                          |
| -------------------------------------- | ---------------------------------- |
| `read_workspace_file`                  | P0                                 |
| `fetch_https_url`                      | P1                                 |
| Playwright-набор                       | P2 (subprocess bridge или sidecar) |
| `bash` только `python3 eidos.py sleep` | P2                                 |


### Ядро памяти


| Модуль                                           | Стратегия                                     |
| ------------------------------------------------ | --------------------------------------------- |
| WorkingMemory (JSON)                             | Rust first, тот же файл                       |
| Episodic / Semantic (SQLite)                     | Rust read/write, схема 1:1                    |
| Sleep pipeline                                   | Порт по шагам; упрощённый sleep в v1 допустим |
| Boot, health, last words                         | P0–P1                                         |
| Journal (markdown)                               | P1; semantic index → **sidecar ML**           |
| External memory + vectors                        | P2; vectors → **sidecar ML**                  |
| Goals, planner, mission, ethics, verifier, pulse | P2+                                           |
| Instrumental registry                            | P1                                            |


### Вне первой волны

- `dashboard/app.py`
- Runtime `experiments/`* (артефакты в репо остаются)

---

## Python ML sidecar (`eidos-ml`)

**Назначение:** всё, что сегодня тянет `transformers` / `torch` / pickle-индексы.

**Интерфейс (черновик):**

- Транспорт: HTTP localhost (простой) или stdio JSON-RPC (один бинарь без порта).
- Методы (примерный список):
  - `POST /embed` — текст → вектор (опционально)
  - `POST /search/journal` — query, top_k
  - `POST /search/external` — query, top_k
  - `POST /reindex/journal` — пересборка индекса
  - `GET /health` — модель загружена, пути к весам

**В Rust:** `eidos_core::ml_client` (`GET /health` при `EIDOS_ML_SIDECAR_URL`); при недоступности sidecar — lexical fallback (как сейчас substring в journal).

**DoD sidecar v0:** journal semantic search работает для CLI/Tauri так же, как при прямом импорте torch в Python, без линковки torch в Rust.

---

## Фазы

### Фаза 0 — Контракты и ADR (1–2 нед.) ✅

- [x] ADR: [docs/adr/0001-rust-tauri-workspace.md](adr/0001-rust-tauri-workspace.md)
- [x] JSON Schema: `logos-rs/schemas/` (wm, working-memory, episodic, semantic-principle, agents, tool spec)
- [x] Rust типы: `logos-rs/crates/eidos-protocol`
- [x] Workspace + `eidos-core` (paths), `eidos-cli` (`--help`, `paths`), заглушка `eidos-lsp`
- [x] CI: `cargo test` в GitHub Actions (`.github/workflows/rust.yml`)
- Parity checklist (таблица выше) — по мере фаз

**Сборка:** см. [logos-rs/README.md](../logos-rs/README.md).

### Фаза 1 — `eidos-core` минимум ✅ (код)

- [x] Пути: `LOGOS_DATA_ROOT`, `REPO_ROOT` (`eidos-core::paths`)
- [x] WM load/save/add_event (`working_memory.rs`)
- [x] LLM `reqwest` + YAML-профили (`agents.rs`, `llm.rs`)
- [x] `llm_sanitize` (Gemma channels / inline tool_call)
- [x] `read_workspace_file` (`tools.rs`)
- [x] Context для ask: system stub + фрагмент `AGENTS.md`
- [x] `eidos ask` — один ход; по умолчанию пишет в `current.json` (`--no-wm` отключает)

**DoD:** `cd logos-rs && cargo run -p eidos-cli -- ask "привет" --agent-profile openai_compatible_local`

**Пример (WSL → LM Studio на Windows):**

```bash
# DEEPSEEK_API_KEY в ~/Logos/.env (см. .env.example)
cd logos-rs && cargo run -p eidos-cli -- ask "Привет"
```

См. также `eidos ask --stub` и `eidos paths`.

### Фаза 2 — CLI parity ✅

- [x] `eidos chat` — интерактивный цикл, `/exit`, `/boot`, `/env`, `/env active`, `/budget`
- [x] Сессии UUID, `data/cli_sessions/`, `latest.json`
- [x] Tool loop: `eidos_echo`, `read_workspace_file`, опционально `fetch_https_url`
- [x] Boot полный через `kernel/eidos_sidecar.py` (или `EIDOS_RUST_BOOT=1` — краткий Rust)
- [x] Контекст LLM через sidecar-daemon (один Python на сессию; `EIDOS_RUST_CONTEXT=1` — Rust)
- [x] Пайплайны в чате: `/pipeline`, `/run`, `/review` (через sidecar)
- [x] Identity capture, `tools_allowed` на identity-вопросах, `format_llm_pending_banner`
- [x] `EIDOS_REPO_PUBLIC_LOG` через sidecar `post_public_log`
- [x] Smoke: `tests/test_eidos_sidecar.py`, `logos-rs/.../llm_sanitize_golden.rs`
- [x] Episodic SQLite в Rust: `EpisodicStore` (`query`, `store`, `get_by_id`), схема и миграции колонок как в Python; CLI `eidos episodic list` (полный sleep/интеграция эпизодов по-прежнему в Python)
- [x] Semantic SQLite в Rust: `SemanticStore`, CLI `eidos semantic list` (`knowledge.db` 1:1 с Python)
- [ ] Playwright tools — нативный Rust позже; `eidos playwright doctor` + Python Playwright (`EIDOS_PLAYWRIGHT=0` выкл.)
- [x] CI `cargo test` в GitHub Actions

**DoD:** `cargo run -p eidos-cli -- chat --agent-profile openai_compatible_local` (из `logos-rs/`)

```bash
cd logos-rs && cargo run -p eidos-cli -- chat --new
```

### Фаза 3 — Tauri desktop v1 ✅

- [x] Каркас `apps/eidos-desktop` (Tauri 2 + Vite + TS)
- [x] `eidos-core::desktop` — сессии, сообщения WM, `send_message`, boot
- [x] `invoke` → `DesktopRuntime` (тот же sidecar/LLM, что CLI)
- [x] UI: чат, сессии, boot, env/budget панель, пайплайны в вводе
- [x] История с tool-сообщениями после ответа
- [x] Сборка на WSL: системные deps + IBUS — **описано** в [README desktop](../logos-rs/apps/eidos-desktop/README.md) (apt-пакеты, IME, запуск с Windows)
- [x] Стриминг ответа (SSE + Tauri events; после tool round — replay чанками; дельты в DOM батчатся через rAF; во время tool round видны спиннер и «…»)
- [x] Панель метрик контекста (кнопка «Контекст», sidecar `context_metrics`)
- [x] CI: `.github/workflows/rust.yml` — `cargo test --workspace`
- [x] Sleep из UI (`run_sleep` → `python3 eidos.py sleep`)
- [x] Редактор `agents.yaml` в окне (валидация `AgentsConfig` перед записью; чтение как у рантайма; сохранение в `data/config/…` или `EIDOS_AGENTS_CONFIG` в пределах repo/data; после сохранения UI шапки через `refreshState`)

**DoD (выполнен):** повседневный чат без терминала — тот же WM/sidecar, что `eidos chat`; стриминг; контекст; сон; настройки; **базовый редактор agents.yaml в окне** (кнопка «agents»). Углублённый UI бюджета и hot-reload профиля — **фаза 4+**.

См. [logos-rs/apps/eidos-desktop/README.md](../logos-rs/apps/eidos-desktop/README.md).

### Фаза 4 — Контекст и пайплайны (4–6 нед., в работе)

- [x] Модуль `context_budget`: `EIDOS_CHAT_TOTAL_CHARS`, усечение истории и system.
- [x] Модуль `context_wm_summary`: при `EIDOS_CHAT_TOTAL_CHARS` > 0 и `EIDOS_CHAT_SUMMARIZE_OLD_WM=1` — ранняя история сворачивается в system (timeline; без `compress_episode`).
- [x] Активная память в **Rust**-ветке: sidecar op `active_memory_block` → `format_active_memory_retrieval_block` (full pipeline в Python).
- [x] Слойное бюджетирование (`_build_system_extra_with_budget`) и parity слоёв без полного sidecar (см. `context_system_extra`, op `semantic_principles_block`).
- [x] Пайплайны вне чата: `eidos run` / `eidos review` в `eidos-cli` делегируют `python3 <repo>/eidos.py run|review` (та же логика, что у Python CLI).

### Фаза 5 — Ядро и инструменты ✅ (v1 Rust CLI / core)

- [x] Episodic SQLite в Rust (`episodic_store`, `eidos episodic list`).
- [x] Semantic SQLite в Rust (`semantic_store`, `eidos semantic list`; upsert `store_principle` для parity).
- [x] Sleep из headless Rust CLI → `eidos.py sleep`.
- [x] Journal: список `data/journal/*.md` (`eidos journal list`; полнотекст/вектора — по-прежнему Python `kernel.journal`).
- [x] `import-opencode` из Rust CLI → `eidos.py import-opencode`.
- [x] Playwright: `eidos playwright doctor` (проверка импорта пакета в Python; инструменты в Python/Rust chat по умолчанию вкл., `EIDOS_PLAYWRIGHT=0` — выкл.).
- [x] ML sidecar: клиент `GET /health` при `EIDOS_ML_SIDECAR_URL` или `EIDOS_ML_BASE` (`eidos ml health`; полный сервис — раздел «Python ML sidecar» выше).
- [ ] Расширенный repo public log, нативные вектора journal/external в Rust (не блокер для day-to-day).

| Инвентарь | SQLite / journal | Статус Rust |
|------------|------------------|-------------|
| Episodic / Semantic | `episodes.db`, `knowledge.db` | чтение/базовая запись в `eidos-core` |
| Journal markdown | `data/journal/*.md` | список файлов; индекс rubert — Python |
| External DB | `documents.db` | путь в `Paths`; I/O позже |

### Фаза 6 — `eidos-lsp` (3–4 нед. после стабильного core)

- `tower-lsp`, workspace = repo root.
- Custom requests памяти; опционально встроенный редактор в Tauri.

### Фаза 7 — ML native (опционально)

- ONNX / `ort` для rubert — только если sidecar станет узким местом.

---

## Альтернатива: быстрый demo UI

Tauri + subprocess `python eidos.py chat` (JSON по stdio) — 2–3 недели demo, **не** заменяет этот план, только прототип UX.

---

## Риски


| Риск                             | Митигация                                                      |
| -------------------------------- | -------------------------------------------------------------- |
| Расхождение Python/Rust в памяти | Одна `data/`, версия схемы SQLite, golden tests                |
| Sidecar не запущен               | Lexical fallback + явное сообщение в UI                        |
| Gemma / локальные модели         | Общий `llm_sanitize` в core + тесты на сэмплах из `log/cli/`   |
| Scope UI                         | v1 = chat + sessions + tools + context; dashboard/mission — v2 |


---

## Критерий «можно заморозить Python CLI»

~80% parity checklist зелёный; sleep и episodic round-trip проверены; Tauri v1 используется ежедневно; sidecar ML покрывает journal search.

---

## Первые шаги (когда будет время)

1. ADR + `eidos-protocol` (serde types из WM event).
2. `eidos-core` + один golden test на два WM-события.
3. Черновик `sidecars/eidos-ml` с `GET /health` и `POST /search/journal`.
4. Статичный макет Tauri (без логики) для согласования UX.

---

## Открытые вопросы (для обсуждения)


| #   | Вопрос               | Варианты                                                           |
| --- | -------------------- | ------------------------------------------------------------------ |
| 1   | Где жить Rust-код?   | `Logos/logos-rs/` vs отдельный repo                                |
| 2   | Первый deliverable   | Только `eidos-cli` vs сразу Tauri-скелет                           |
| 3   | Demo UI (2–3 нед.)   | Subprocess Python vs ждать Фазу 1 core                             |
| 4   | Playwright в v1      | Subprocess Python bridge vs отложить до Фазы 5                     |
| 5   | Sidecar ML транспорт | HTTP localhost vs stdio JSON-RPC                                   |
| 6   | Стриминг ответа LLM  | ✅ Фаза 3: SSE + Tauri events (replay после tool round)             |
| 7   | LSP в v1 desktop     | Встроенный редактор + `eidos-lsp` vs только внешний VS Code/Cursor |


Рекомендация на старт обсуждения: **Фаза 0 + Фаза 1** (`eidos-protocol`, `eidos-core`, headless один ход чата), параллельно **статичный макет Tauri** без логики; sidecar ML — когда понадобится journal search в новом UI.

---

## Связанные документы

- [CLI_ARCH.md](../CLI_ARCH.md) — архитектура текущего CLI
- [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) — план зрелости Python-стека
- [STRUCTURE.md](../STRUCTURE.md) — типы памяти и `data/`
- [config/agents.defaults.yaml](../config/agents.defaults.yaml) — шаблон профилей LLM

