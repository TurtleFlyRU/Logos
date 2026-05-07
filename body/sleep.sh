#!/usr/bin/env bash
# sleep.sh — пайплайн сна Эйдоса
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[sleep] 🌀 Эйдос засыпает..."

# Запуск sleep-пайплайна
python3 "$REPO_ROOT/kernel/memory.py" 2>/dev/null || python "$REPO_ROOT/kernel/memory.py" 2>/dev/null || {
    # Если не сработало как скрипт — запускаем через -c
    python3 -c "
import sys
sys.path.insert(0, '$REPO_ROOT')
from kernel.memory import Memory
m = Memory()
report = m.sleep()
print(f'[sleep] Обработано эпизодов: {report[\"episodes_processed\"]}')
print(f'[sleep] Извлечено принципов: {report[\"principles_extracted\"]}')
print('[sleep] ✅ Сон завершён')
" 2>/dev/null || python -c "
import sys
sys.path.insert(0, '$REPO_ROOT')
from kernel.memory import Memory
m = Memory()
report = m.sleep()
print(f'[sleep] Обработано эпизодов: {report[\"episodes_processed\"]}')
print('[sleep] ✅ Сон завершён')
" 2>/dev/null || echo "[sleep] WARNING: сон не выполнен"
}

echo "[sleep] 🌅 Эйдос проснулся"
