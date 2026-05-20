#!/usr/bin/env bash
# Лаунчер для glspc: LOGOS_REPO_ROOT + лог в /tmp (stderr), stdio не трогаем.
set -euo pipefail
LOG="${EIDOS_LSP_LOG:-/tmp/eidos-lsp-glspc.log}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BIN="${SCRIPT_DIR}/../target/debug/eidos-lsp"
{
  echo "=== $(date -Iseconds) pid=$$ pwd=$(pwd) repo=$REPO_ROOT"
  echo "argv=$*"
  echo "which=$({ command -v "$BIN"; } 2>&1 || echo MISSING)"
} >>"$LOG" 2>&1
export LOGOS_REPO_ROOT="${LOGOS_REPO_ROOT:-$REPO_ROOT}"
if [[ ! -x "$BIN" ]]; then
  echo "eidos-lsp-glspc: нет бинарника $BIN — выполните: cd logos-rs && cargo build -p eidos-lsp" >>"$LOG"
  echo "eidos-lsp-glspc: нет бинарника $BIN (см. $LOG)" >&2
  exit 1
fi
exec "$BIN" "$@"
