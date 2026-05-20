"""Tool search (OpenAI-compatible): отложенная загрузка инструментов в ходе диалога.

По умолчанию **client-executed** (работает с chat/completions и локальными моделями):
в API сначала только «ядро» + ``eidos_tool_search``; модель запрашивает namespace/query,
полные схемы подгружаются на следующие раунды tool loop.

Нативный режим (``defer_loading`` + ``type: tool_search``) — только при
``EIDOS_TOOL_SEARCH_NATIVE=1`` (модели вроде gpt-5.4+ на Responses/OpenAI).

Env:
- ``EIDOS_TOOL_SEARCH`` — ``1`` (по умолчанию): отложенная загрузка; ``0`` — все tools сразу.
- ``EIDOS_TOOL_SEARCH_NATIVE`` — ``1``: нативные поля OpenAI (иначе client ``eidos_tool_search``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from cli.tools import tools_enabled

TOOL_SEARCH_FN = "eidos_tool_search"

# Всегда в API с первого раунда (не defer).
IMMEDIATE_TOOL_NAMES: frozenset[str] = frozenset(
    {"read_workspace_file", "eidos_echo", "bash"}
)

NAMESPACES: tuple[str, ...] = ("workspace", "memory", "browser", "network")

NAMESPACE_LABELS: dict[str, str] = {
    "workspace": "Файлы и отладка в репозитории (read_workspace_file, eidos_echo, bash)",
    "memory": "Память Эйдос: episodic, semantic, journal, external (memory_*)",
    "browser": "Браузер Playwright (browser_*)",
    "network": "HTTP GET по публичным URL (fetch_https_url)",
}


def tool_search_enabled() -> bool:
    if not tools_enabled():
        return False
    v = os.environ.get("EIDOS_TOOL_SEARCH", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def tool_search_native_enabled() -> bool:
    """Нативный ``tool_search`` + ``defer_loading`` (OpenAI gpt-5.4+)."""
    if not tool_search_enabled():
        return False
    v = os.environ.get("EIDOS_TOOL_SEARCH_NATIVE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def is_tool_search_meta_name(name: str) -> bool:
    return name.strip() == TOOL_SEARCH_FN


def collect_all_tool_specs() -> list[dict[str, Any]]:
    """Полный реестр tools среды (как ``builtin_tool_specs``)."""
    from cli.tools import builtin_tool_specs

    return list(builtin_tool_specs())


def tool_namespace(name: str) -> str:
    if name.startswith("memory_"):
        return "memory"
    if name == "fetch_https_url":
        return "network"
    if name.startswith("browser_"):
        return "browser"
    return "workspace"


def _spec_name(spec: dict[str, Any]) -> str:
    fn = spec.get("function") or {}
    return str(fn.get("name") or "").strip()


def partition_specs(
    specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """immediate, deferred_by_namespace."""
    immediate: list[dict[str, Any]] = []
    deferred: dict[str, list[dict[str, Any]]] = {k: [] for k in NAMESPACES}
    if not tool_search_enabled():
        return list(specs), {k: [] for k in NAMESPACES}

    for spec in specs:
        name = _spec_name(spec)
        if not name:
            continue
        ns = tool_namespace(name)
        if name in IMMEDIATE_TOOL_NAMES:
            immediate.append(spec)
        else:
            deferred.setdefault(ns, []).append(spec)
    return immediate, deferred


@dataclass
class ToolSearchSession:
    """Состояние загрузки tools на один пользовательский ход."""

    loaded: set[str] = field(default_factory=set)
    all_specs: list[dict[str, Any]] = field(default_factory=list)
    immediate: list[dict[str, Any]] = field(default_factory=list)
    deferred: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def start(cls) -> ToolSearchSession:
        all_specs = collect_all_tool_specs()
        immediate, deferred = partition_specs(all_specs)
        loaded = {_spec_name(s) for s in immediate if _spec_name(s)}
        return cls(
            loaded=loaded,
            all_specs=all_specs,
            immediate=immediate,
            deferred=deferred,
        )

    def spec_by_name(self, name: str) -> dict[str, Any] | None:
        for spec in self.all_specs:
            if _spec_name(spec) == name:
                return spec
        return None

    def _deferred_flat(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for ns in ("workspace", "memory", "browser", "network"):
            out.extend(self.deferred.get(ns) or [])
        return out

    def _mark_defer(self, spec: dict[str, Any], defer: bool) -> dict[str, Any]:
        import copy

        out = copy.deepcopy(spec)
        fn = out.setdefault("function", {})
        if defer:
            fn["defer_loading"] = True
        else:
            fn.pop("defer_loading", None)
        return out

    def _namespace_stub(self, ns: str, specs: list[dict[str, Any]]) -> dict[str, Any]:
        names = ", ".join(_spec_name(s) for s in specs if _spec_name(s))
        desc = NAMESPACE_LABELS.get(ns, ns)
        if names:
            desc = f"{desc}. Инструменты: {names}. Загрузка: eidos_tool_search(namespace={ns!r})."
        return {
            "type": "function",
            "function": {
                "name": f"namespace_{ns}",
                "description": desc[:1024],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hint": {
                            "type": "string",
                            "description": "Не вызывайте напрямую — используйте eidos_tool_search.",
                        }
                    },
                },
            },
        }

    def build_api_tool_specs(self) -> list[dict[str, Any]]:
        """Список для поля ``tools`` в текущем раунде API."""
        if not tool_search_enabled():
            return list(self.all_specs)

        if tool_search_native_enabled():
            out: list[dict[str, Any]] = [{"type": "tool_search"}]
            for spec in self.immediate:
                out.append(self._mark_defer(spec, False))
            for spec in self._deferred_flat():
                name = _spec_name(spec)
                defer = name not in self.loaded
                out.append(self._mark_defer(spec, defer))
            return out

        out = [self._mark_defer(s, False) for s in self.immediate]
        out.append(_eidos_tool_search_spec())
        for name in sorted(self.loaded):
            if name in IMMEDIATE_TOOL_NAMES or is_tool_search_meta_name(name):
                continue
            spec = self.spec_by_name(name)
            if spec is not None:
                out.append(spec)
        return out

    def catalog_deferred_summary(self) -> list[str]:
        if not tool_search_enabled():
            return []
        lines: list[str] = []
        for ns in ("workspace", "memory", "browser", "network"):
            specs = self.deferred.get(ns) or []
            if not specs:
                continue
            names = [_spec_name(s) for s in specs if _spec_name(s)]
            loaded_here = [n for n in names if n in self.loaded]
            lines.append(
                f"  namespace {ns}: {len(names)} tool(s)"
                + (f", загружено: {', '.join(loaded_here)}" if loaded_here else " (через eidos_tool_search)")
            )
        return lines


def _eidos_tool_search_spec() -> dict[str, Any]:
    ns_enum = list(NAMESPACES)
    return {
        "type": "function",
        "function": {
            "name": TOOL_SEARCH_FN,
            "description": (
                "Client tool search (как OpenAI tool_search, execution=client): "
                "найти и загрузить отложенные инструменты по namespace и/или query. "
                "После вызова полные схемы станут доступны для function calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Подстрока в имени или описании инструмента",
                    },
                    "namespace": {
                        "type": "string",
                        "enum": ns_enum,
                        "description": "Ограничить поиск одним namespace",
                    },
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Явный список имён для загрузки",
                    },
                },
            },
        },
    }


def _tokenize_query(query: str) -> list[str]:
    return [t for t in re.split(r"[\s_,./-]+", query.lower()) if len(t) >= 2]


def execute_tool_search(
    session: ToolSearchSession,
    args: dict[str, Any],
) -> tuple[str, list[str]]:
    """Загрузить tools; возвращает (текст для role=tool, новые имена)."""
    newly: list[str] = []

    def _load(name: str) -> None:
        if not name or name in session.loaded:
            return
        if session.spec_by_name(name) is None:
            return
        session.loaded.add(name)
        newly.append(name)

    explicit = args.get("names")
    if isinstance(explicit, list):
        for raw in explicit:
            _load(str(raw).strip())

    ns_filter = str(args.get("namespace") or "").strip().lower()
    if ns_filter not in NAMESPACES:
        ns_filter = ""

    query = str(args.get("query") or "").strip()
    tokens = _tokenize_query(query)

    if ns_filter and not tokens and not isinstance(explicit, list):
        for spec in session.deferred.get(ns_filter) or []:
            _load(_spec_name(spec))

    if tokens:
        for spec in session._deferred_flat():
            name = _spec_name(spec)
            if not name:
                continue
            if ns_filter and tool_namespace(name) != ns_filter:
                continue
            fn = spec.get("function") or {}
            desc = str(fn.get("description") or "").lower()
            hay = f"{name} {desc}"
            if any(t in hay for t in tokens):
                _load(name)

    payload = {
        "tool_search_output": {
            "loaded": sorted(session.loaded),
            "newly_loaded": newly,
            "api_tools_next_round": len(session.build_api_tool_specs()),
        },
        "hint": "Теперь можно вызывать загруженные function tools.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=0), newly
