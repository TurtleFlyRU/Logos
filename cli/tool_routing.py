"""Маршрутизация tool-aware раундов на отдельные LLM-профили."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from cli.agent_backends import (
    LLMRuntimeParams,
    ToolRoute,
    get_llm_runtime_params,
    resolve_tool_route as resolve_backend_tool_route,
)


_FILESYSTEM_READ_TOOLS = {"read_workspace_file", "glob", "rg", "readfile"}
_SHELL_TOOLS = {"bash", "shell", "terminal_exec"}
_NETWORK_FETCH_TOOLS = {"fetch_https_url"}


@dataclass(frozen=True)
class ToolRoundRoute:
    """Решение о профиле для tool-aware раунда."""

    profile_name: str
    runtime_params: LLMRuntimeParams
    offered_tools: tuple[str, ...]
    matched_tools: tuple[str, ...]
    routes: tuple[ToolRoute, ...]
    diagnostics: str


def tool_group_name(tool_name: str) -> str:
    """Вернуть логическую группу инструмента."""
    clean = tool_name.strip()
    if clean in _FILESYSTEM_READ_TOOLS:
        return "filesystem-read"
    if clean in _SHELL_TOOLS:
        return "shell"
    if clean in _NETWORK_FETCH_TOOLS:
        return "network-fetch"
    if clean.startswith("browser_"):
        return "browser"
    return ""


def known_tool_names() -> tuple[str, ...]:
    """Известные текущие и зарезервированные имена инструментов."""
    names = [
        "read_workspace_file",
        "fetch_https_url",
        "browser_open",
        "browser_close",
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_fill",
        "browser_press",
        "browser_screenshot",
        "glob",
        "rg",
        "readfile",
        "bash",
    ]
    return tuple(names)


def resolve_tool_route(tool_name: str) -> ToolRoute | None:
    """Разрешить маршрут одного инструмента с учётом известных групп."""
    return resolve_backend_tool_route(tool_name, group_name=tool_group_name(tool_name))


def list_tool_routes(*, tool_names: Iterable[str] | None = None) -> list[ToolRoute]:
    """Список маршрутов инструментов с групповым fallback."""
    if tool_names is None:
        tool_names = known_tool_names()
    routes: list[ToolRoute] = []
    seen: set[str] = set()
    for name in tool_names:
        clean = str(name).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        route = resolve_tool_route(clean)
        if route is not None:
            routes.append(route)
    routes.sort(key=lambda item: (item.profile_name, item.tool_name))
    return routes


def resolve_tool_round_route(tool_names: Sequence[str]) -> ToolRoundRoute | None:
    """Выбрать профиль для раунда, где модели доступны инструменты."""
    offered_tools: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        clean = str(name).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        offered_tools.append(clean)

    routes = [route for name in offered_tools if (route := resolve_tool_route(name)) is not None]
    if not routes:
        return None

    profile_names = sorted({route.profile_name for route in routes})
    if len(profile_names) != 1:
        details = ", ".join(f"{route.tool_name}->{route.profile_name}" for route in routes)
        raise RuntimeError(
            "Найдено несколько профилей для одного tool-aware раунда: "
            f"{details}. Приведите маршруты к одному профилю."
        )

    profile_name = profile_names[0]
    matched_tools = tuple(route.tool_name for route in routes)
    details = ", ".join(f"{route.tool_name}[{route.source}]" for route in routes)
    diagnostics = f"route={details} -> {profile_name}"
    return ToolRoundRoute(
        profile_name=profile_name,
        runtime_params=get_llm_runtime_params(profile_name=profile_name),
        offered_tools=tuple(offered_tools),
        matched_tools=matched_tools,
        routes=tuple(routes),
        diagnostics=diagnostics,
    )


def format_tool_routing_report() -> str:
    """Человекочитаемый отчёт по маршрутам инструментов."""
    routes = list_tool_routes()
    lines = ["[tool_routing] Настроенные маршруты инструментов:"]
    if not routes:
        lines.append("  <none>")
        return "\n".join(lines)

    for route in routes:
        via = f" via {route.group_name}" if route.group_name else ""
        lines.append(
            f"  {route.tool_name} -> {route.profile_name} "
            f"(source={route.source}{via})"
        )
    return "\n".join(lines)

