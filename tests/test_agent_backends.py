"""Профили LLM из YAML (фаза 9a)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from cli.agent_backends import (
    get_llm_runtime_params,
    list_profile_names,
    list_tool_routes,
    resolve_profile_yaml,
    resolve_tool_route,
)
from kernel.config import REPO_ROOT


@pytest.fixture
def clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_AGENT_PROFILE", raising=False)
    monkeypatch.delenv("EIDOS_AGENTS_CONFIG", raising=False)


def test_defaults_yaml_on_path() -> None:
    p = REPO_ROOT / "config" / "agents.defaults.yaml"
    assert p.is_file(), "репозиторий должен содержать config/agents.defaults.yaml"


def test_list_profile_names_includes_deepseek(clear_profile_env, monkeypatch):
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(REPO_ROOT / "config" / "agents.defaults.yaml"))
    names = list_profile_names()
    assert "deepseek" in names
    assert "openai_compatible_local" in names


def test_resolve_deepseek_requires_key(monkeypatch, tmp_path: Path) -> None:
    from cli.llm import LLMConfigError

    cfg = tmp_path / "a.yaml"
    cfg.write_text(
        "version: 1\nprofiles:\n  p1:\n    base_url: https://x.example/v1/\n"
        "    api_key_env: MYKEY\n    model: mm\n    read_timeout_sec: 60\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))
    monkeypatch.delenv("MYKEY", raising=False)
    monkeypatch.setenv("EIDOS_AGENT_PROFILE", "p1")
    with pytest.raises(LLMConfigError):
        resolve_profile_yaml("p1")
    monkeypatch.setenv("MYKEY", "secret")
    r = resolve_profile_yaml("p1")
    assert r.api_key == "secret"
    assert r.base_url.rstrip("/") == "https://x.example/v1"
    assert r.model == "mm"
    assert r.omit_authorization_header is False


def test_get_llm_legacy_env(clear_profile_env, monkeypatch, tmp_path: Path) -> None:
    """Без YAML — только ``LLM_*`` env (legacy)."""
    cfg = tmp_path / "legacy.yaml"
    cfg.write_text("version: 1\nprofiles: {}\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://z/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    r = get_llm_runtime_params()
    assert r.api_key == "k"
    assert r.base_url.endswith("/v1")
    assert r.model == "m"
    assert r.profile_name == ""


def test_default_profile_deepseek_without_env(clear_profile_env, monkeypatch) -> None:
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(REPO_ROOT / "config" / "agents.defaults.yaml"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-secret")
    r = get_llm_runtime_params()
    assert r.profile_name == "deepseek"
    assert r.api_key == "ds-secret"
    assert "deepseek.com" in r.base_url
    assert r.model == "deepseek-chat"


def test_llm_timeout_override_over_profile(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "b.yaml"
    cfg.write_text(
        "version: 1\nprofiles:\n  slow:\n"
        "    api_key_env: K\n    model: x\n    base_url: https://a/v1\n"
        "    read_timeout_sec: 30\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))
    monkeypatch.setenv("EIDOS_AGENT_PROFILE", "slow")
    monkeypatch.setenv("K", "k")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "99")
    r = get_llm_runtime_params()
    assert r.read_timeout_sec == 99.0


def test_chat_completions_omits_auth_for_local_profile(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(REPO_ROOT / "config" / "agents.defaults.yaml"))
    monkeypatch.setenv("EIDOS_AGENT_PROFILE", "openai_compatible_local")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        assert "/chat/completions" in str(request.url)
        json.loads(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    from cli.llm import chat_completions

    text = chat_completions([{"role": "user", "content": "?"}], client=client)
    assert text == "ok"
    assert captured.get("auth") is None


def test_resolve_tool_route_from_group_fallback(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "routes.yaml"
    cfg.write_text(
        "version: 1\n"
        "profiles:\n"
        "  main:\n"
        "    api_key_env: MAIN_KEY\n"
        "    base_url: https://main.example/v1\n"
        "    model: main-model\n"
        "  local:\n"
        "    api_key_env: LOCAL_KEY\n"
        "    base_url: http://127.0.0.1:11434/v1\n"
        "    model: local-model\n"
        "    omit_authorization_header: true\n"
        "tool_routing:\n"
        "  groups:\n"
        "    browser:\n"
        "      profile: local\n"
        "  tools:\n"
        "    browser_open:\n"
        "      group: browser\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))
    route = resolve_tool_route("browser_open", group_name="browser")
    assert route is not None
    assert route.profile_name == "local"
    assert route.group_name == "browser"
    assert route.source == "group"


def test_list_tool_routes_includes_defaults_yaml_browser_routes(monkeypatch) -> None:
    monkeypatch.setenv(
        "EIDOS_AGENTS_CONFIG",
        str(REPO_ROOT / "config" / "agents.defaults.yaml"),
    )
    routes = list_tool_routes(
        tool_names=["read_workspace_file", "fetch_https_url", "browser_open", "bash"]
    )
    assert {route.tool_name for route in routes} == {
        "read_workspace_file",
        "fetch_https_url",
        "browser_open",
        "bash",
    }
    assert {route.profile_name for route in routes} == {"openai_compatible_local"}


def test_resolve_tool_route_bad_profile_raises(monkeypatch, tmp_path: Path) -> None:
    from cli.llm import LLMConfigError

    cfg = tmp_path / "bad-routes.yaml"
    cfg.write_text(
        "version: 1\n"
        "profiles:\n"
        "  main:\n"
        "    api_key_env: MAIN_KEY\n"
        "    base_url: https://main.example/v1\n"
        "    model: main-model\n"
        "tool_routing:\n"
        "  tools:\n"
        "    read_workspace_file:\n"
        "      profile: missing_profile\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))
    with pytest.raises(LLMConfigError):
        resolve_tool_route("read_workspace_file")
