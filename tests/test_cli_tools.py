"""Тесты инструментов CLI и цикла tool_calls (фаза 4)."""

from __future__ import annotations

import json

import httpx

import kernel.config


def test_execute_tool_echo():
    from cli.tools import execute_tool

    assert execute_tool("eidos_echo", '{"text": "ping"}', registry=None) == "ping"


def test_execute_tool_unknown():
    from cli.tools import execute_tool

    out = execute_tool("nope", "{}", registry=None)
    assert "error" in json.loads(out)


def test_assistant_message_for_api_tool_calls():
    from cli.tools import assistant_message_for_api

    msg = assistant_message_for_api(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "eidos_echo", "arguments": "{}"},
                }
            ],
        }
    )
    assert msg["role"] == "assistant"
    assert msg["content"] is None
    assert len(msg["tool_calls"]) == 1


def test_wm_events_includes_tool_messages():
    from cli.context import wm_events_to_chat_messages

    events = [
        {"role": "user", "content": "u", "cli_session_id": "s"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "eidos_echo", "arguments": '{"text":"x"}'},
                }
            ],
            "cli_session_id": "s",
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "content": "x",
            "cli_session_id": "s",
        },
        {"role": "assistant", "content": "final", "cli_session_id": "s"},
    ]
    msgs = wm_events_to_chat_messages(events, "s")
    assert msgs[0] == {"role": "user", "content": "u"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["tool_calls"]
    assert msgs[2]["role"] == "tool"
    assert msgs[2]["tool_call_id"] == "c1"
    assert msgs[3] == {"role": "assistant", "content": "final"}


def test_chat_completion_assistant_message_parses_tool_calls(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.test/v1")

    tool_calls = [
        {
            "id": "call_a",
            "type": "function",
            "function": {"name": "eidos_echo", "arguments": '{"text":"z"}'},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": tool_calls,
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    from cli.llm import chat_completion_assistant_message

    msg = chat_completion_assistant_message(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "eidos_echo"}}],
        client=client,
    )
    assert msg.get("tool_calls") == tool_calls


def test_cli_chat_llm_reply_two_rounds(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel.config, "INSTRUMENTAL_DB_PATH", tmp_path / "tools.db")
    monkeypatch.setenv("EIDOS_TOOLS", "1")

    calls = []

    def fake_amsg(messages, **kwargs):
        calls.append(len(messages))
        if len(calls) == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "t1",
                        "type": "function",
                        "function": {
                            "name": "eidos_echo",
                            "arguments": '{"text":"step"}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr("cli.llm.chat_completion_assistant_message", fake_amsg)

    class FakeWM:
        def __init__(self) -> None:
            self.events: list = []
            self.data = {"events": self.events}

        def add_event(self, ev):
            self.events.append(ev)

    class FakeMem:
        def __init__(self) -> None:
            self.working = FakeWM()

    mem = FakeMem()
    from cli.runtime import _cli_chat_llm_reply

    text = _cli_chat_llm_reply(
        mem,
        "sid",
        ["cli", "eidos"],
        [{"role": "user", "content": "ping"}],
    )
    assert text == "done"
    roles = [e["role"] for e in mem.working.events]
    assert roles == ["assistant", "tool"]
    assert len(calls) == 2


def test_cli_chat_llm_reply_identity_skips_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel.config, "INSTRUMENTAL_DB_PATH", tmp_path / "tools.db")
    monkeypatch.setenv("EIDOS_TOOLS", "1")

    captured: list[Any] = []

    def fake_amsg(messages, **kwargs):
        captured.append(kwargs.get("tools"))
        return {"role": "assistant", "content": "из памяти"}

    monkeypatch.setattr("cli.llm.chat_completion_assistant_message", fake_amsg)

    class FakeWM:
        def __init__(self) -> None:
            self.events: list = []
            self.data = {"events": self.events}

        def add_event(self, ev):
            self.events.append(ev)

    class FakeMem:
        def __init__(self) -> None:
            self.working = FakeWM()

    mem = FakeMem()
    from cli.runtime import _cli_chat_llm_reply

    text = _cli_chat_llm_reply(
        mem,
        "sid",
        ["cli", "eidos"],
        [{"role": "user", "content": "x"}],
        allow_tools=False,
    )
    assert text == "из памяти"
    assert captured == [None]
    assert mem.working.events == []
