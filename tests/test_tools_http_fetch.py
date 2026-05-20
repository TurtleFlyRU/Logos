"""Инструмент fetch_https_url (по умолчанию вкл.; EIDOS_HTTP_FETCH=0 выкл.)."""

from __future__ import annotations

import json

import httpx
import pytest

_RealClient = httpx.Client


def test_builtin_tools_include_fetch_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_HTTP_FETCH", raising=False)
    from cli.tools import builtin_tool_specs

    names = [s["function"]["name"] for s in builtin_tool_specs()]
    assert "fetch_https_url" in names


def test_builtin_tools_exclude_fetch_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIDOS_HTTP_FETCH", "0")
    from cli.tools import builtin_tool_specs

    names = [s["function"]["name"] for s in builtin_tool_specs()]
    assert "fetch_https_url" not in names


def test_fetch_blocks_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_HTTP_FETCH", raising=False)
    from cli.tools import execute_tool

    raw = execute_tool(
        "fetch_https_url",
        '{"url":"https://127.0.0.1/"}',
        registry=None,
    )
    payload = json.loads(raw)
    assert "error" in payload


def test_fetch_execute_mock_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_HTTP_FETCH", raising=False)
    monkeypatch.setenv("LLM_IGNORE_PROXY", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "example.net" in str(request.url.host)
        return httpx.Response(200, content=b"<html>hi</html>")

    def client_factory(**kwargs: object) -> httpx.Client:
        kwargs.pop("transport", None)
        return _RealClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("cli.tools.httpx.Client", client_factory)

    from cli.tools import execute_tool

    body = execute_tool(
        "fetch_https_url",
        '{"url":"https://example.net/doc","max_chars":500}',
        registry=None,
    )
    assert "example.net/doc" in body
    assert "200" in body
    assert "hi" in body
