# eidos-lsp (фаза 6)

LSP-сервер для репозитория Эйдос: сессии, превью контекста, список journal — поверх `eidos-core`.

## Статус

**v0.1 — stdio LSP** (`tower-lsp`). Команды через **`workspace/executeCommand`**:

| Команда | Назначение |
|---------|------------|
| `eidos.sessionList` | JSON-массив `data/cli_sessions/*.json` |
| `eidos.contextPreview` | активная сессия, события WM, последний снимок бюджета |
| `eidos.memorySearch` | `data/journal/*.md` (аргумент `[0]` — подстрока в имени) |

Сервер **не** подсвечивает Rust/Python как язык — только служебные команды Эйдос.

## Сборка

```bash
cd /path/to/Logos/logos-rs
cargo build -p eidos-lsp
```

Проверка без редактора:

```bash
cargo run -p eidos-lsp -- --info
```

Должны появиться `repo`, `data`, `WM` и три команды.

---

## Подключение в VS Code или Cursor (пошагово)

VS Code и Cursor **сами не запускают** произвольный LSP из одной строки в `settings.json`. Нужен маленький **клиент-расширение** из Marketplace (ставится один раз).

### Шаг 0. Открыть правильную папку

Откройте **корень репозитория Logos** (`eidos.py` в корне), а не только `logos-rs/`.  
Иначе `eidos-lsp` может не найти `data/` и `kernel/`.

В WSL путь обычно: `/home/user/Logos`.

### Шаг 1. Собрать бинарник

```bash
cd /home/user/Logos/logos-rs
cargo build -p eidos-lsp
```

Запомните путь (debug-сборка):

- Linux/WSL: `/home/user/Logos/logos-rs/target/debug/eidos-lsp`
- Windows (если собирали там): `...\Logos\logos-rs\target\debug\eidos-lsp.exe`

### Шаг 2. Установить расширение-клиент LSP

**Вариант A (проще) — [glspc](https://marketplace.visualstudio.com/items?itemName=torokati44.glspc)** «Generic LSP Client»:

1. `Ctrl+Shift+X` → Extensions.
2. Поиск: `glspc` или `Generic LSP Client`.
3. Install.

**Вариант B — [vscode-lsp-generic](https://marketplace.visualstudio.com/items?itemName=maximsmol.vscode-lsp-generic)** (гибче, если нужны конкретные типы файлов):

1. Поиск: `vscode-lsp-generic`.
2. Install.

В **Cursor** те же шаги: Extensions → Marketplace (совместим с VS Code).

### Шаг 3. Прописать путь к серверу

`Ctrl+Shift+P` → **Preferences: Open User Settings (JSON)**  
или workspace: **`.vscode/settings.json`** в корне Logos.

#### Вариант A — glspc

```json
{
  "glspc.serverPath": "/home/user/Logos/logos-rs/target/debug/eidos-lsp"
}
```

Подставьте **свой** абсолютный путь. На Windows — `C:\\...\\eidos-lsp.exe` (двойные обратные слэши).

После сохранения перезагрузите окно: `Developer: Reload Window`.

#### Вариант B — vscode-lsp-generic

```json
{
  "lsp_generic_client": {
    "servers": {
      "eidos": {
        "name": "Eidos",
        "path": "/home/user/Logos/logos-rs/target/debug/eidos-lsp",
        "args": [],
        "documentSelector": ["markdown", "plaintext"]
      }
    }
  }
}
```

`documentSelector` — для каких языков в редакторе поднимать сервер (можно добавить `"yaml"` для `agents.yaml`).

### Шаг 4. «Включить» сервер в окне

**glspc:** откройте любой файл в режиме **Plain Text** (`Plain Text` в правом нижнем углу → выбрать Plain Text) или файл, который клиент привяжет к серверу. Расширение запустит `eidos-lsp` при активации.

**vscode-lsp-generic:** откройте `.md` / `plaintext` / `yaml` — по вашему `documentSelector`.

### Шаг 5. Проверить, что сервер жив

1. `View` → **Output** (Вывод).
2. В выпадающем списке справа найдите канал вроде **glspc** / **LSP** / **Eidos** (зависит от расширения).
3. Не должно быть ошибок «failed to spawn» / «NotFound».

Повторно в терминале:

```bash
/home/user/Logos/logos-rs/target/debug/eidos-lsp --info
```

### Шаг 6. Вызвать команды Эйдос

`Ctrl+Shift+P` → **Execute Command** (Выполнить команду).

Ищите (после подключения LSP):

- `eidos.sessionList`
- `eidos.contextPreview`
- `eidos.memorySearch`

Если списка нет — клиент ещё не поднял сервер (вернитесь к шагу 4) или расширение не проксирует server commands (попробуйте другой вариант A/B).

Результат команды часто виден в **Output → LSP** или в уведомлении; для `sessionList`/`contextPreview` это JSON.

**memorySearch** с фильтром: в расширениях, которые позволяют аргументы, передайте строку; иначе вызовите без аргумента — вернётся список journal.

### Шаг 7. После пересборки Rust

```bash
cargo build -p eidos-lsp
```

Перезагрузите окно редактора (`Reload Window`). Путь к бинарнику не меняется, если не переключали `release`/`debug`.

---

## Частые проблемы

| Симптом | Что сделать |
|--------|-------------|
| **Connection closed / Server will restart** (4 раза) | 1) Пересобрать: `cd logos-rs && cargo build -p eidos-lsp` (бинарник в `logos-rs/target/debug/`). 2) **Reload Window**. 3) `glspc.serverPath` → этот бинарник. Частая причина: glspc передаёт **`--stdio`**, старый бинарник падал с exit 2. 4) Workspace = корень **Logos** (`eidos.py`). |
| `repo root not found` | То же: корень Logos или `LOGOS_REPO_ROOT`; после v0.1.1 пути берутся из `rootUri` при initialize. |
| `failed to spawn` | `chmod +x logos-rs/scripts/eidos-lsp.sh`; путь Linux в WSL, не `C:\` |
| Команд нет в палитре | Сервер не запущен (шаг 4); установить glspc |
| glspc только Plain Text | Открыть `.txt` или язык **Plain Text** |
| Cursor ≠ VS Code | Расширения те же; settings.json тот же формат |

## Режимы бинарника

```bash
cargo run -p eidos-lsp -- --info   # пути + команды, без LSP
cargo run -p eidos-lsp             # stdio LSP (так запускает расширение)
```

## Связанные документы

- [docs/MIGRATION_RUST_TAURI.md](../../../docs/MIGRATION_RUST_TAURI.md) — фаза 6
- [eidos-lsp.example.jsonc](./eidos-lsp.example.jsonc) — копипаста настроек
