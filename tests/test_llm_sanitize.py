"""Санитизация Gemma thinking / inline tool_call в ответах LLM."""

from __future__ import annotations

import json

import pytest

from cli.llm_sanitize import (
    normalize_assistant_message,
    sanitize_assistant_text,
    strip_model_channels,
)


def test_strip_thought_channel() -> None:
    raw = (
        "<|channel>thought\n"
        "internal reasoning here\n"
        "<|channel>final\n"
        "Видимый ответ пользователю."
    )
    assert strip_model_channels(raw) == "Видимый ответ пользователю."


def test_strip_thought_until_tool_call() -> None:
    raw = "<|channel>thought\nplanning\n<|tool_call>call:bash{command:x}<tool_call|>"
    assert strip_model_channels(raw) == ""


def test_parse_inline_tool_call_browser_snapshot() -> None:
    raw = (
        "<|channel>thought\n"
        "long plan\n"
        "<|tool_call>call:browser_snapshot{max_chars:10000,selector:<|\"|>div.traffic<|\"|>}"
        "<tool_call|>"
    )
    content, calls = sanitize_assistant_text(raw)
    assert content == ""
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "browser_snapshot"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["max_chars"] == 10000
    assert "motion" in args["selector"] or "div" in args["selector"]


def test_normalize_assistant_message_promotes_tool_calls() -> None:
    msg = {
        "role": "assistant",
        "content": (
            "<|channel>thought\n"
            "hidden\n"
            "<|tool_call>call:read_workspace_file{path:README.md}<tool_call|>"
        ),
    }
    out = normalize_assistant_message(msg)
    assert out.get("tool_calls")
    assert out["tool_calls"][0]["function"]["name"] == "read_workspace_file"
    assert out.get("content") in (None, "")


def test_normalize_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIDOS_STRIP_MODEL_THOUGHT", "0")
    raw = "<|channel>thought\nsecret\n<|channel>final\nok"
    msg = {"role": "assistant", "content": raw}
    assert normalize_assistant_message(msg)["content"] == raw
