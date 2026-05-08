"""Пайплайны сборки контекста для CLI (фаза v1)."""

from __future__ import annotations

from typing import Any


def wm_events_to_chat_messages(
    events: list[dict[str, Any]],
    cli_session_id: str,
    *,
    max_messages: int = 40,
) -> list[dict[str, str]]:
    """События WM с данным cli_session_id → история user/assistant для chat/completions."""
    out: list[dict[str, str]] = []
    for ev in events:
        if ev.get("cli_session_id") != cli_session_id:
            continue
        role = ev.get("role")
        if role not in ("user", "assistant"):
            continue
        content = ev.get("content") or ev.get("message") or ""
        text = str(content).strip()
        if not text:
            continue
        out.append({"role": str(role), "content": text})
    return out[-max_messages:]
