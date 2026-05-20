#!/usr/bin/env bash
# Запуск вшитого UI: сначала пересобрать фронт и Rust, иначе изменений не будет.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGOS_RS="$(cd "$ROOT/../.." && pwd)"
cd "$ROOT"
npm run build
cd "$LOGOS_RS"
cargo build -p eidos-desktop
echo "[eidos-desktop] Запуск target/debug/eidos-desktop (UI из dist/, только что собран)"
exec "$LOGOS_RS/target/debug/eidos-desktop"
