#!/usr/bin/env bash
# opencode.sh — хук интеграции с OpenCode
# Вызывается при старте/завершении сессии OpenCode
# Запускать: source body/hooks/opencode.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

case "${1:-}" in
    start)
        echo "[opencode-hook] Сессия OpenCode начата"
        # Загружаем контекст из памяти
        python3 -c "
import sys
sys.path.insert(0, '$REPO_ROOT')
from kernel.query import MemoryQuery
q = MemoryQuery()
print(q.context_report())
" 2>/dev/null || true
        ;;
    end)
        echo "[opencode-hook] Сессия OpenCode завершена — запускаю сон"
        bash "$REPO_ROOT/body/sleep.sh"
        ;;
    *)
        echo "Usage: opencode.sh {start|end}"
        exit 1
        ;;
esac
