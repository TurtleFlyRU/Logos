"""Тестовый набор запросов для оценки сложности и сигнала бюджета."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
# Прямой импорт через path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from budget import ComplexityScorer, BudgetSignal  # type: ignore[import-untyped]


TEST_QUERIES = [
    {
        "query": "привет",
        "files": 0,
        "expected_level": "low",
    },
    {
        "query": "как работает память?",
        "files": 0,
        "expected_level": "low",
    },
    {
        "query": "найди в дневнике все записи про архитектуру памяти",
        "files": 1,
        "expected_level": "medium",
    },
    {
        "query": "сравни подходы к иерархической памяти в experiment 001 и текущей архитектуре",
        "files": 2,
        "expected_level": "high",
    },
    {
        "query": "проанализируй принципы из семантической памяти, спланируй рефакторинг architecture памяти, сравни с экспериментом 001 и 002, выведи обобщённый паттерн",
        "files": 3,
        "expected_level": "critical",
    },
]


def run():
    scorer = ComplexityScorer()
    signal = BudgetSignal(scorer)

    results = []
    print(f"{'Запрос':<55} {'Score':<8} {'Level':<10} {'Expansion':<10}")
    print("-" * 85)
    for t in TEST_QUERIES:
        r = signal.evaluate(t["query"], t["files"])
        match = "✓" if r["complexity"]["level"] == t["expected_level"] else "✗"
        print(f"{t['query'][:52]+'...'if len(t['query'])>52 else t['query']:<55} "
              f"{r['complexity']['score']:<8} {r['complexity']['level']:<10} "
              f"{r['needs_expansion']:<10} {match}")
        results.append({
            "query": t["query"],
            "files": t["files"],
            "expected_level": t["expected_level"],
            "actual": r["complexity"],
            "needs_expansion": r["needs_expansion"],
            "recommendation": r["recommendation"],
        })

    # Сохраняем
    out_path = Path(__file__).resolve().parent.parent / "results" / "budget_metrics.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nРезультаты сохранены в {out_path}")


if __name__ == "__main__":
    run()
