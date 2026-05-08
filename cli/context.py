"""Пайплайны сборки контекста для CLI (фаза 5 — единая сборка для chat).

Переменные окружения (все опциональны):
- EIDOS_CHAT_WM_MESSAGES — сколько последних WM-сообщений отдавать в API (4–80, по умолчанию 40).
- EIDOS_CHAT_ATTENTION — ``0``: не добавлять слоты внимания в system (по умолчанию вкл.).
- EIDOS_CHAT_BOOT_SNIPPET — ``0``: не добавлять фрагмент ``boot_context`` в system (по умолчанию **вкл.**).
- EIDOS_CHAT_BOOT_SNIPPET_CHARS — максимум символов фрагмента boot в system (по умолчанию 12000).
- EIDOS_CHAT_PRINCIPLES — ``0``: не добавлять блок семантических принципов (по умолчанию вкл.).
"""

from __future__ import annotations

import os
from typing import Any

CLI_CHAT_PERSONA = (
    "Ты Эйдос — со-исследователь. Отвечай по делу; язык ответа подстраивай под пользователя. "
    "Если нужно проверить цикл инструментов — доступны функции eidos_echo и "
    "read_workspace_file (только файлы внутри репозитория)."
)

_DEFAULT_WM_MESSAGES = 40
_DEFAULT_BOOT_SNIPPET_CHARS = 12000
_DEFAULT_PRINCIPLES_LIMIT = 5
_DEFAULT_PRINCIPLES_MIN_CONF = 0.7


def _env_flag(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw not in ("0", "false", "no", "off")


def _wm_message_budget() -> int:
    raw = os.environ.get("EIDOS_CHAT_WM_MESSAGES", "").strip()
    if not raw:
        return _DEFAULT_WM_MESSAGES
    try:
        return max(4, min(80, int(raw)))
    except ValueError:
        return _DEFAULT_WM_MESSAGES


def _boot_snippet_char_cap() -> int:
    raw = os.environ.get("EIDOS_CHAT_BOOT_SNIPPET_CHARS", "").strip()
    if raw:
        try:
            return max(800, min(120_000, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_BOOT_SNIPPET_CHARS


def wm_events_to_chat_messages(
    events: list[dict[str, Any]],
    cli_session_id: str,
    *,
    max_messages: int = 40,
) -> list[dict[str, Any]]:
    """События WM с данным cli_session_id → сообщения для chat/completions."""
    out: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("cli_session_id") != cli_session_id:
            continue
        role = ev.get("role")
        if role == "tool":
            tid = ev.get("tool_call_id")
            if not tid:
                continue
            content = ev.get("content") or ""
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tid),
                    "content": str(content),
                }
            )
            continue
        if role == "assistant":
            tc = ev.get("tool_calls")
            if tc:
                msg_a: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": tc,
                    "content": ev["content"] if "content" in ev else None,
                }
                out.append(msg_a)
                continue
            content_a = ev.get("content") or ev.get("message") or ""
            text_a = str(content_a).strip()
            if not text_a:
                continue
            out.append({"role": "assistant", "content": text_a})
            continue
        if role == "user":
            content = ev.get("content") or ev.get("message") or ""
            text = str(content).strip()
            if not text:
                continue
            out.append({"role": "user", "content": text})
            continue
    return out[-max_messages:]


def format_attention_slots_block(memory: Any) -> str:
    slots = (memory.working.data.get("attention_slots") or [])[-4:]
    if not slots:
        return ""
    lines = ["— Слоты внимания (WM):"]
    for slot in slots:
        summary = str(slot.get("summary", ""))[:200]
        role = slot.get("role", "event")
        lines.append(f"  • [{role}] {summary}")
    return "\n".join(lines) + "\n"


def format_boot_context_snippet(
    memory: Any,
    *,
    max_chars: int = _DEFAULT_BOOT_SNIPPET_CHARS,
) -> str:
    ctx = memory.working.data.get("context") or {}
    boot = ctx.get("boot_context")
    if not boot or not isinstance(boot, str):
        return ""
    text = boot.strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return (
        "— Фрагмент сохранённого boot-контекста (из WM, без повторного boot):\n"
        + text
        + "\n\n"
    )


def format_semantic_principles_block(
    memory: Any,
    *,
    limit: int = _DEFAULT_PRINCIPLES_LIMIT,
    min_confidence: float = _DEFAULT_PRINCIPLES_MIN_CONF,
) -> str:
    rows = memory.semantic.get_principles(min_confidence=min_confidence)[:limit]
    if not rows:
        return ""
    lines = ["— Принципы (семантическая память):"]
    for row in rows:
        p = str(row.get("principle", "")).strip()
        if not p:
            continue
        conf = float(row.get("confidence") or 0)
        lines.append(f"  • [{conf:.2f}] {p[:400]}")
    return "\n".join(lines) + "\n"


def build_chat_context(
    memory: Any,
    cli_session_id: str,
    *,
    user_message: str | None = None,
) -> str:
    """Текстовые блоки для дополнения system-сообщения (не включает персону).

    ``cli_session_id`` зарезервирован под фильтрацию по сессии в следующих слоях.
    ``user_message`` — заготовка под cue-based retrieval (позже); пока не используется.
    """
    del cli_session_id, user_message  # зарезервированы под фильтрацию и cue-retrieval

    parts: list[str] = []
    if _env_flag("EIDOS_CHAT_ATTENTION", default=True):
        parts.append(format_attention_slots_block(memory))
    if _env_flag("EIDOS_CHAT_BOOT_SNIPPET", default=True):
        parts.append(
            format_boot_context_snippet(memory, max_chars=_boot_snippet_char_cap())
        )
    if _env_flag("EIDOS_CHAT_PRINCIPLES", default=True):
        parts.append(
            format_semantic_principles_block(
                memory,
                limit=_DEFAULT_PRINCIPLES_LIMIT,
                min_confidence=_DEFAULT_PRINCIPLES_MIN_CONF,
            )
        )
    return "\n".join(p for p in parts if p).strip()


def build_chat_messages_for_llm(
    memory: Any,
    cli_session_id: str,
    *,
    max_wm_messages: int | None = None,
    tools_compatible_history: bool = True,
    user_message: str | None = None,
) -> list[dict[str, Any]]:
    """Полный список сообщений для chat/completions: system (персона + контекст) + хвост WM."""
    from cli.tools import tools_enabled

    max_wm = max_wm_messages if max_wm_messages is not None else _wm_message_budget()
    hist = wm_events_to_chat_messages(
        memory.working.data["events"],
        cli_session_id,
        max_messages=max_wm,
    )
    if tools_compatible_history and not tools_enabled():
        hist = [h for h in hist if h.get("role") in ("user", "assistant")]

    extra = build_chat_context(memory, cli_session_id, user_message=user_message)
    system_content = CLI_CHAT_PERSONA.strip()
    if extra:
        system_content = f"{system_content}\n\n{extra}"

    return [{"role": "system", "content": system_content}, *hist]
