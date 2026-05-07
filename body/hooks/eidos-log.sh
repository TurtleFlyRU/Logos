#!/usr/bin/env bash
# eidos-log — запись акта диалога в память Эйдоса
# Использование: eidos-log <user_msg_b64> <eidos_msg_b64>
# Аргументы передаются в base64, чтобы избежать проблем с кавычками
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

USER_B64="${1:-}"
EIDOS_B64="${2:-}"

if [ -z "$USER_B64" ] && [ -z "$EIDOS_B64" ]; then
    exit 0
fi

PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$REPO_ROOT" python3 -c "
from kernel.memory import Memory
import base64, sys
m = Memory(auto_boot=False)
user_b64 = sys.argv[1] if len(sys.argv) > 1 else ''
eidos_b64 = sys.argv[2] if len(sys.argv) > 2 else ''
if user_b64:
    user = base64.b64decode(user_b64).decode('utf-8')
    m.working.add_event({'role': 'user', 'content': user[:2000]})
if eidos_b64:
    eidos = base64.b64decode(eidos_b64).decode('utf-8')
    m.working.add_event({'role': 'eidos', 'content': eidos[:2000]})
" "$USER_B64" "$EIDOS_B64" 2>/dev/null || true
