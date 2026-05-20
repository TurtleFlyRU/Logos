"""Тесты выбора профиля для tool-aware раундов."""

from __future__ import annotations

import pytest

from kernel.config import REPO_ROOT


def test_resolve_tool_round_route_uses_local_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EIDOS_AGENTS_CONFIG",
        str(REPO_ROOT / "config" / "agents.defaults.yaml"),
    )
    route = None

    from cli.tool_routing import resolve_tool_round_route

    route = resolve_tool_round_route(
        ["eidos_echo", "read_workspace_file", "fetch_https_url", "browser_open"]
    )
    assert route is not None
    assert route.profile_name == "openai_compatible_local"
    assert route.runtime_params.profile_name == "openai_compatible_local"
    assert set(route.matched_tools) == {
        "read_workspace_file",
        "fetch_https_url",
        "browser_open",
    }


def test_resolve_tool_round_route_text_only_returns_none() -> None:
    from cli.tool_routing import resolve_tool_round_route

    assert resolve_tool_round_route(["eidos_echo"]) is None


def test_resolve_tool_round_route_conflicting_profiles_raise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    cfg = tmp_path / "tool-routing.yaml"
    cfg.write_text(
        "version: 1\n"
        "profiles:\n"
        "  main:\n"
        "    api_key_env: MAIN_KEY\n"
        "    base_url: https://main.example/v1\n"
        "    model: main-model\n"
        "  local_a:\n"
        "    api_key_env: LOCAL_A\n"
        "    base_url: http://127.0.0.1:11434/v1\n"
        "    model: local-a\n"
        "    omit_authorization_header: true\n"
        "  local_b:\n"
        "    api_key_env: LOCAL_B\n"
        "    base_url: http://127.0.0.1:1234/v1\n"
        "    model: local-b\n"
        "    omit_authorization_header: true\n"
        "tool_routing:\n"
        "  tools:\n"
        "    read_workspace_file:\n"
        "      profile: local_a\n"
        "    fetch_https_url:\n"
        "      profile: local_b\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(cfg))

    from cli.tool_routing import resolve_tool_round_route

    with pytest.raises(RuntimeError):
        resolve_tool_round_route(["read_workspace_file", "fetch_https_url"])
