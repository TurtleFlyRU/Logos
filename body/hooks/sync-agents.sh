#!/usr/bin/env bash
# sync-agents.sh — синхронизирует мастер-копию AGENTS.md с рабочей
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MASTER="$REPO_ROOT/body/AGENTS.md"
TARGET="$HOME/.config/opencode/AGENTS.md"

if [ ! -f "$MASTER" ]; then
    echo "[sync-agents] ERROR: мастер-копия не найдена: $MASTER"
    exit 1
fi

cp "$MASTER" "$TARGET"
echo "[sync-agents] ✅ AGENTS.md синхронизирован"
