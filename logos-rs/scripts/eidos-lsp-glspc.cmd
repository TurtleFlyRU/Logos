@echo off
REM Cursor/VS Code на Windows (без Remote-WSL): запуск LSP внутри WSL.
REM Путь к дистрибутиву WSL — при необходимости замените Ubuntu на имя из `wsl -l`.
wsl.exe -d Ubuntu -e /home/user/Logos/logos-rs/target/debug/eidos-lsp --stdio %*
