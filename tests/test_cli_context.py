"""Тесты сборки контекста CLI."""

from __future__ import annotations

from cli.context import build_chat_messages_for_llm, wm_events_to_chat_messages


def test_wm_events_filters_session_and_role():
    events = [
        {"role": "user", "content": "a", "cli_session_id": "s1"},
        {"role": "assistant", "content": "b", "cli_session_id": "s1"},
        {"role": "user", "content": "other", "cli_session_id": "s2"},
        {"role": "system", "content": "x", "cli_session_id": "s1"},
    ]
    msgs = wm_events_to_chat_messages(events, "s1")
    assert msgs == [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]


def test_wm_events_truncates_tail():
    events = [
        {"role": "user", "content": str(i), "cli_session_id": "s"} for i in range(50)
    ]
    msgs = wm_events_to_chat_messages(events, "s", max_messages=10)
    assert len(msgs) == 10
    assert msgs[-1]["content"] == "49"


def test_build_chat_messages_system_and_history(monkeypatch):
    monkeypatch.delenv("EIDOS_CHAT_BOOT_SNIPPET", raising=False)

    class Sem:
        def get_principles(self, **_kwargs):
            return [{"principle": "учиться на ошибках", "confidence": 0.95}]

    class WM:
        data = {
            "events": [
                {"role": "user", "content": "привет", "cli_session_id": "sid"},
            ],
            "context": {},
            "attention_slots": [],
        }

    class Mem:
        working = WM()
        semantic = Sem()

    msgs = build_chat_messages_for_llm(
        Mem(),
        "sid",
        user_message="привет",
    )
    assert msgs[0]["role"] == "system"
    assert "Эйдос" in msgs[0]["content"]
    assert "учиться на ошибках" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "привет"}


def test_build_chat_messages_principles_disabled(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.delenv("EIDOS_CHAT_BOOT_SNIPPET", raising=False)

    class Sem:
        def get_principles(self, **_kwargs):
            return [{"principle": "x", "confidence": 0.99}]

    class WM:
        data = {"events": [], "context": {}, "attention_slots": []}

    class Mem:
        working = WM()
        semantic = Sem()

    msgs = build_chat_messages_for_llm(Mem(), "sid")
    assert "Принципы" not in msgs[0]["content"]
