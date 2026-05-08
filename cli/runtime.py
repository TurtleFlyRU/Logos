"""Синхронный рантайм диалога CLI."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

import httpx

from cli.context import wm_events_to_chat_messages
from cli.llm import LLMConfigError, chat_completions

if TYPE_CHECKING:
    from kernel.memory import Memory


def run_chat_interactive(
    memory: Memory,
    session_id: str,
    *,
    use_llm: bool = True,
    stub: bool = False,
) -> None:
    """Интерактивный цикл: WM + LLM, события помечены cli_session_id."""
    from cli import session as sess

    tags = ["cli", "eidos"]
    short = session_id[:8] + "…"
    print(f"Сессия CLI {short} ({session_id}). Команды: /exit, /quit")
    if stub or not use_llm:
        print("[stub] Режим без вызова LLM (--stub).")

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            print()
            break
        if not line:
            continue
        low = line.lower()
        if low in ("/exit", "/quit"):
            break

        memory.working.add_event(
            {
                "role": "user",
                "content": line,
                "cli_session_id": session_id,
                "tags": tags,
                "event_type": "cli_chat",
            }
        )

        hist = wm_events_to_chat_messages(memory.working.data["events"], session_id)
        reply: str | None = None

        if stub or not use_llm:
            reply = f"[stub] {line[:2000]}"
        else:
            messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": (
                        "Ты Эйдос — со-исследователь. Отвечай по делу; язык ответа "
                        "подстраивай под пользователя."
                    ),
                },
            ]
            messages.extend(hist)
            try:
                reply = chat_completions(messages)
            except LLMConfigError as exc:
                print(exc, file=sys.stderr)
                reply = None
            except httpx.HTTPError as exc:
                print(f"HTTP ошибка: {exc}", file=sys.stderr)
                reply = None

        if reply:
            print(reply)
            memory.working.add_event(
                {
                    "role": "assistant",
                    "content": reply,
                    "cli_session_id": session_id,
                    "tags": tags,
                    "event_type": "cli_chat",
                }
            )
            sess.touch_session(session_id, last_turn_at=time.time())


def run_ask(question: str, *, use_llm: bool = True) -> int:
    """Один запрос: LLM при наличии ключей, иначе заглушка. Возвращает код выхода."""
    if use_llm:
        try:
            text = chat_completions([{"role": "user", "content": question}])
            print(text)
            return 0
        except LLMConfigError as exc:
            print(f"[stub] {exc}", file=sys.stderr)
            print(f"[stub] Вопрос был: {question[:500]}")
            return 2
        except httpx.HTTPError as exc:
            print(f"HTTP ошибка: {exc}", file=sys.stderr)
            return 3

    print(f"[stub] {question}")
    return 0
