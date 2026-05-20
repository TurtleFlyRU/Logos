"""Каталог инструментов сессии: единая сборка specs + текст для system (авто каждый ход)."""

from __future__ import annotations

import os
from typing import Any

from cli.context import tools_allowed_for_chat_line
from cli.tools import tools_enabled


def tools_catalog_enabled() -> bool:
    """Текстовый блок в system; всегда при ``EIDOS_TOOLS=1``."""
    return tools_enabled()


def collect_tool_specs() -> list[dict[str, Any]]:
    """Все tool specs, доступные в этой среде."""
    from cli.tool_search import collect_all_tool_specs

    return collect_all_tool_specs()


def tool_names_from_specs(specs: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for spec in specs:
        fn = spec.get("function") or {}
        name = fn.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _env_on(key: str, *, default: bool = True) -> bool:
    raw = os.environ.get(key, "1" if default else "0").strip().lower()
    if default:
        return raw not in ("0", "false", "no", "off")
    return raw in ("1", "true", "yes", "on")


def _disabled_by_env_notes() -> list[str]:
    """Инструменты, которые сейчас не попали в specs из-за env."""
    notes: list[str] = []
    if not _env_on("EIDOS_TOOLS", default=True):
        notes.append("EIDOS_TOOLS=0 — все инструменты выключены")
    if not _env_on("EIDOS_MEMORY_TOOLS", default=True):
        notes.append("EIDOS_MEMORY_TOOLS=0 — memory_* выключены")
    if not _env_on("EIDOS_HTTP_FETCH", default=True):
        notes.append("EIDOS_HTTP_FETCH=0 — fetch_https_url недоступен")
    if not _env_on("EIDOS_PLAYWRIGHT", default=True):
        notes.append("EIDOS_PLAYWRIGHT=0 — browser_* недоступны")
    return notes


def format_tools_catalog_block(
    *,
    user_line: str | None = None,
    max_chars: int | None = 8000,
) -> str:
    """Текст для вставки в system: актуальный список на этот ход."""
    if not tools_catalog_enabled():
        return ""

    from cli.tool_search import ToolSearchSession, tool_search_enabled

    specs = collect_tool_specs()
    names = tool_names_from_specs(specs)
    session = ToolSearchSession.start() if tool_search_enabled() else None
    api_specs = session.build_api_tool_specs() if session else specs
    api_names = tool_names_from_specs(api_specs)
    allowed = True
    if user_line is not None:
        allowed = tools_allowed_for_chat_line(user_line)

    lines = [
        "— Доступные инструменты (сессия, обновляется автоматически каждый ход):",
    ]
    if not tools_enabled():
        lines.append("  tool_calls: выключены глобально (EIDOS_TOOLS=0).")
    elif not allowed:
        lines.append(
            "  tool_calls: для этой реплики отключены (короткий вопрос про личность; "
            "см. EIDOS_CHAT_TOOLS_ON_IDENTITY=1 чтобы разрешить)."
        )
        lines.append(f"  В API не передаётся tools; зарегистрировано в среде: {len(names)}.")
    elif session is not None:
        lines.append(
            f"  tool_search: вкл.; в API сейчас {len(api_names)} tool(s) "
            f"(всего в среде {len(names)}; загрузка: eidos_tool_search)."
        )
        for note in session.catalog_deferred_summary():
            lines.append(note)
    else:
        lines.append(
            f"  tool_calls: разрешены; в API передаётся {len(names)} инструмент(ов)."
        )

    catalog_specs = api_specs if session is not None else specs
    for spec in catalog_specs:
        fn = spec.get("function") or {}
        name = str(fn.get("name") or "?")
        desc = str(fn.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 160:
            desc = desc[:159] + "…"
        lines.append(f"  · {name}" + (f" — {desc}" if desc else ""))

    for note in _disabled_by_env_notes():
        if note not in lines:
            lines.append(f"  ⚠ {note}")

    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def format_tools_help() -> str:
    """Текст для slash ``/tools`` (CLI, desktop, chat_turn)."""
    from cli.tool_search import tool_search_enabled, tool_search_native_enabled

    tools_on = tools_enabled()
    search_on = tool_search_enabled()
    lines = [
        "Инструменты Эйдос",
        "",
        "1) Каталог в system — автоматически каждый ход при EIDOS_TOOLS=1.",
        "2) Tool search — отложенная загрузка (EIDOS_TOOL_SEARCH=1, по умолчанию вкл.).",
        f"   client: eidos_tool_search · native OpenAI: {'on' if tool_search_native_enabled() else 'off'}",
        "",
    ]
    if not tools_on:
        lines.append("EIDOS_TOOLS=0 — инструменты и каталог выключены.")
    else:
        block = format_tools_catalog_block(max_chars=12_000)
        if block:
            lines.append(block)
        lines.extend(
            [
                "",
                "Env:",
                "  EIDOS_TOOLS — мастер-выключатель",
                f"  EIDOS_TOOL_SEARCH — {'on' if search_on else 'off'} (все tools сразу при off)",
                "  EIDOS_TOOL_SEARCH_NATIVE — нативный type:tool_search (gpt-5.4+)",
                "  EIDOS_MEMORY_TOOLS, EIDOS_PLAYWRIGHT, EIDOS_HTTP_FETCH — состав builtin_tool_specs",
                "  EIDOS_CHAT_TOOLS_ON_IDENTITY — tool_calls на «кто я»",
                "",
                "Slash: /tools · /memory (память)",
            ]
        )
    return "\n".join(lines)
