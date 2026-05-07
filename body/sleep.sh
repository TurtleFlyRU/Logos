#!/usr/bin/env bash
# sleep.sh — пайплайн сна Эйдоса (R2: идемпотентный, с прогрессом)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[sleep] Эйдос засыпает..."

cd "$REPO_ROOT"

# Сбор данных о ходе сна через callback
python3 -c "
import sys, time
sys.path.insert(0, '$REPO_ROOT')
from kernel.memory import Memory

def progress(name, step, total):
    bar_len = 20
    filled = int(bar_len * step / total)
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f'  [{bar}] {step}/{total} — {name}', flush=True)

m = Memory()
report = m.sleep(progress_callback=progress)
print()
print(f'  Статус: {report[\"status\"]}')
print(f'  Время: {report.get(\"elapsed_seconds\", \"?\")}с')
print(f'  Эпизодов: {report.get(\"episodes_processed\", 0)}')
print(f'  Принципов: {report.get(\"promoted_to_semantic\", 0)}')
"
echo "[sleep] Сон завершён"
