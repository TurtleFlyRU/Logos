"""Разбор slash-команд пайплайна для ``eidos chat``."""

from __future__ import annotations

import pytest

from cli.pipelines.chat_commands import ChatPipelineArgs, format_chat_pipeline_help, parse_chat_pipeline_line


def test_parse_pipeline_research_rest() -> None:
    parsed = parse_chat_pipeline_line("/pipeline research тема с пробелами")
    assert isinstance(parsed, ChatPipelineArgs)
    assert parsed.name == "research"
    assert parsed.topic == "тема с пробелами"
    assert parsed.paths == ()


def test_parse_run_alias() -> None:
    parsed = parse_chat_pipeline_line('/run experiment "один блок" хвост')
    assert isinstance(parsed, ChatPipelineArgs)
    assert parsed.name == "experiment"
    assert "один блок" in parsed.topic
    assert "хвост" in parsed.topic


def test_parse_review_shorthand() -> None:
    parsed = parse_chat_pipeline_line(
        '/review --paths README.md --paths AGENTS.md "стиль документации"'
    )
    assert isinstance(parsed, ChatPipelineArgs)
    assert parsed.name == "code_review"
    assert parsed.paths == ("README.md", "AGENTS.md")
    assert "стиль документации" in parsed.topic


def test_parse_help_literals() -> None:
    assert parse_chat_pipeline_line("/pipeline") == "help"
    assert parse_chat_pipeline_line("/pipeline help") == "help"
    assert parse_chat_pipeline_line("/review help") == "help"
    assert parse_chat_pipeline_line("/review --help") == "help"
    assert parse_chat_pipeline_line("hello") is None


@pytest.fixture()
def limited_pipelines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cli.pipelines.chat_commands._known_pipelines",
        lambda: frozenset({"research"}),
    )


def test_parse_unknown_pipeline(limited_pipelines: None) -> None:
    parsed = parse_chat_pipeline_line("/pipeline foo x")
    assert isinstance(parsed, str)
    assert "foo" in parsed


def test_format_help_contains_run() -> None:
    txt = format_chat_pipeline_help()
    assert "/pipeline" in txt and "/run" in txt
