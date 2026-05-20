"""Тесты именованных пайплайнов (фаза 9b)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cli.agent_backends import get_llm_runtime_params
from cli.pipelines.presets import pipeline_preset, preset_names
from cli.pipelines.runner import run_pipeline


@pytest.fixture(autouse=True)
def _pipeline_env_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_AGENT_PROFILE", raising=False)
    monkeypatch.delenv("EIDOS_AGENTS_CONFIG", raising=False)
    monkeypatch.delenv("EIDOS_CODE_REVIEW_PROFILES", raising=False)


def test_preset_names_contains_core() -> None:
    pn = preset_names()
    assert "research" in pn
    assert "experiment" in pn
    assert "code_review" in pn


def test_pipeline_preset_restores_wm_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIDOS_CHAT_WM_MESSAGES", "7")
    with pipeline_preset("research"):
        assert os.environ["EIDOS_CHAT_WM_MESSAGES"] == "56"
    assert os.environ["EIDOS_CHAT_WM_MESSAGES"] == "7"


def test_code_review_swaps_profiles_per_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOGOS_DATA_ROOT", str(tmp_path))
    agents = tmp_path / "agents.yaml"
    agents.write_text(
        """version: 1
profiles:
  pa:
    base_url: "https://example.com/v1"
    api_key_env: LLM_API_KEY
    model: "stage-model-a"
  pb:
    base_url: "https://example.com/v1"
    api_key_env: LLM_API_KEY
    model: "stage-model-b"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_AGENTS_CONFIG", str(agents))
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("EIDOS_CODE_REVIEW_PROFILES", "pa,pb")

    seq: list[tuple[str, str]] = []

    def fake_chat(
        _messages: list[dict[str, str]],
        *,
        client: object = None,
        timeout: float | None = None,
    ) -> str:
        cfg = get_llm_runtime_params()
        seq.append((cfg.profile_name, cfg.model))
        return f"reply-{cfg.profile_name}"

    exit_code = run_pipeline(
        "code_review",
        "проверь формулировки",
        paths=[],
        stub=False,
        no_boot=True,
        chat_completions=fake_chat,
    )
    assert exit_code == 0
    assert seq == [
        ("pa", "stage-model-a"),
        ("pb", "stage-model-b"),
    ]
