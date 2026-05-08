"""Фаза 8: бюджет сообщений чата (char budget) — предсказуемое урезание."""

from __future__ import annotations

from cli.context import build_chat_messages_for_llm, estimate_messages_chars


class _Ep:
    def query_all(self, **_kwargs):
        return []

    def query(self, **_kwargs):
        return []


class _Ext:
    def search(self, *_a, **_kw):
        return []


def _make_mem(events: list[dict]):
    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {"events": events, "context": {}, "attention_slots": []}

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep()
        external = _Ext()

    return Mem()


def test_total_char_budget_is_monotonic(monkeypatch):
    # отключаем тяжёлые блоки system ради стабильности
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    sid = "s"
    events = []
    for i in range(60):
        events.append({"role": "user", "content": f"u{i} " + ("x" * 50), "cli_session_id": sid})
        events.append({"role": "assistant", "content": f"a{i} " + ("y" * 50), "cli_session_id": sid})

    mem = _make_mem(events)

    monkeypatch.setenv("EIDOS_CHAT_TOTAL_CHARS", "5000")
    m_small = build_chat_messages_for_llm(mem, sid)
    small = estimate_messages_chars(m_small)
    assert small <= 5000

    monkeypatch.setenv("EIDOS_CHAT_TOTAL_CHARS", "15000")
    m_big = build_chat_messages_for_llm(mem, sid)
    big = estimate_messages_chars(m_big)
    assert big <= 15000

    # монотонность: больше бюджета -> не меньше content в сумме
    assert big >= small

