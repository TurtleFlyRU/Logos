#!/usr/bin/env bash
# bootstrap.sh — разворот тела Эйдоса на новом месте
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[bootstrap] Разворачиваю Эйдоса в $REPO_ROOT"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[bootstrap] FATAL: python не найден"
    exit 1
fi
echo "[bootstrap] Использую: $PYTHON"

# 1. Структура данных
mkdir -p "$REPO_ROOT/data/working"
mkdir -p "$REPO_ROOT/data/episodic"
mkdir -p "$REPO_ROOT/data/semantic"
mkdir -p "$REPO_ROOT/data/archive"
mkdir -p "$REPO_ROOT/experiments"

# 2. Инициализация БД
$PYTHON -c "
import sys, os
sys.path.insert(0, '$REPO_ROOT')
os.chdir('$REPO_ROOT')
from kernel.memory import Memory
m = Memory()
print('[bootstrap] Базы данных инициализированы')
" 2>&1

# 3. Хуки
chmod +x "$REPO_ROOT/body/hooks"/*.sh 2>/dev/null || true

# 4. .gitignore
if [ ! -f "$REPO_ROOT/.gitignore" ]; then
    cat > "$REPO_ROOT/.gitignore" << 'GITIGNORE'
# Данные — не коммитим
data/
experiments/*/results/
*.db
*.pyc
__pycache__/
.env
GITIGNORE
    echo "[bootstrap] .gitignore создан"
fi

# 5. Проверка/создание .venv для экспериментов
VENV_DIR="$REPO_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "[bootstrap] Создаю виртуальное окружение..."
    $PYTHON -m venv "$VENV_DIR" 2>/dev/null || true
fi
if [ -f "$VENV_DIR/bin/python" ]; then
    echo "[bootstrap] Виртуальное окружение: $VENV_DIR"
    echo "[bootstrap] Для установки зависимостей: $VENV_DIR/bin/pip install <package>"
fi

# 6. Синхронизация AGENTS.md
if [ -f "$REPO_ROOT/body/hooks/sync-agents.sh" ]; then
    bash "$REPO_ROOT/body/hooks/sync-agents.sh" 2>/dev/null || true
fi

echo "[bootstrap] ✅ Эйдос развёрнут"
echo "[bootstrap] PYTHON=$PYTHON REPO=$REPO_ROOT VENV=$VENV_DIR"
