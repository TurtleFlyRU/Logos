"""Тесты сборки контекста CLI."""

from __future__ import annotations

from cli.context import wm_events_to_chat_messages


def test_wm_events_filters_session_and_role():
    events = [
        {"role": "user", "content": "a", "cli_session_id": "s1"},
        {"role": "assistant", "content": "b", "cli_session_id": "s1"},
        {"role": "user", "content": "other", "cli_session_id": "s2"},
        {"role": "system", "content": "x", "cli_session_id": "s1"},
    ]
    msgs = wm_events_to_chat_messages(events, "s1")
    assert msgs == [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]


def test_wm_events_truncates_tail():
    events = [
        {"role": "user", "content": str(i), "cli_session_id": "s"}
        for i in range(50)
    ]
    msgs = wm_events_to_chat_messages(events, "s", max_messages=10)
    assert len(msgs) == 10
    assert msgs[-1]["content"] == "49"
