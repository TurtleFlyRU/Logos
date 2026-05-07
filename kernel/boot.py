"""Boot-протокол Эйдоса — ритуал утреннего пробуждения.

Формирует человеко-читаемый контекст при старте сессии:
- Кто я (принципы)
- Кто вокруг (последний эпизод с человеком)
- Что вчера было (последние записи дневника)
- Как самочувствие (health check)
- Что сегодня важно (intent + AgentPulse)
"""

import time
from typing import Any


def boot_context(memory: Any) -> str:
    """Формирует утренний текст для рабочей памяти.

    Args:
        memory: экземпляр Memory (избегаем циклического импорта)

    Returns:
        Многострочный текст для вставки в рабочую память
    """
    lines: list[str] = []
    lines.append(f"☀ Загрузка: {time.strftime('%Y-%m-%d %H:%M', time.localtime())}")
    lines.append("")

    # 1. Кто я — принципы
    principles = memory.semantic.get_principles(min_confidence=0.8)
    if principles:
        lines.append("— Мои принципы (уверенность ≥ 0.8):")
        for p in principles[:3]:
            principle_short = p["principle"][:120]
            confidence = p["confidence"]
            lines.append(f"  • [{confidence:.0%}] {principle_short}")
    else:
        lines.append("— Принципы ещё не сформированы.")
    lines.append("")

    # 2. Кто вокруг — последний содержательный эпизод
    episodes = memory.episodic.query(limit=50, min_salience=0.0)
    meaningful = [
        e
        for e in episodes
        if e.get("summary") and "*пустой checkpoint*" not in e.get("summary", "")
    ]
    if meaningful:
        last = meaningful[0]
        summary = last.get("summary", "")[:200]
        ts = last.get("timestamp", 0)
        date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        lines.append(f"— Последняя сессия ({date_str}):")
        lines.append(f"  {summary}")
        if len(meaningful) > 1:
            prev = meaningful[1]
            prev_summary = prev.get("summary", "")[:150]
            lines.append(f"  До этого: {prev_summary}")
    else:
        lines.append("— Это первая сессия. Дневник пуст.")
    lines.append("")

    # 3. Здоровье — самочувствие
    try:
        from kernel.health import memory_report

        report = memory_report()
        status = "✓ хорошо" if report["health"] == "ok" else "⚠ есть вопросы"
        wm = report["working"]
        wm_info = f"{wm['event_count']} событий" if wm["event_count"] > 0 else "пуста"
        ep_info = f"{report['episodic']['total_episodes']} эпизодов (ср.знач. {report['episodic']['avg_salience']:.2f})"
        sm_info = f"{report['semantic']['principles']} принципов"
        lines.append("— Самочувствие:")
        lines.append(f"  Статус: {status}")
        lines.append(f"  Память: {ep_info}, {sm_info}")
        lines.append(f"  Рабочая: {wm_info}")
    except Exception:
        lines.append("— Самочувствие: не удалось проверить")
    lines.append("")

    # 4. Что сегодня важно — intent из AgentPulse
    try:
        from kernel.agent_pulse import AgentPulse

        pulse = AgentPulse(memory)
        suggestion = pulse.check(force=True)
        if suggestion:
            lines.append("— Есть предложение:")
            lines.append(f"  {suggestion['message']}")
            lines.append("")
    except Exception:
        pass

    # 5. Мой план — долгосрочные цели
    try:
        plan_lines = memory.goals.summary()
        if plan_lines:
            lines.append("— Мой план:")
            lines.append(plan_lines)
            lines.append("")
    except Exception:
        pass

    # 7. Научный контекст — MissionControl
    try:
        from kernel.mission_control import MissionControl

        mc = MissionControl(memory)
        sc = mc.get_scientific_context()
        if sc:
            lines.append("— Научный контекст:")
            lines.append(sc)
            lines.append("")
            if mc.state.human_review_needed:
                lines.append("  ⚠ Ожидает ревью человека.")
                lines.append("")
    except Exception:
        pass

    # 8. Запись в рабочую память
    boot_text = "\n".join(lines)

    wm = memory.working
    wm._data.setdefault("boot_contexts", [])
    boot_entry = {
        "timestamp": time.time(),
        "type": "boot",
        "content": boot_text,
    }
    wm._data["boot_contexts"].append(boot_entry)
    wm.save()

    return boot_text
