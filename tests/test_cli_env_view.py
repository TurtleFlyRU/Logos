"""Тесты отображения env-настроек CLI."""

from __future__ import annotations

import pytest

from kernel.config import REPO_ROOT


def test_format_cli_env_report_masks_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_AGENT_PROFILE", "local")
    monkeypatch.setenv("LLM_API_KEY", "super-secret")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_PROXY_PASSWORD", "p@ss")

    from cli.env_view import format_cli_env_report

    text = format_cli_env_report(show_unset=False)
    assert "EIDOS_AGENT_PROFILE=local" in text
    assert "LLM_API_KEY=<set>" in text
    assert "super-secret" not in text
    assert "EIDOS_PLAYWRIGHT_PROXY_PASSWORD=<set>" in text


def test_format_cli_env_report_shows_unset_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EIDOS_PLAYWRIGHT", raising=False)

    from cli.env_view import format_cli_env_report

    text = format_cli_env_report(show_unset=True)
    assert "EIDOS_PLAYWRIGHT=<unset>" in text


def test_format_cli_env_report_includes_tool_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "EIDOS_AGENTS_CONFIG",
        str(REPO_ROOT / "config" / "agents.defaults.yaml"),
    )

    from cli.env_view import format_cli_env_report

    text = format_cli_env_report(show_unset=False)
    assert "[tool_routing]" in text
    assert "read_workspace_file -> openai_compatible_local" in text
