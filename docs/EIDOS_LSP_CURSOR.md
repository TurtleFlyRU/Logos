# eidos-lsp + Cursor / VS Code (glspc)

## Симптом: Connection closed ×4

Почти всегда одно из:

1. **Cursor на Windows**, папка в WSL, а `glspc` пытается запустить **Linux-бинарник с Windows** → мгновенный обрыв.
2. В `glspc.serverPath` остался **`${workspaceFolder}/...`**, а расширение подставило путь, который не существует для spawn.
3. Старый бинарник без флага **`--stdio`** (исправлено; нужен `cargo build -p eidos-lsp`).

## Рекомендуемый способ (WSL)

1. В терминале WSL: `cd ~/Logos && cursor .`  
   (или VS Code: **Remote-WSL: Open Folder in WSL**).
2. Убедиться, что в статус-баре есть **WSL: Ubuntu** (или ваш дистрибутив), не «голый» Windows.
3. Сборка:
   ```bash
   cd ~/Logos/logos-rs && cargo build -p eidos-lsp
   ```
4. В `.vscode/settings.json` уже задано:
   ```json
   "glspc.serverPath": "/home/user/Logos/logos-rs/scripts/eidos-lsp-glspc.sh",
   "glspc.trace.server": "off"
   ```
   При другом пути к репо замените **`/home/user/Logos`** на свой.
5. `chmod +x logos-rs/scripts/eidos-lsp-glspc.sh`
6. **Developer: Reload Window**
7. Открыть файл с языком **Plain Text** (для glspc).
8. Output → выбрать **glspc** / **Generic LSP Client** — смотреть stderr (`eidos-lsp: start pid=...`).

## Диагностика после неудачного старта

```bash
cat /tmp/eidos-lsp-glspc.log
```

Там будут `argv=`, `pwd=`, `MISSING` если бинарник не собран.

## Cursor только на Windows (без Remote-WSL)

В `glspc.serverPath` укажите **`.cmd`** (путь Windows), например:

`\\wsl.localhost\Ubuntu\home\user\Logos\logos-rs\scripts\eidos-lsp-glspc.cmd`

или скопируйте `logos-rs/scripts/eidos-lsp-glspc.cmd` и поправьте дистрибутив в `wsl.exe -d Ubuntu`.

Надёжнее всё же открыть проект **из WSL** (`cursor .` в `~/Logos`).

## Проверка вручную (WSL)

```bash
/home/user/Logos/logos-rs/target/debug/eidos-lsp --stdio --help
/home/user/Logos/logos-rs/scripts/eidos-lsp-glspc.sh --info
```
