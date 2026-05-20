"""Тесты отображения budget/fill в CLI."""

from __future__ import annotations

import pytest


def _make_mem(events: list[dict], context: dict | None = None):
    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        AUTO_SLEEP_THRESHOLD = 50
        data = {
            "events": events,
            "context": dict(context) if context else {},
            "attention_slots": [],
            "event_count": len(events),
        }

    class Ep:
        def query_all(self, **_kwargs):
            return []

        def query(self, **_kwargs):
            return []

    class Ext:
        def search(self, *_a, **_kw):
            return []

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = Ep()
        external = Ext()

    return Mem()


def test_format_chat_budget_report_capped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EIDOS_CHAT_TOTAL_CHARS", "5000")
    monkeypatch.setenv("EIDOS_CHAT_WM_MESSAGES", "12")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ATTENTION", "0")
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    sid = "s"
    events = [
        {"role": "user", "content": "hello world", "cli_session_id": sid},
        {"role": "assistant", "content": "reply text", "cli_session_id": sid},
    ]
    mem = _make_mem(events)

    from cli.budget_view import format_chat_budget_report

    text = format_chat_budget_report(mem, sid)
    assert "[budget]" in text
    assert "5000" in text
    assert "wm_messages=12" in text
    assert "auto_sleep: 2/50 events (remaining=48)" in text
    assert "split:" in text


def test_format_chat_budget_report_uncapped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("EIDOS_CHAT_TOTAL_CHARS", raising=False)
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ATTENTION", "0")
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    mem = _make_mem([])

    from cli.budget_view import format_chat_budget_report

    text = format_chat_budget_report(mem, "s")
    assert "uncapped" in text
    assert "auto_sleep: 0/50 events (remaining=50)" in text
