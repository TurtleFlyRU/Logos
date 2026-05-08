"""Пайплайны сборки контекста для CLI (фаза v1)."""

from __future__ import annotations

from typing import Any


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
