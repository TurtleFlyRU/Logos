"""Синхронный рантайм диалога (v1 — заглушка до полной оркестрации)."""

from __future__ import annotations

import sys

import httpx

from cli.llm import LLMConfigError, chat_completions


def run_chat_stub() -> None:
    """Интерактивный цикл без LLM: только проверка UX и slash-команд."""
    print("Эйдос CLI (фаза внедрения). Команды: /exit, /quit")
    print("[stub] Ответы модели будут подключены через полный runtime.")
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
        print(f"[stub] assistant> {line[:2000]}")


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
