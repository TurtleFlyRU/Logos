# Eidos Desktop (Tauri 2) — фаза 3 ✅

Окно чата поверх `eidos-core` + Python sidecar (тот же стек, что `eidos chat`). Статус миграции: [docs/MIGRATION_RUST_TAURI.md](../../../docs/MIGRATION_RUST_TAURI.md) (фаза 3 закрыта).

## Зависимости Linux / WSL

```bash
sudo apt update
sudo apt install -y pkg-config libwebkit2gtk-4.1-dev build-essential \
  libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

Для WSL2 нужен **WSLg** (GUI) или запуск X-сервера на Windows.

### Предупреждения EGL / MESA в терминале

Строки вида `libEGL warning`, `MESA-LOADER`, `ZINK` на Linux/WSL часто **безвредны**: WebKitGTK/WebGL пробует драйвер, в WSL это нормально. Если окно и чат работают — можно игнорировать.

### Потоковый вывод в чате

- Пока модель выполняет **инструменты** (tool round), в ленту новые сообщения попадают только **после завершения хода**: дельты стрима и полная история синхронизируются с WM в конце. Во время ожидания остаётся **«Запрос к модели…»** и пузырь ассистента с **«…»**, чтобы не казалось, что UI завис.
- Вставка текста по дельтам **батчится через `requestAnimationFrame`** (не чаще одного кадра) — меньше нагрузка на WebKit, удобнее на WSL.
- После раунда **инструментов** ответ приходит одним HTTP-ответом, затем в UI воспроизводится по чанкам. Чтобы буквы шли поэтапно, в desktop по умолчанию `EIDOS_STREAM_REPLAY_MS=6`. Мгновенно: `EIDOS_STREAM_REPLAY_MS=0`.
- Чистый **SSE** без tools зависит от API: часть локальных серверов шлёт весь текст одним событием.

### Русский ввод в поле чата (WSL / Linux)

WebKitGTK иногда **не получает кириллицу от IBUS**:

**Вариант A — IBUS (часто помогает):**

```bash
sudo apt install -y ibus ibus-gtk3
export GTK_IM_MODULE=ibus
export XMODIFIERS=@im=ibus
export LANG=ru_RU.UTF-8
ibus-daemon -drx
cd logos-rs/apps/eidos-desktop && npm run tauri dev
```

**Вариант B — fcitx5:**

```bash
sudo apt install -y fcitx5 fcitx5-gtk
export GTK_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
```

**Вариант C — обход:** набрать текст в другом окне и **Ctrl+V** в поле чата (вставка работает).

**Вариант D:** запускать desktop **на Windows** (не в WSL): `npm run tauri dev` из PowerShell в том же репозитории.

CLI `cargo run -p eidos-cli -- chat` в терминале WSL русский ввод обычно работает без этих настроек.

## Запуск

Из корня репозитория Logos:

```bash
# Ключ DeepSeek (один раз): cp .env.example .env и вставьте DEEPSEEK_API_KEY
# По умолчанию профиль deepseek из config/agents.defaults.yaml

cd logos-rs/apps/eidos-desktop
npm install
npm run tauri dev
```

Заглушка без LLM: `EIDOS_DESKTOP_STUB=1 npm run tauri dev`

## UI

**Работает (как CLI + sidecar):**

- Чат: user / assistant / tool-сообщения из WM; **стриминг** ответа (события `chat-stream-*`, после хода — полная история с tool)
- LLM + инструменты (`EIDOS_TOOLS=1`), identity, полный контекст Python
- Пайплайны в поле ввода: `/pipeline research …`, `/run`, `/review`
- Кнопки и slash: **Env**, **Контекст** (слои + `/budget`), **Пайплайны**, **Boot**, **Сон**, **Настройки**, **Новая сессия**
- **Сон** — `python3 eidos.py sleep` (опционально `--force` при втором подтверждении)
- **Настройки** — профиль LLM, пути, флаги окружения (без API-ключей)
- Кнопка **agents** — правка `agents.yaml`: читается тот же файл, что у рантайма; перед записью проверяется разбор YAML (структура как у `eidos-protocol::AgentsConfig`). Сохранение в `data/config/agents.yaml` (или в путь из `EIDOS_AGENTS_CONFIG`, если он внутри repo/data). Параметры LLM для чата читаются с диска на каждый ход — перезапуск не обязателен; после «Сохранить» шапка (профиль/модель) обновляется.
- Список сессий, переключение, общий `data/working/current.json` с CLI
- Профиль в шапке (имя, модель; путь к `agents.yaml` в tooltip)

**Переменные (опционально):** `EIDOS_AGENT_PROFILE` (другой профиль), `EIDOS_DESKTOP_STUB=1`, `EIDOS_TOOLS=1` (инструменты как в CLI). **Playwright** (`browser_*`) по умолчанию **вкл.**; выключить: `EIDOS_PLAYWRIGHT=0`. Нужен долгоживущий sidecar (в desktop по умолчанию); при `EIDOS_RUST_NO_SIDECAR=1` контекст браузера между вызовами не сохранится.

**CLI:** `EIDOS_STREAM=1 cargo run -p eidos-cli -- chat` — дельты в stdout.

**Следующие шаги (фаза 4+):** подсветка синтаксиса YAML; углублённый UI бюджета.

## DoD фазы 3 (чеклист)

- Один репозиторий `Logos`: `cd logos-rs/apps/eidos-desktop && npm run tauri dev`.
- `.env` в корне репо с `DEEPSEEK_API_KEY` / `LLM_API_KEY` (см. `.env.example`); профиль **deepseek** по умолчанию из `config/agents.defaults.yaml`.
- Чат, сессии, boot, Env, Контекст (слои + `/budget`), пайплайны, стриминг ответа, Сон, Настройки.
- При **100% диска**: `cd logos-rs && cargo clean` перед сборкой.

## Частые проблемы

| Симптом | Действие |
|--------|-----------|
| `No space left on device` при `rustc` | `cargo clean` в `logos-rs/`, освободить `/` |
| Пустой или обнулённый `src-tauri/src/lib.rs` | Восстановить из git / бэкапа; файл не должен быть 0 bytes |
| Ошибки sidecar | Запуск из корня `Logos` (или `LOGOS_REPO_ROOT`); `python3` и `PYTHONPATH` как у `eidos.py` |
| Кириллица не вводится (WSL) | Раздел «Русский ввод» выше или запуск desktop на Windows |
