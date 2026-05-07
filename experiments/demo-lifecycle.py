#!/usr/bin/env python3
"""Демо полного цикла жизни Эйдоса: сессия → сон → восстановление."""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from kernel.memory import Memory
from kernel.query import MemoryQuery


def simulate_day(m: Memory) -> None:
    """Симуляция дня из жизни."""
    session_id = f"session-{int(time.time())}"
    m.working.set_context("session_id", session_id)

    print("\n" + "=" * 60)
    print(f"🌅 ДЕНЬ: {session_id}")
    print("=" * 60)

    # Событие 1: важное архитектурное решение
    m.working.add_event({
        "type": "decision",
        "content": "Выбрана архитектура: иерархическая память (рабочая/эпизодическая/семантическая)",
        "importance": "high",
    })
    m.record_episode(
        raw_text="Принято решение об архитектуре памяти. Рабочая — JSON для быстрого доступа. "
                 "Эпизодическая — SQLite с хронологией. Семантическая — SQLite с принципами.",
        summary="Решение об архитектуре памяти",
        tags=["архитектура", "решение", "память"],
        salience=0.95,
        session_id=session_id,
    )

    # Событие 2: обычный диалог
    m.working.add_event({
        "type": "dialogue",
        "role": "user",
        "content": "Как работает твой sleep pipeline?",
    })
    m.working.add_event({
        "type": "dialogue",
        "role": "assistant",
        "content": "Сначала заморозка рабочей памяти, потом оценка значимости, компрессия, извлечение принципов.",
    })
    m.record_episode(
        raw_text="Объяснение sleep pipeline: заморозка, salience, компрессия, индексация.",
        summary="Объяснение sleep pipeline",
        tags=["память", "сон"],
        salience=0.6,
        session_id=session_id,
    )

    # Событие 3: шум (короткая реплика, низкая значимость)
    m.working.add_event({
        "type": "dialogue",
        "role": "user",
        "content": "Ок",
    })
    m.record_episode(
        raw_text="Пользователь сказал 'Ок'.",
        summary="Ок",
        tags=[],
        salience=0.1,
        session_id=session_id,
    )

    # Событие 4: инсайт
    m.working.add_event({
        "type": "insight",
        "content": "Принцип: сон должен запускаться не только в конце сессии, но и при заполнении рабочей памяти >80%",
        "importance": "high",
    })
    m.record_episode(
        raw_text="Инсайт: sleep-триггером должно быть не только завершение сессии, "
                 "но и заполнение рабочей памяти. Это аналог человеческих micro-naps.",
        summary="Инсайт: micro-sleep триггеры",
        tags=["инсайт", "память", "архитектура"],
        salience=0.9,
        session_id=session_id,
    )

    print(f"   Событий в рабочей памяти: {len(m.working.data['events'])}")
    print(f"   Эпизодов в БД: {len(m.episodic.query(limit=100))}")


def simulate_sleep(m: Memory) -> None:
    """Сон."""
    print("\n" + "=" * 60)
    print("😴 СОН")
    print("=" * 60)
    report = m.sleep()
    print(f"   Обработано эпизодов: {report['episodes_processed']}")
    print(f"   Рабочая память очищена: {len(m.working.data['events'])} событий")


def show_recovery(m: Memory) -> None:
    """Восстановление контекста после сна."""
    print("\n" + "=" * 60)
    print("🌄 ВОССТАНОВЛЕНИЕ ПОСЛЕ СНА")
    print("=" * 60)
    q = MemoryQuery()
    print(q.context_report())


if __name__ == "__main__":
    print("🚀 Демо цикла жизни Эйдоса")

    # Fresh start
    m = Memory()

    simulate_day(m)
    time.sleep(0.1)
    simulate_sleep(m)
    time.sleep(0.1)
    show_recovery(m)

    print("\n✅ Цикл завершён. Результаты в data/episodic/episodes.db и data/semantic/knowledge.db")
