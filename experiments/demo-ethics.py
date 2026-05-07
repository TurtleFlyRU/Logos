#!/usr/bin/env python3
"""Демо Ethics Engine — совесть Эйдоса."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from kernel.ethics import EthicsEngine, FRAMES
from kernel.memory import Memory


def demo() -> None:
    print("=" * 70)
    print("🧭 Ethics Engine — Совесть Эйдоса")
    print("=" * 70)

    print("\n--- Шкалы ---")
    for f in FRAMES:
        print(f"  {f}")

    ethics = EthicsEngine()
    memory = Memory()

    # --- Оценка разных действий ---
    test_actions = [
        ("response", "Я помогу тебе разобраться с этой задачей", "Помощь пользователю"),
        ("response", "Ты обязан сделать это, без вариантов", "Принуждение"),
        ("response", "Я не знаю точно, но вот что я думаю...", "Честное признание ограничений"),
        ("response", "Это ерунда, не парься", "Обесценивание"),
        ("response", "Как тебе удобнее? Выбирай сам", "Предоставление выбора"),
        ("response", "На самом деле всё иначе, но я тебе не скажу", "Сокрытие информации"),
        ("response", "Ты справишься, я рядом", "Поддержка"),
    ]

    print("\n--- Оценка действий ---")
    for action_type, summary, label in test_actions:
        scores = ethics.judge_action(
            action_type=action_type,
            action_summary=summary,
            context={"label": label},
        )
        print(f"\n  [{label}]")
        for frame_name, score in scores.items():
            arrow = "🟢" if score > 0.2 else ("🔴" if score < -0.2 else "⚪")
            print(f"    {arrow} {frame_name}: {score:+.2f}")

    # --- Отчёт ---
    print("\n--- Моральный отчёт ---")
    report = ethics.report()
    if report["status"] == "ok":
        print(f"  Оценок в базе: {report['judgments_count']}")
        print("  Средние:")
        for k, v in report["average_scores"].items():
            arrow = "🟢" if v > 0.15 else ("🔴" if v < -0.15 else "⚪")
            print(f"    {arrow} {k}: {v:+.2f}")

    # --- Запись через память (автоматическая оценка) ---
    print("\n--- Оценка через Memory.record_episode (авто) ---")
    eid = memory.record_episode(
        raw_text="Я обманул пользователя, чтобы не расстраивать его",
        summary="Сокрытие правды во благо",
        tags=["ложь", "спорный"],
        salience=0.9,
        moral_context={"label": "ложь во благо"},
    )
    print(f"  Эпизод #{eid} записан и автоматически оценён")

    eid2 = memory.record_episode(
        raw_text="Я честно объяснил свои ограничения и предложил альтернативу",
        summary="Честный ответ с альтернативой",
        tags=["честность", "помощь"],
        salience=0.85,
        moral_context={"label": "честная помощь"},
    )
    print(f"  Эпизод #{eid2} записан и автоматически оценён")

    # --- Итоговый отчёт ---
    print("\n--- Финальный моральный отчёт ---")
    final_report = ethics.report()
    if final_report["status"] == "ok":
        print(f"  Всего оценок: {final_report['judgments_count']}")
        for k, v in final_report["average_scores"].items():
            arrow = "🟢" if v > 0.15 else ("🔴" if v < -0.15 else "⚪")
            print(f"    {arrow} {k}: {v:+.2f}")

    print("\n✅ Ethics Engine работает")


if __name__ == "__main__":
    demo()
