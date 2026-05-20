# ADR-0001: Rust workspace внутри Logos (Tauri + LSP)

**Статус:** принято (фаза 0, май 2026)  
**Контекст:** [MIGRATION_RUST_TAURI.md](../MIGRATION_RUST_TAURI.md)

## Решение

1. Весь новый код на Rust живёт в каталоге **`logos-rs/`** внутри репозитория `Logos`.
2. Cargo workspace из crate’ов с явными границами:
   - **`eidos-protocol`** — serde-типы и контракты (общие для CLI, Tauri, LSP).
   - **`eidos-core`** — логика: config, memory, llm, context, tools (без UI).
   - **`eidos-cli`** — headless бинарь, parity с `eidos.py`.
   - **`eidos-lsp`** — заглушка до фазы 6; зависит только от `eidos-protocol` + `eidos-core`.
3. Python (`kernel/`, `cli/`, `eidos.py`) остаётся **эталоном** до parity; стратегия **strangler**, не удаление.
4. **ML (torch, rubert):** отдельный Python **sidecar** `sidecars/eidos-ml/` (фаза 5+); Rust вызывает по HTTP/stdio, без линковки torch.
5. **Данные:** те же пути — `LOGOS_DATA_ROOT`, `REPO_ROOT`; Rust не импортирует Python.

## Вынос в отдельный репозиторий (позже)

Допустим, если:

- нет прямых зависимостей Rust → Python;
- конфигурация только через env и файлы в `data/`;
- `eidos-protocol` самодостаточен.

Механика: копия или `git subtree split` каталога `logos-rs/`, CI отдельно; репозиторий `Logos` может остаться хранилищем `data/`, BOOK, experiments.

## Отклонённые альтернативы

| Альтернатива | Почему нет |
|--------------|------------|
| Сразу отдельный repo | Двойной CI, сложнее golden tests против Python |
| Big bang, удалить Python | Долгий простой рабочего CLI |
| Tauri + subprocess Python как v1 | Быстро, но не даёт `eidos-core` и LSP |
| torch в Rust v1 | Тяжёлая сборка; sidecar проще |

## Последствия

- В корне репо появляется `logos-rs/`; CI (позже) — `cargo test`, `cargo clippy`.
- JSON Schema в `logos-rs/schemas/` — источник правды для контрактов; типы в Rust должны им соответствовать.
- Фаза 1: реализация WM + один LLM-ход в `eidos-core`.
