"""Boot-протокол Эйдоса — ритуал утреннего пробуждения.

Формирует контекст с бюджетом ~25% от контекстного окна (≈31K токенов).
Приоритет: последние события → эпизоды по recency → семантические принципы.
"""

import json
import re
import time
from typing import Any

from kernel.config import SLEEP_LAST_WORDS_PATH

# Бюджет: ~31 000 токенов ≈ ~120 000 символов (1 токен ≈ 4 символа для русского)
MAX_BOOT_CHARS = 120_000
# Резерв под мета-информацию (принципы, health, pulse, цели)
META_BUDGET = 5_000
# Какой процент хронологического окна грузить ПОЛНОСТЬЮ (последние N% диалогов)
RECENT_WINDOW_PERCENT = 25


def _cue_words(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return [word.lower() for word in re.findall(r"[\wА-Яа-яЁё-]{3,}", text)[:40]]


def _count_tokens(text: str) -> int:
    """Грубая оценка токенов: 1 токен ≈ 4 символа."""
    return len(text) // 4


def boot_context(memory: Any) -> str:
    """Формирует утренний текст для рабочей памяти.

    Args:
        memory: экземпляр Memory (избегаем циклического импорта)

    Returns:
        Многострочный текст для вставки в рабочую память
    """
    lines: list[str] = []
    meta_lines: list[str] = []
    boot_cues: list[str] = []
    now = time.time()
    seconds_in_day = 86400

    lines.append(f"☀ Загрузка: {time.strftime('%Y-%m-%d %H:%M', time.localtime())}")
    lines.append("")

    # ── Шаг 0: последние слова перед сном (всегда) ────────────
    if SLEEP_LAST_WORDS_PATH.exists():
        try:
            lw = json.loads(SLEEP_LAST_WORDS_PATH.read_text())
            events = lw.get("events", [])
            if events:
                lines.append("— Последнее перед сном:")
                for e in events[-5:]:
                    role = e.get("role", "?")
                    content = str(e.get("content", e.get("message", "")))[:300]
                    boot_cues.extend(_cue_words(content))
                    lines.append(f"  [{role}] {content}")
                lines.append("")
        except Exception:
            pass

    # ── Шаг 0.5: активные слоты внимания ──────────────────────
    wm_data = getattr(memory.working, "_data", {}) or {}
    attention_slots = wm_data.get("attention_slots", [])
    if attention_slots:
        lines.append("— В фокусе внимания:")
        for slot in attention_slots[-4:]:
            summary = str(slot.get("summary", ""))[:240]
            role = slot.get("role", "event")
            boot_cues.extend(_cue_words(summary))
            lines.append(f"  [{role}] {summary}")
        lines.append("")

    boot_cues.extend(_cue_words(wm_data.get("context", {})))

    # ── Шаг 1: эпизодическая память по хронологическому окну ─
    episodes = memory.episodic.query(limit=200, min_salience=0.0)
    cue_matches: list[dict[str, Any]] = []
    if boot_cues and hasattr(memory.episodic, "recall_by_cues"):
        try:
            recalled = memory.episodic.recall_by_cues(boot_cues, limit=20)
            if isinstance(recalled, list):
                cue_matches = recalled
        except Exception:
            cue_matches = []
    if cue_matches:
        by_id: dict[Any, dict[str, Any]] = {}
        for episode in [*cue_matches, *episodes]:
            by_id.setdefault(episode.get("id", id(episode)), episode)
        episodes = list(by_id.values())
    meaningful = [
        e
        for e in episodes
        if e.get("raw_text") and "*пустой checkpoint*" not in e.get("summary", "")
    ]

    if meaningful:
        ts_list = sorted(
            [e.get("timestamp", 0) for e in meaningful if e.get("timestamp")]
        )
        if ts_list:
            earliest = ts_list[0]
            latest = ts_list[-1]
            span = latest - earliest
            # Окно: последние RECENT_WINDOW_PERCENT% времени
            cutoff = latest - span * RECENT_WINDOW_PERCENT / 100.0
        else:
            cutoff = now

        full_lines: list[str] = []
        summary_lines: list[str] = []
        full_chars = 0
        summary_chars = 0
        ep_budget = MAX_BOOT_CHARS - META_BUDGET

        # Сортируем от новых к старым
        meaningful_sorted = sorted(
            meaningful, key=lambda e: e.get("timestamp", 0), reverse=True
        )

        for ep in meaningful_sorted:
            ts = ep.get("timestamp", 0)
            date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            summary = ep.get("summary", "") or ""

            if ts >= cutoff and ep.get("raw_text"):
                raw = ep.get("raw_text", "") or ""
                entry = f"  [{date_str}]\n{raw[:2000]}"
            else:
                entry = f"  [{date_str}] {summary[:300]}"

            entry += "\n"
            if full_chars + len(entry) > ep_budget:
                break

            if ts >= cutoff:
                full_lines.append(entry)
            else:
                summary_lines.append(entry)
            full_chars += len(entry)

        if full_lines:
            lines.append(
                f"— Последние {RECENT_WINDOW_PERCENT}% хронологии ({len(full_lines)} эпизодов):"
            )
            lines.append("")
            lines.extend(full_lines)
            lines.append("")

        if summary_lines:
            cnt = len(summary_lines)
            lines.append(f"— Остальные эпизоды ({cnt}, кратко):")
            lines.append("")
            lines.extend(summary_lines)
            lines.append("")

    # ── Шаг 2: мета-информация (считаем токены, укладываемся) ─
    meta_chars = 0

    # Принципы
    principles = memory.semantic.get_principles(min_confidence=0.7)
    if principles:
        meta_lines.append("— Мои принципы:")
        for p in principles[:5]:
            p_short = p["principle"][:150]
            conf = p["confidence"]
            meta_lines.append(f"  • [{conf:.0%}] {p_short}")
        meta_lines.append("")

    # Здоровье
    try:
        from kernel.health import memory_report
        report = memory_report()
        status = "✓ хорошо" if report["health"] == "ok" else "⚠ есть вопросы"
        wm_info = f"{report['working']['event_count']} событий" if report['working']['event_count'] > 0 else "пуста"
        ep_info = f"{report['episodic']['total_episodes']} эпизодов"
        sm_info = f"{report['semantic']['principles']} принципов"
        meta_lines.append("— Самочувствие:")
        meta_lines.append(f"  Статус: {status}")
        meta_lines.append(f"  Память: {ep_info}, {sm_info}")
        meta_lines.append(f"  Рабочая: {wm_info}")
        meta_lines.append("")
    except Exception:
        meta_lines.append("— Самочувствие: не удалось проверить\n")

    # AgentPulse
    try:
        from kernel.agent_pulse import AgentPulse
        pulse = AgentPulse(memory)
        suggestion = pulse.check(force=True)
        if suggestion:
            meta_lines.append("— Есть предложение:")
            meta_lines.append(f"  {suggestion['message']}")
            meta_lines.append("")
    except Exception:
        pass

    # Цели
    try:
        plan_lines = memory.goals.summary()
        if plan_lines:
            meta_lines.append("— Мой план:")
            meta_lines.append(plan_lines)
            meta_lines.append("")
    except Exception:
        pass

    # MissionControl
    try:
        from kernel.mission_control import MissionControl
        mc = MissionControl(memory)
        sc = mc.get_scientific_context()
        if sc:
            meta_lines.append("— Научный контекст:")
            meta_lines.append(sc)
            meta_lines.append("")
            if mc.state.human_review_needed:
                meta_lines.append("  ⚠ Ожидает ревью человека.")
                meta_lines.append("")
    except Exception:
        pass

    # Усекаем мета-информацию если не влезает
    meta_final: list[str] = []
    for line in meta_lines:
        if meta_chars + len(line) > META_BUDGET:
            meta_final.append(f"  ... (мета обрезано по бюджету {META_BUDGET} символов)")
            break
        meta_final.append(line)
        meta_chars += len(line)

    lines.extend(meta_final)

    # ── Финальная сборка ──────────────────────────────────────
    boot_text = "\n".join(lines)

    # Обрезаем по бюджету если всё ещё не влезаем
    if len(boot_text) > MAX_BOOT_CHARS:
        boot_text = boot_text[:MAX_BOOT_CHARS] + "\n... (контекст обрезан по бюджету)"

    # Запись в рабочую память
    wm = memory.working
    wm._data.setdefault("boot_contexts", [])
    tokens_est = _count_tokens(boot_text)
    boot_entry: dict[str, Any] = {
        "timestamp": time.time(),
        "type": "boot",
        "content": boot_text,
        "tokens_estimate": tokens_est,
        "budget_limit": MAX_BOOT_CHARS // 4,
    }
    wm._data["boot_contexts"].append(boot_entry)
    wm.save()

    return boot_text
