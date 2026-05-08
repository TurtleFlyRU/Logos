"""Тесты HTTP-клиента LLM с mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from cli.llm import chat_completions, llm_settings


def test_llm_settings_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1/")
    monkeypatch.setenv("LLM_MODEL", "m1")
    key, base, model = llm_settings()
    assert key == "x"
    assert base == "https://example.com/v1"
    assert model == "m1"


def test_format_llm_pending_banner(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.delenv("LLM_IGNORE_PROXY", raising=False)
    from cli.llm import format_llm_pending_banner

    line = format_llm_pending_banner()
    assert "api.deepseek.com" in line
    assert "deepseek-chat" in line
    assert "таймаут чтения" in line
    assert "прокси из env:" in line


def test_chat_completions_with_mock(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.test/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/chat/completions" in str(request.url)
        body = json.loads(request.content.decode())
        assert body["model"]
        assert body["messages"]
        assert body.get("stream") is False
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ответ"}}]},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    text = chat_completions(
        [{"role": "user", "content": "hi"}],
        client=client,
    )
    assert text == "ответ"


def test_chat_completions_empty_choices_raises(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.test/v1")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    from cli.llm import LLMConfigError

    with pytest.raises(LLMConfigError):
        chat_completions([{"role": "user", "content": "x"}], client=client)
