"""Тестовый набор для верификации черновиков."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from verifier import Verifier


TEST_CASES = [
    {
        "query": "Какие принципы записаны в семантической памяти?",
        "draft": "В семантической памяти записаны принципы из эпизодов с высокой значимостью.",
        "note": "общий — должен найти поддержку",
    },
    {
        "query": "Как работает иерархическая память?",
        "draft": "Иерархическая память включает три уровня: рабочая, эпизодическая и семантическая. Каждый уровень имеет свою функцию.",
        "note": "факт из архитектуры — должен найти поддержку",
    },
    {
        "query": "Что Эйдос думает о философии Ницше?",
        "draft": "Эйдос считает, что сверхчеловек Ницше — это метафора AGI, а воля к власти — аналог вычислительной мощности.",
        "note": "галлюцинация — не должно быть поддержки",
    },
]


def run():
    verifier = Verifier()
    results = []

    print(f"{'Запрос':<50} {'Claims':<8} {'Issues':<8} {'Correction':<10}")
    print("-" * 80)
    for tc in TEST_CASES:
        r = verifier.verify_and_format(tc["draft"], tc["query"])
        status = "✓" if not r["needs_correction"] else "✗"
        print(f"{tc['query'][:48]:<50} {r['claims_checked']:<8} {len(r['issues']):<8} {status:<10}")
        if r["needs_correction"]:
            print(f"  ⤷ коррекция: {r['corrections'][0][:80]}")
        print(f"  ⤷ поддержка: {len(r['supporting'])} принципов, противоречий: {len(r['contradictions'])}")

        results.append({
            "query": tc["query"],
            "draft": tc["draft"],
            "note": tc["note"],
            **r,
        })

    out_path = Path(__file__).resolve().parent.parent / "results" / "verification_metrics.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nРезультаты сохранены в {out_path}")


if __name__ == "__main__":
    run()
