"""Показ активных env-настроек CLI в человекочитаемом виде."""

from __future__ import annotations

import os
from typing import Iterable

_ENV_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "paths",
        (
            "LOGOS_DATA_ROOT",
            "PLAYWRIGHT_BROWSERS_PATH",
        ),
    ),
    (
        "repo_public_log",
        (
            "EIDOS_REPO_PUBLIC_LOG",
            "EIDOS_REPO_PUBLIC_LOG_DIR",
        ),
    ),
    (
        "llm",
        (
            "EIDOS_AGENT_PROFILE",
            "EIDOS_AGENTS_CONFIG",
            "LLM_BASE_URL",
            "LLM_MODEL",
            "LLM_TIMEOUT_SEC",
            "LLM_IGNORE_PROXY",
            "LLM_PROGRESS",
            "LLM_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
    ),
    (
        "tools",
        (
            "EIDOS_TOOLS",
            "EIDOS_TOOL_ROUNDS",
            "EIDOS_HTTP_FETCH",
            "EIDOS_HTTP_FETCH_TIMEOUT_SEC",
            "EIDOS_HTTP_FETCH_MAX_BYTES",
            "EIDOS_HTTP_FETCH_USER_AGENT",
        ),
    ),
    (
        "browser",
        (
            "EIDOS_PLAYWRIGHT",
            "EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST",
            "EIDOS_PLAYWRIGHT_IGNORE_PROXY",
            "EIDOS_PLAYWRIGHT_TIMEOUT_MS",
            "EIDOS_PLAYWRIGHT_USER_AGENT",
            "EIDOS_PLAYWRIGHT_PROXY_SERVER",
            "EIDOS_PLAYWRIGHT_PROXY_USERNAME",
            "EIDOS_PLAYWRIGHT_PROXY_PASSWORD",
            "EIDOS_PLAYWRIGHT_PROXY_BYPASS",
        ),
    ),
    (
        "chat_pipeline",
        (
            "EIDOS_CHAT_METRICS",
            "EIDOS_CHAT_TOTAL_CHARS",
            "EIDOS_CHAT_WM_MESSAGES",
            "EIDOS_CODE_REVIEW_PROFILES",
            "EIDOS_STRIP_MODEL_THOUGHT",
        ),
    ),
    (
        "proxy_env",
        (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        ),
    ),
)

_SECRET_MARKERS = ("KEY", "PASSWORD", "TOKEN", "SECRET")


def _is_secret_var(name: str) -> bool:
    """Определить, нужно ли маскировать значение переменной.

    Args:
        name: Имя env-переменной.

    Returns:
        True, если значение не стоит печатать в открытом виде.
    """
    upper = name.upper()
    return any(marker in upper for marker in _SECRET_MARKERS)


def _render_env_value(name: str, value: str | None) -> str:
    """Отрендерить значение env для терминала.

    Args:
        name: Имя env-переменной.
        value: Значение или None, если переменная не выставлена.

    Returns:
        Строка для показа в CLI.
    """
    if value is None:
        return "<unset>"
    if _is_secret_var(name):
        return "<set>"
    return value if value != "" else '""'


def _iter_group_lines(name: str, keys: Iterable[str], *, show_unset: bool) -> list[str]:
    """Собрать строки одной логической группы env-переменных."""
    rows = [f"  [{name}]"]
    found = False
    for key in keys:
        value = os.environ.get(key)
        if value is None and not show_unset:
            continue
        found = True
        rows.append(f"    {key}={_render_env_value(key, value)}")
    return rows if found else []


def format_cli_env_report(*, show_unset: bool = True) -> str:
    """Сформировать отчёт по env-настройкам CLI.

    Args:
        show_unset: Показывать ли переменные без значения как ``<unset>``.

    Returns:
        Многострочный текст для прямой печати в терминал.
    """
    lines = ["[env] Настройки CLI (секреты скрыты):"]
    for group_name, keys in _ENV_GROUPS:
        group_lines = _iter_group_lines(group_name, keys, show_unset=show_unset)
        if group_lines:
            lines.extend(group_lines)
    from cli.tool_routing import format_tool_routing_report

    lines.append(format_tool_routing_report())
    return "\n".join(lines)
