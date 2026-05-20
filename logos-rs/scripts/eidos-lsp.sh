#!/usr/bin/env bash
# Обёртка для glspc/Cursor: задаёт LOGOS_REPO_ROOT, даже если cwd расширения «не тот».
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export LOGOS_REPO_ROOT="${LOGOS_REPO_ROOT:-$REPO_ROOT}"
BIN="${SCRIPT_DIR}/../target/debug/eidos-lsp"
if [[ ! -x "$BIN" ]]; then
  BIN="${SCRIPT_DIR}/../target/release/eidos-lsp"
fi
exec "$BIN" "$@"
