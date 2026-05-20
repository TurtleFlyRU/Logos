"""Профили LLM из YAML (фаза 9a): OpenAI-compatible endpoint + ключи из env.

Файл конфигурации (первый существующий путь):

1. ``EIDOS_AGENTS_CONFIG`` — явный путь
2. ``$LOGOS_DATA_ROOT/config/agents.yaml`` (или ``data/config/agents.yaml`` при корне repo)
3. ``<repo>/config/agents.yaml``
4. ``<repo>/config/agents.defaults.yaml`` (коммитится в репозитории)

Профиль по умолчанию: ``default_profile`` в YAML (в шаблоне — ``deepseek``).
Переопределение: ``EIDOS_AGENT_PROFILE=<имя>``. Без профиля и без YAML — legacy ``LLM_*``.
Ключ DeepSeek: ``.env`` в корне репозитория (``DEEPSEEK_API_KEY`` или ``LLM_API_KEY``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kernel.config import DATA_ROOT, REPO_ROOT

_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-chat"


@dataclass(frozen=True)
class LLMRuntimeParams:
    """Параметры одного запроса chat/completions."""

    api_key: str
    base_url: str
    model: str
    read_timeout_sec: float
    omit_authorization_header: bool = False
    profile_name: str = ""


@dataclass(frozen=True)
class ToolRoute:
    """Разрешённый маршрут инструмента на профиль LLM."""

    tool_name: str
    profile_name: str
    group_name: str = ""
    source: str = "tool"


def _effective_read_timeout_sec(default_sec: float) -> float:
    raw = os.environ.get("LLM_TIMEOUT_SEC", "").strip()
    if raw:
        try:
            return max(5.0, float(raw))
        except ValueError:
            pass
    return max(5.0, float(default_sec))


def agent_config_candidates() -> list[Path]:
    """Порядок поиска ``agents.yaml``."""
    paths: list[Path] = []
    raw = os.environ.get("EIDOS_AGENTS_CONFIG", "").strip()
    if raw:
        paths.append(Path(raw).expanduser().resolve())
    paths.extend(
        [
            DATA_ROOT / "config" / "agents.yaml",
            REPO_ROOT / "config" / "agents.yaml",
            REPO_ROOT / "config" / "agents.defaults.yaml",
        ]
    )
    return paths


def find_agents_config_path() -> Path | None:
    """Первый существующий файл конфигурации или ``None``."""
    for p in agent_config_candidates():
        if p.is_file():
            return p
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    return doc if isinstance(doc, dict) else {}


def load_agents_document() -> tuple[Path | None, dict[str, Any]]:
    """Путь и документ YAML или ``(None, {})`` если файлов нет."""
    found = find_agents_config_path()
    if found is None:
        return None, {}
    return found, _load_yaml(found)


def list_profile_names() -> list[str]:
    """Имена профилей из текущего файла конфигурации (для подсказок / тестов)."""
    _, doc = load_agents_document()
    profiles = doc.get("profiles") or {}
    if not isinstance(profiles, dict):
        return []
    return sorted(str(k) for k in profiles.keys())


def _profiles_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles = doc.get("profiles") or {}
    return profiles if isinstance(profiles, dict) else {}


def _tool_routing_doc(doc: dict[str, Any]) -> dict[str, Any]:
    block = doc.get("tool_routing") or {}
    return block if isinstance(block, dict) else {}


def _tool_routing_tools(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tools = _tool_routing_doc(doc).get("tools") or {}
    return tools if isinstance(tools, dict) else {}


def _tool_routing_groups(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = _tool_routing_doc(doc).get("groups") or {}
    return groups if isinstance(groups, dict) else {}


def _tool_routing_defaults(doc: dict[str, Any]) -> dict[str, Any]:
    defaults = _tool_routing_doc(doc).get("defaults") or {}
    return defaults if isinstance(defaults, dict) else {}


def _validate_route_profile_name(
    profile_name: str,
    *,
    cfg_path: Path | None,
    doc: dict[str, Any],
    tool_name: str,
) -> str:
    from cli.llm import LLMConfigError

    profiles = _profiles_map(doc)
    clean = profile_name.strip()
    if not clean:
        raise LLMConfigError(f"Пустой профиль маршрута для инструмента {tool_name!r}.")
    if clean not in profiles:
        where = str(cfg_path) if cfg_path is not None else "<unknown>"
        avail = ", ".join(sorted(str(k) for k in profiles)) or "(пусто)"
        raise LLMConfigError(
            f"Маршрут инструмента {tool_name!r} указывает на неизвестный профиль "
            f"{clean!r} в {where}. Доступные: {avail}"
        )
    return clean


def resolve_tool_route(tool_name: str, *, group_name: str = "") -> ToolRoute | None:
    """Разрешить маршрут инструмента на профиль из YAML.

    Args:
        tool_name: Имя инструмента.
        group_name: Логическая группа инструмента для fallback.

    Returns:
        `ToolRoute` или None, если маршрут не задан.
    """
    cfg_path, doc = load_agents_document()
    if not doc:
        return None

    tools = _tool_routing_tools(doc)
    groups = _tool_routing_groups(doc)
    defaults = _tool_routing_defaults(doc)
    block = tools.get(tool_name)
    if isinstance(block, dict):
        profile_raw = str(block.get("profile") or "").strip()
        route_group = str(block.get("group") or group_name or "").strip()
        if profile_raw:
            profile = _validate_route_profile_name(
                profile_raw,
                cfg_path=cfg_path,
                doc=doc,
                tool_name=tool_name,
            )
            return ToolRoute(
                tool_name=tool_name,
                profile_name=profile,
                group_name=route_group,
                source="tool",
            )
        if route_group:
            group_block = groups.get(route_group)
            if isinstance(group_block, dict):
                profile_raw = str(group_block.get("profile") or "").strip()
                if profile_raw:
                    profile = _validate_route_profile_name(
                        profile_raw,
                        cfg_path=cfg_path,
                        doc=doc,
                        tool_name=tool_name,
                    )
                    return ToolRoute(
                        tool_name=tool_name,
                        profile_name=profile,
                        group_name=route_group,
                        source="group",
                    )

    if group_name:
        group_block = groups.get(group_name)
        if isinstance(group_block, dict):
            profile_raw = str(group_block.get("profile") or "").strip()
            if profile_raw:
                profile = _validate_route_profile_name(
                    profile_raw,
                    cfg_path=cfg_path,
                    doc=doc,
                    tool_name=tool_name,
                )
                return ToolRoute(
                    tool_name=tool_name,
                    profile_name=profile,
                    group_name=group_name,
                    source="group",
                )

    default_profile = str(defaults.get("tool_round_profile") or "").strip()
    if default_profile:
        profile = _validate_route_profile_name(
            default_profile,
            cfg_path=cfg_path,
            doc=doc,
            tool_name=tool_name,
        )
        return ToolRoute(
            tool_name=tool_name,
            profile_name=profile,
            group_name=group_name.strip(),
            source="default",
        )
    return None


def list_tool_routes(*, tool_names: list[str] | None = None) -> list[ToolRoute]:
    """Список известных маршрутов инструментов.

    Args:
        tool_names: При наличии — разрешить маршруты только для этого списка имён.

    Returns:
        Отсортированный список `ToolRoute`.
    """
    cfg_path, doc = load_agents_document()
    if not doc:
        return []

    names = tool_names
    if names is None:
        names = sorted(str(k) for k in _tool_routing_tools(doc).keys())
    routes: list[ToolRoute] = []
    seen: set[str] = set()
    for name in names:
        clean = str(name).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        route = resolve_tool_route(clean)
        if route is not None:
            routes.append(route)
    routes.sort(key=lambda r: (r.profile_name, r.tool_name))
    return routes


def resolve_profile_yaml(profile_name: str) -> LLMRuntimeParams:
    """Параметры профиля по имени из YAML.

    Raises:
        LLMConfigError: см. импорт внутри (избегаем цикла при загрузке ``cli.llm``).
    """
    from cli.llm import LLMConfigError

    name = profile_name.strip()
    if not name:
        raise LLMConfigError("Пустое имя профиля.")

    cfg_path = find_agents_config_path()
    if cfg_path is None:
        raise LLMConfigError(
            "Задан EIDOS_AGENT_PROFILE, но не найден agents.yaml "
            "(EIDOS_AGENTS_CONFIG, data/config/agents.yaml, config/agents.yaml, "
            "config/agents.defaults.yaml)."
        )

    doc = _load_yaml(cfg_path)
    profiles_raw = doc.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise LLMConfigError(f"Некорректный файл {cfg_path}: нет словаря profiles")

    block = profiles_raw.get(name)
    if not isinstance(block, dict):
        avail = ", ".join(sorted(str(k) for k in profiles_raw)) or "(пусто)"
        raise LLMConfigError(
            f"Профиль {name!r} не описан в {cfg_path}. Доступные: {avail}"
        )

    base = str(block.get("base_url") or _DEFAULT_BASE_URL).strip().rstrip("/")
    model = str(block.get("model") or _DEFAULT_MODEL).strip()

    omit = bool(block.get("omit_authorization_header", False))

    key_env_primary = str(block.get("api_key_env") or "LLM_API_KEY").strip()
    fallback_envs_raw = block.get("api_key_fallback_envs") or []
    fallback_envs: list[str] = []
    if isinstance(fallback_envs_raw, list):
        fallback_envs = [str(v).strip() for v in fallback_envs_raw if str(v).strip()]

    api_key = ""
    for var in ([key_env_primary] if key_env_primary else []) + fallback_envs:
        val = os.environ.get(var, "").strip()
        if val:
            api_key = val
            break

    if not omit and not api_key:
        envs = ", ".join([key_env_primary, *fallback_envs]) if key_env_primary else ", ".join(
            fallback_envs
        )
        raise LLMConfigError(
            f"Для профиля {name!r} задайте ключ в env ({envs}), "
            "либо включите omit_authorization_header для локальных эндпоинтов без ключа."
        )

    read_def = float(block.get("read_timeout_sec", 120))
    timeout = _effective_read_timeout_sec(read_def)

    return LLMRuntimeParams(
        api_key=api_key,
        base_url=base or _DEFAULT_BASE_URL,
        model=model or _DEFAULT_MODEL,
        read_timeout_sec=timeout,
        omit_authorization_header=omit,
        profile_name=name,
    )


def _default_profile_name(doc: dict[str, Any]) -> str:
    """Имя профиля из ``default_profile`` или ``deepseek``, если он описан в YAML."""
    raw = str(doc.get("default_profile") or "").strip()
    if raw:
        return raw
    profiles = _profiles_map(doc)
    if "deepseek" in profiles:
        return "deepseek"
    return ""


def get_llm_runtime_params(profile_name: str | None = None) -> LLMRuntimeParams:
    """Итоговые параметры: профиль YAML или только ``LLM_*`` env.

    Args:
        profile_name: Явный профиль для разового вызова. Если None — ``EIDOS_AGENT_PROFILE``,
            иначе ``default_profile`` из agents YAML, иначе legacy ``LLM_*``.
    """
    pname = (
        profile_name.strip()
        if isinstance(profile_name, str) and profile_name.strip()
        else os.environ.get("EIDOS_AGENT_PROFILE", "").strip()
    )
    if not pname:
        _, doc = load_agents_document()
        pname = _default_profile_name(doc)
    if pname:
        return resolve_profile_yaml(pname)

    api_key = (os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    base = os.environ.get("LLM_BASE_URL", _DEFAULT_BASE_URL).strip().rstrip("/")
    base = base or _DEFAULT_BASE_URL
    model = os.environ.get("LLM_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL

    timeout = _effective_read_timeout_sec(120.0)
    return LLMRuntimeParams(
        api_key=api_key,
        base_url=base,
        model=model,
        read_timeout_sec=timeout,
        omit_authorization_header=False,
        profile_name="",
    )
