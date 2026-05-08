"""Boot-протокол Эйдоса — ритуал утреннего пробуждения.

Формирует контекст с лимитом символов (грубо токены × 4). По умолчанию ~25K токенов.
Пайплайн вызывает отделы памяти через их API (WM-слоты, episodic.query/recall_by_cues,
semantic.get_principles, цели, instrumental, pulse и др.). Эпизоды упорядочиваются по
важности (salience, давность, теги, объём), затем укладываются в бюджет.

CLI: ``boot_context(memory, sync_opencode=False)`` — без автоматической синхронизации OpenCode.

Переменные окружения:
- ``EIDOS_BOOT_MAX_TOKENS`` — верхняя оценка токенов для всего boot-текста (4096–64000),
  по умолчанию 25000.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from kernel.config import SLEEP_LAST_WORDS_PATH

CHARS_PER_TOKEN_EST = 4
DEFAULT_BOOT_TOKEN_BUDGET = 25_000
DEFAULT_BOOT_CHARS = DEFAULT_BOOT_TOKEN_BUDGET * CHARS_PER_TOKEN_EST
MAX_BOOT_CHARS = DEFAULT_BOOT_CHARS
RECENT_WINDOW_PERCENT = 25
_BOOT_CONTEXT_HISTORY_LIMIT = 15


def _cue_words(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return [word.lower() for word in re.findall(r"[\wА-Яа-яЁё-]{3,}", text)[:40]]


def _count_tokens(text: str) -> int:
    """Грубая оценка токенов: 1 токен ≈ 4 символа."""
    return len(text) // CHARS_PER_TOKEN_EST


def resolve_boot_char_budget(max_boot_chars: int | None = None) -> int:
    """Максимальная длина строки boot в символах."""
    if max_boot_chars is not None:
        return max(10_000, min(320_000, max_boot_chars))
    raw = os.environ.get("EIDOS_BOOT_MAX_TOKENS", "").strip()
    if raw.isdigit():
        tokens = int(raw)
    else:
        tokens = DEFAULT_BOOT_TOKEN_BUDGET
    tokens = max(4096, min(64_000, tokens))
    return tokens * CHARS_PER_TOKEN_EST


def _meta_budget_chars(total_budget: int) -> int:
    return max(3000, min(12_000, total_budget // 18))


def _episode_tags_list(ep: dict[str, Any]) -> list[str]:
    raw = ep.get("tags")
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            pass
    return []


def _episode_priority(ep: dict[str, Any], *, latest_ts: float) -> float:
    salience = float(ep.get("salience") or 0)
    ts = float(ep.get("timestamp") or 0)
    age_sec = max(0.0, latest_ts - ts)
    recency = 1.0 / (1.0 + age_sec / (3600 * 24))
    bonus = 0.0
    tags_lower = [t.lower() for t in _episode_tags_list(ep)]
    boosts = (
        "ошибка",
        "решение",
        "архитектура",
        "kernel",
        "cli",
        "eidos",
        "sleep",
        "миссия",
        "experiment",
        "исследование",
        "план",
    )
    for t in tags_lower:
        if any(b in t for b in boosts):
            bonus += 0.12
        if "cli" in t or "eidos" in t:
            bonus += 0.06
    raw_len = len(str(ep.get("raw_text") or ""))
    size_bonus = min(0.22, raw_len / 6000.0)
    return salience * 0.48 + recency * 0.34 + bonus + size_bonus


def boot_context(
    memory: Any,
    *,
    sync_opencode: bool = True,
    max_boot_chars: int | None = None,
    persist_boot_context: bool = True,
) -> str:
    """Формирует утренний текст и сохраняет историю boot в WM.

    Args:
        memory: экземпляр Memory.
        sync_opencode: подтягивать ли OpenCode в WM (для нативного CLI — False).
        max_boot_chars: явный лимит символов (иначе EIDOS_BOOT_MAX_TOKENS × 4).
        persist_boot_context: записать ``working.context['boot_context']`` для chat.
    """
    budget_chars = resolve_boot_char_budget(max_boot_chars)
    meta_budget = _meta_budget_chars(budget_chars)

    lines: list[str] = []
    meta_lines: list[str] = []
    boot_cues: list[str] = []
    now = time.time()

    lines.append(f"☀ Загрузка: {time.strftime('%Y-%m-%d %H:%M', time.localtime())}")
    lines.append("")

    if sync_opencode:
        try:
            from kernel.opencode_adapter import OpenCodeAdapter

            oc = OpenCodeAdapter()
            synced = oc.sync_to_working_memory(memory, max_messages=100)
            if synced:
                lines.append(f"— Синхронизировано {synced} сообщений из OpenCode")
                lines.append("")
        except Exception:
            pass

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
            cutoff = latest - span * RECENT_WINDOW_PERCENT / 100.0
        else:
            cutoff = now

        full_lines: list[str] = []
        summary_lines: list[str] = []
        full_chars = 0
        ep_budget = budget_chars - meta_budget

        latest_ts = max((float(e.get("timestamp") or 0) for e in meaningful), default=now)
        meaningful_sorted = sorted(
            meaningful,
            key=lambda e: (
                -_episode_priority(e, latest_ts=latest_ts),
                -float(e.get("timestamp") or 0),
            ),
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
                "— Эпизоды (важность × свежесть; подробно в последнем "
                f"{RECENT_WINDOW_PERCENT}% временной шкалы; {len(full_lines)} шт.):"
            )
            lines.append("")
            lines.extend(full_lines)
            lines.append("")

        if summary_lines:
            cnt = len(summary_lines)
            lines.append(f"— Эпизоды кратко ({cnt} шт.):")
            lines.append("")
            lines.extend(summary_lines)
            lines.append("")

    meta_chars = 0

    principles = memory.semantic.get_principles(min_confidence=0.7)
    if principles:
        meta_lines.append("— Мои принципы:")
        for p in principles[:5]:
            p_short = p["principle"][:150]
            conf = p["confidence"]
            meta_lines.append(f"  • [{conf:.0%}] {p_short}")
        meta_lines.append("")

    try:
        from kernel.health import memory_report

        report = memory_report()
        status = "✓ хорошо" if report["health"] == "ok" else "⚠ есть вопросы"
        wm_info = (
            f"{report['working']['event_count']} событий"
            if report["working"]["event_count"] > 0
            else "пуста"
        )
        ep_info = f"{report['episodic']['total_episodes']} эпизодов"
        sm_info = f"{report['semantic']['principles']} принципов"
        meta_lines.append("— Самочувствие:")
        meta_lines.append(f"  Статус: {status}")
        meta_lines.append(f"  Память: {ep_info}, {sm_info}")
        meta_lines.append(f"  Рабочая: {wm_info}")
        meta_lines.append("")
    except Exception:
        meta_lines.append("— Самочувствие: не удалось проверить\n")

    try:
        from kernel.instrumental import InstrumentalRegistry

        ir = InstrumentalRegistry()
        boot_summary = ir.get_boot_summary(limit=3)
        if boot_summary:
            meta_lines.append(boot_summary)
    except Exception:
        pass

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

    try:
        plan_lines = memory.goals.summary()
        if plan_lines:
            meta_lines.append("— Мой план:")
            meta_lines.append(plan_lines)
            meta_lines.append("")
    except Exception:
        pass

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

    meta_final: list[str] = []
    for line in meta_lines:
        if meta_chars + len(line) > meta_budget:
            meta_final.append(
                f"  ... (мета обрезано по бюджету {meta_budget} символов)"
            )
            break
        meta_final.append(line)
        meta_chars += len(line)

    lines.extend(meta_final)

    boot_text = "\n".join(lines)

    if len(boot_text) > budget_chars:
        boot_text = boot_text[:budget_chars] + "\n... (контекст обрезан по бюджету)"

    wm = memory.working
    wm._data.setdefault("boot_contexts", [])
    tokens_est = _count_tokens(boot_text)
    boot_entry: dict[str, Any] = {
        "timestamp": time.time(),
        "type": "boot",
        "content": boot_text,
        "tokens_estimate": tokens_est,
        "budget_tokens_estimate": budget_chars // CHARS_PER_TOKEN_EST,
    }
    wm._data["boot_contexts"].append(boot_entry)
    wm._data["boot_contexts"][:] = wm._data["boot_contexts"][-_BOOT_CONTEXT_HISTORY_LIMIT:]
    wm.save()

    if persist_boot_context:
        memory.working.set_context("boot_context", boot_text)

    return boot_text


def run_cli_chat_boot(memory: Any) -> str:
    """Boot для нативного CLI: без OpenCode, бюджет из окружения."""
    return boot_context(memory, sync_opencode=False)
