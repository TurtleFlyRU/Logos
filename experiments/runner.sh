#!/usr/bin/env bash
# runner.sh — запуск эксперимента
# Использование: bash experiments/runner.sh <имя_эксперимента>
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXP_NAME="${1:-}"
EXP_DIR="$REPO_ROOT/experiments/$EXP_NAME"

if [ -z "$EXP_NAME" ]; then
    echo "Использование: bash experiments/runner.sh <имя_эксперимента>"
    echo "Доступные эксперименты:"
    ls -d "$REPO_ROOT/experiments"/*/ 2>/dev/null | while read d; do
        basename "$d"
    done
    exit 1
fi

if [ ! -d "$EXP_DIR" ]; then
    echo "❌ Эксперимент '$EXP_NAME' не найден в $EXP_DIR"
    exit 1
fi

cd "$REPO_ROOT"

echo "=" 60
echo "🔬 Запуск эксперимента: $EXP_NAME"
echo "=" 60

# 1. Чтение HYPOTHESIS.md
echo ""
echo "📋 Гипотеза:"
head -5 "$EXP_DIR/HYPOTHESIS.md" 2>/dev/null || echo "(нет HYPOTHESIS.md)"

# 2. Зависимости
DEP_FILE="$EXP_DIR/requirements.txt"
if [ -f "$DEP_FILE" ]; then
    echo ""
    echo "📦 Установка зависимостей..."
    pip3 install -r "$DEP_FILE" 2>&1 || pip install -r "$DEP_FILE" 2>&1 || true
fi

# 3. Запуск src/main.py если есть
MAIN="$EXP_DIR/src/main.py"
if [ -f "$MAIN" ]; then
    echo ""
    echo "▶️  Запуск $MAIN"
    echo ""
    python3 "$MAIN" 2>&1
    EXIT_CODE=$?
    echo ""
    if [ $EXIT_CODE -eq 0 ]; then
        echo "✅ Эксперимент завершён успешно"
    else
        echo "❌ Эксперимент завершён с ошибкой (exit code $EXIT_CODE)"
    fi
else
    echo "ℹ️  Нет src/main.py — запустите шаги вручную"
fi

# 4. Результаты
if [ -d "$EXP_DIR/results" ]; then
    RESULT_COUNT=$(find "$EXP_DIR/results" -type f 2>/dev/null | wc -l)
    echo ""
    echo "📊 Файлов результатов: $RESULT_COUNT"
    ls -la "$EXP_DIR/results/" 2>/dev/null
fi

echo ""
echo "=" 60
echo "🏁 Завершено: $EXP_NAME"
echo "=" 60
