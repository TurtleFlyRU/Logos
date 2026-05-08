"""Фаза 8: бюджет сообщений чата (char budget) — предсказуемое урезание."""

from __future__ import annotations

from cli.context import build_chat_messages_for_llm, chat_context_metrics, estimate_messages_chars


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


def test_total_char_budget_is_monotonic(monkeypatch, tmp_path):
    # отключаем тяжёлые блоки system ради стабильности
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос — со-исследователь.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

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


def test_old_history_is_summarized_into_system_block(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос — со-исследователь.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    # включаем фазу 8.2: summary старой истории
    monkeypatch.setenv("EIDOS_CHAT_SUMMARIZE_OLD_WM", "1")
    monkeypatch.setenv("EIDOS_CHAT_KEEP_LAST_MESSAGES", "6")
    monkeypatch.setenv("EIDOS_CHAT_SUMMARY_CHARS", "1200")
    monkeypatch.setenv("EIDOS_CHAT_TOTAL_CHARS", "4000")

    sid = "s"
    events = []
    for i in range(40):
        events.append({"role": "user", "content": f"U{i} " + ("x" * 80), "cli_session_id": sid})
        events.append({"role": "assistant", "content": f"A{i} " + ("y" * 80), "cli_session_id": sid})

    mem = _make_mem(events)
    msgs = build_chat_messages_for_llm(mem, sid)

    # system + summary system + tail + last user message
    assert msgs[0]["role"] == "system"
    assert any(m.get("role") == "system" and "Сжатая история" in str(m.get("content")) for m in msgs[1:3])
    assert msgs[-1]["role"] in ("user", "assistant")
    assert estimate_messages_chars(msgs) <= 4000


def test_layer_budget_drops_low_priority_blocks_first(monkeypatch, tmp_path):
    # Настраиваем так, чтобы extra-блоки влезали не все: active_memory должен первым пострадать.
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ATTENTION", "0")
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос — со-исследователь.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    monkeypatch.setenv("EIDOS_CHAT_LAYER_BUDGET", "1")
    monkeypatch.setenv("EIDOS_CHAT_SUMMARIZE_OLD_WM", "0")

    # Очень маленький бюджет, но с активной памятью включённой
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "1")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY_CHARS", "50000")  # намеренно огромно
    monkeypatch.setenv("EIDOS_CHAT_TOTAL_CHARS", "2200")

    sid = "s"
    events = []
    for i in range(10):
        events.append({"role": "user", "content": f"U{i} " + ("x" * 120), "cli_session_id": sid})
        events.append({"role": "assistant", "content": f"A{i} " + ("y" * 120), "cli_session_id": sid})

    mem = _make_mem(events)
    msgs = build_chat_messages_for_llm(mem, sid, user_message="test")

    # Влезли: persona + хвост истории. Блок активной памяти может не попасть из-за бюджета.
    sys_text = msgs[0]["content"]
    assert "Ты Эйдос" in sys_text
    assert estimate_messages_chars(msgs) <= 2200


def test_metrics_layers_not_triggered_by_persona(monkeypatch, tmp_path):
    # persona содержит слова «Пользователь (CLI...)» и др., но слои должны считаться
    # включёнными только если реально добавлены блоки с заголовком «— ...».
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_ATTENTION", "0")
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("Ты Эйдос — со-исследователь.\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    sid = "s"
    mem = _make_mem([])
    msgs = build_chat_messages_for_llm(mem, sid, user_message="hi")
    m = chat_context_metrics(msgs, total_budget=0)
    assert m["layers"]["identity"] is False
    assert m["layers"]["attention"] is False
    assert m["layers"]["active_memory"] is False
    assert m["layers"]["boot_snippet"] is False
    assert m["layers"]["principles"] is False

