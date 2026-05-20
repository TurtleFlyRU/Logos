#!/usr/bin/env bash
# Правильный запуск desktop: Vite на :1420 + окно Tauri (всегда свежий src/).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [[ ! -d node_modules ]]; then
  npm install
fi
echo "[eidos-desktop] Запуск: npm run tauri dev (UI из Vite, не из старого бинарника)"
exec npm run tauri dev
