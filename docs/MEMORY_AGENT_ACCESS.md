# Доступ агента к памяти (любая глубина по запросу)

LSP отложен. Этот документ — план и чеклист **P0–P2**.

## Два контура

| Контур | Когда | Механизм |
|--------|--------|----------|
| **Пассивный** | Каждый ход | Блок «Активное извлечение» в system (`format_active_memory_retrieval_block`) |
| **По запросу** | Когда среза мало | LLM **tools** `memory_*` |

Переменные пассивного контура: `EIDOS_CHAT_MEMORY_PIPELINE`, `EIDOS_CHAT_ACTIVE_MEMORY`, `EIDOS_CHAT_ACTIVE_MEMORY_CHARS` — см. `cli/context.py`.

Переменные tools: `EIDOS_MEMORY_TOOLS` (по умолчанию **вкл.** при `EIDOS_TOOLS=1`; `0` — только отключить memory tools).

---

## Инструменты `memory_*`

| Tool | Назначение |
|------|------------|
| `memory_search_episodic` | Поиск по ключевым словам / cues, `recall_by_cues`, или свежие N |
| `memory_get_episode` | Полный эпизод по `id` (raw/summary) |
| `memory_list_semantic` | Принципы semantic DB, опциональный фильтр по подстроке |
| `memory_search_journal` | Семантический или лексический поиск по `data/journal/*.md` |
| `memory_read_journal` | Прочитать файл дневника целиком (с лимитом символов) |
| `memory_search_external` | Векторный поиск ExternalMemory (если индекс есть) |

---

## Фазы

### P0 — tools + sidecar + Rust chat/desktop ✅ (цель спринта)

- [x] `cli/memory_tools.py` — specs + execute
- [x] `cli/tools.py` — регистрация при `memory_tools_enabled()`
- [x] `kernel/eidos_sidecar.py` — `memory_tool_specs`, `memory_execute`
- [x] `eidos-core` — `py_sidecar` + маршрутизация в `chat.rs`
- [x] Тесты `tests/test_memory_tools.py`

### P1 — journal file + external + UX

- [x] `memory_read_journal`, `memory_search_external` в Python
- [x] Slash `/memory` в `chat_turn.rs` + desktop (справка по tools и pipeline)
- [x] Slash `/tools` — каталог + tool search (`cli/tool_catalog.py`, `cli/tool_search.py`)
- [x] `logos-rs/README.md` — env `EIDOS_MEMORY_TOOLS`

### P2 — Rust-native fallback (без sidecar)

- [x] `eidos-core/src/memory_tools.rs` — episodic/semantic/journal lexical
- [x] `eidos-core/src/external_store.rs` — `memory_search_external` лексика по `documents.db`
- [x] `execute_tool` / chat: fallback если sidecar выключен (`EIDOS_RUST_NO_SIDECAR=1`)
- [x] `eidos-core/src/active_memory.rs` — пассивный блок в system без Python (`EIDOS_RUST_NO_SIDECAR=1` или `EIDOS_RUST_ACTIVE_MEMORY=1`)
- [x] `sidecars/eidos-ml/` + `ml_client` — `EIDOS_ML_SIDECAR_URL` → `POST /search/journal`, `/search/external` (вектора); иначе лексика

---

## Критерий готовности

Агент в `eidos chat` и desktop может вызвать tool, получить эпизод по id или список journal hits, не полагаясь только на усечённый active block.

Связано: [MIGRATION_RUST_TAURI.md](MIGRATION_RUST_TAURI.md), [STRUCTURE.md](../STRUCTURE.md).
