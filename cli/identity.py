"""Имя пользователя из явных фраз в CLI → WM context."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"меня\s+зовут\s+([А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,48})", re.I),
    re.compile(r"my\s+name\s+is\s+([A-Za-zА-Яа-яЁё][А-Яа-яЁёA-Za-z\-]{1,48})", re.I),
    re.compile(r"(?:^|[\s,.!?])я\s*[—\-]\s*([А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,48})(?:\s|$|[,.!?])", re.I),
)


def try_capture_user_display_name(memory: Any, line: str) -> None:
    text = line.strip()
    if len(text) < 4:
        return
    for rx in _PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        name = str(m.group(1)).strip()
        if 2 <= len(name) <= 60:
            memory.working.set_context("user_display_name", name)
        return


def seed_user_display_name_from_agents_md(memory: Any) -> None:
    """Если имя ещё не задано — взять его из корневого AGENTS.md.

    Это делает поведение CLI ближе к OpenCode: имя доступно сразу при приветствии,
    без необходимости произносить его в текущей сессии.
    """
    try:
        ctx = memory.working.data.get("context") or {}
        if isinstance(ctx.get("user_display_name"), str) and ctx["user_display_name"].strip():
            return
    except Exception:
        pass

    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "AGENTS.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return

    # Паттерн: "Работаю в паре с человеком (TurtleFlyRU, Александр)."
    m = re.search(
        r"Работаю\s+в\s+паре\s+с\s+человеком\s*\\([^,)]{2,64},\\s*([A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\\-]{1,48})\\)",
        text,
        re.I,
    )
    if not m:
        return
    name = str(m.group(1)).strip()
    if 2 <= len(name) <= 60:
        try:
            memory.working.set_context("user_display_name", name)
        except Exception:
            return
