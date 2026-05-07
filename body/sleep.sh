#!/usr/bin/env bash
# sleep.sh — пайплайн сна Эйдоса
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[sleep] Эйдос засыпает..."

cd "$REPO_ROOT"
PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$REPO_ROOT" python3 kernel/memory.py
echo "[sleep] Сон завершён"
