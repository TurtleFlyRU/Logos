"""Показ бюджетов контекста CLI и текущего заполнения."""

from __future__ import annotations

from typing import Any

from cli.context import (
    _active_memory_budget_chars,
    _env_flag,
    _keep_last_messages,
    _layer_budget_enabled,
    _summary_char_budget,
    _summarize_old_wm_enabled,
    _total_chat_char_budget,
    _wm_message_budget,
    _wm_summary_style,
    build_chat_messages_for_llm,
    chat_context_metrics,
    format_context_metrics_sizes,
)


def _fill_ratio_text(used: int, total: int) -> str:
    """Отрендерить заполнение бюджета как `used/total` и проценты."""
    if total <= 0:
        return f"{used} chars (uncapped)"
    pct = min(999.0, (used / total) * 100.0) if total else 0.0
    free = max(0, total - used)
    return f"{used}/{total} chars ({pct:.0f}%, free={free})"


def _auto_sleep_text(memory: Any) -> str:
    """Отрендерить текущее состояние счётчика auto-sleep."""
    working = getattr(memory, "working", None)
    if working is None:
        return "-"
    data = getattr(working, "data", None)
    event_count = 0
    if isinstance(data, dict):
        try:
            event_count = max(0, int(data.get("event_count", 0) or 0))
        except (TypeError, ValueError):
            event_count = 0
    try:
        threshold = max(1, int(getattr(working, "AUTO_SLEEP_THRESHOLD", 0) or 0))
    except (TypeError, ValueError):
        threshold = 0
    if threshold <= 0:
        return "-"
    remaining = max(0, threshold - event_count)
    return f"{event_count}/{threshold} events (remaining={remaining})"


def format_chat_budget_report(
    memory: Any,
    cli_session_id: str,
    *,
    user_message: str | None = None,
) -> str:
    """Сформировать отчёт о бюджетах и текущем заполнении контекста.

    Args:
        memory: Экземпляр памяти с рабочей памятью и backends.
        cli_session_id: Текущий chat session id.
        user_message: Опциональный текст текущего запроса для preview-оценки.

    Returns:
        Многострочный текст для печати в CLI.
    """
    total_budget = _total_chat_char_budget()
    messages = build_chat_messages_for_llm(
        memory,
        cli_session_id,
        user_message=user_message,
    )
    metrics = chat_context_metrics(messages, total_budget=total_budget)
    used = int(metrics["total_chars"])
    sizes = format_context_metrics_sizes(metrics, sep=", ")
    summary_on = _summarize_old_wm_enabled()

    lines = [
        "[budget] Chat budgets and fill:",
        f"  total: {_fill_ratio_text(used, total_budget)}",
        (
            f"  config: wm_messages={_wm_message_budget()}, "
            f"active_memory_chars={_active_memory_budget_chars()}, "
            f"layer_budget={'on' if _layer_budget_enabled(total_budget=total_budget) else 'off'}"
        ),
        (
            f"  summary_old_wm={'on' if summary_on else 'off'}, "
            f"summary_chars={_summary_char_budget()}, "
            f"keep_last={_keep_last_messages()}, style={_wm_summary_style()}"
        ),
        f"  auto_sleep: {_auto_sleep_text(memory)}",
        (
            f"  payload: system={metrics['system_messages']}, "
            f"history={metrics['history_messages']}, tool={metrics['tool_messages']}, "
            f"tok≈{metrics['approx_prompt_tokens']}"
        ),
        f"  split: {sizes or '-'}",
    ]

    if _env_flag("EIDOS_CHAT_ACTIVE_MEMORY", default=True):
        layers = metrics.get("layers", {})
        active = []
        if isinstance(layers, dict):
            active = [name for name, enabled in layers.items() if enabled]
        lines.append(f"  layers: {', '.join(active) if active else '-'}")
    return "\n".join(lines)
