# eidos-lsp (фаза 6)

LSP-сервер для репозитория Эйдос: память, сессии, превью контекста — поверх `eidos-core`, без дублирования логики Python.

## Статус

**Заглушка v0** — бинарник печатает пути и версию. Следующий шаг: `tower-lsp`, `initialize`, custom requests:

| Request | Назначение |
|---------|------------|
| `eidos/memorySearch` | семантика / journal |
| `eidos/sessionList` | список `data/cli_sessions/` |
| `eidos/contextPreview` | метрики бюджета текущей сессии |

## Запуск (проверка каркаса)

```bash
cd logos-rs && cargo run -p eidos-lsp
```

## Интеграция в редактор

Пример для VS Code / Cursor (`settings.json`):

```json
{
  "eidos-lsp.serverPath": "/path/to/logos-rs/target/debug/eidos-lsp"
}
```

(полная схема появится с реализацией stdio LSP.)

## Связанные документы

- [docs/MIGRATION_RUST_TAURI.md](../../../docs/MIGRATION_RUST_TAURI.md) — фаза 6
- `eidos-core`, `eidos-protocol` — общие типы WM и памяти
