"""Опциональная запись публичного CLI-лога в дерево репозитория (не в data/).

Пишет только при ``EIDOS_REPO_PUBLIC_LOG=1``. Содержимое проходит санитизацию:
без блоков кода, без результатов инструментов, усечение и маскирование типичных секретов.
Автоматического git push/commit нет — только файлы на диске.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from kernel.config import REPO_ROOT

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_ASSIGN_SECRET_RE = re.compile(
    r"(?i)\b("
    r"(?:[a-z0-9]+_)?api[_-]?key|access[_-]?token|auth[_-]?token|bearer|client[_-]?secret|"
    r"password|passwd|pwd|secret|token"
    r")\b\s*[:=]\s*\S+"
)
_SK_OPENAI_RE = re.compile(r"\bsk-[A-Za-z0-9]{10,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _log_dir() -> Path:
    raw = os.environ.get("EIDOS_REPO_PUBLIC_LOG_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT / "log" / "cli").resolve()


def _sanitize_text(text: str, *, max_len: int = 1200) -> str:
    """Убрать типичные утечки и обрезать длину."""
    s = _CODE_FENCE_RE.sub("[omitted: code block]", text)
    s = _ASSIGN_SECRET_RE.sub(r"\1=[redacted]", s)
    s = _SK_OPENAI_RE.sub("sk-[redacted]", s)
    s = _JWT_RE.sub("[redacted:jwt]", s)
    s = " ".join(s.split())
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _tool_names_only(tool_calls: list[dict[str, Any]] | None) -> str:
    if not tool_calls:
        return ""
    names: list[str] = []
    for tc in tool_calls:
        fn = tc.get("function") if isinstance(tc, dict) else None
        if isinstance(fn, dict):
            n = str(fn.get("name") or "").strip()
            if n:
                names.append(n)
    return ", ".join(names)


def maybe_append_cli_public_log(
    *,
    event: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """Если включено и событие подходит — дописать строку в дневной markdown-файл.

    Условия: ``EIDOS_REPO_PUBLIC_LOG``, нативный CLI (``cli_transport == eidos``),
    ``event_type == cli_chat``, роли только ``user`` или ``assistant``.
    Результаты ``role=tool`` сюда не попадают (вызывающий код их не шлёт).

    Args:
        event: Одно событие рабочей памяти.
        context: ``working.data["context"]``.
    """
    if not _env_truthy("EIDOS_REPO_PUBLIC_LOG"):
        return
    if context.get("cli_transport") != "eidos":
        return
    if event.get("event_type") != "cli_chat":
        return
    role = str(event.get("role") or "")
    if role not in ("user", "assistant"):
        return

    base = _log_dir()
    base.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.localtime())
    path = base / f"{day}.md"

    ts = time.strftime("%H:%M:%S", time.localtime())
    sid = event.get("cli_session_id")
    sid_s = str(sid)[:12] if sid else "-"

    lines: list[str] = []
    if not path.exists():
        lines.append(f"# Эйдос — публичный CLI-лог ({day})\n")

    lines.append("\n---\n")
    lines.append(f"## {role} — {ts} (session {sid_s})\n")

    tcalls = event.get("tool_calls")
    if role == "assistant" and isinstance(tcalls, list) and tcalls:
        names = _tool_names_only(tcalls)
        if names:
            lines.append(f"**tools:** {names}\n")

    raw = event.get("content", event.get("message", event.get("text", "")))
    body = str(raw).strip() if raw is not None else ""
    if body:
        lines.append("\n")
        lines.append(_sanitize_text(body))
        lines.append("\n")

    block = "".join(lines)
    with path.open("a", encoding="utf-8") as f:
        f.write(block)
