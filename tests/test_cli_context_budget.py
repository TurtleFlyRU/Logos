"""Фаза 8: бюджет сообщений чата (char budget) — предсказуемое урезание."""

from __future__ import annotations

from cli.context import (
    approx_prompt_tokens_from_chars,
    build_chat_messages_for_llm,
    chat_context_metrics,
    estimate_messages_chars,
    format_cli_wm_plan_and_session_block,
    format_context_metrics_sizes,
    _finalize_messages_for_chat_api,
    _render_compact_history_summary,
)


class _Ep:
    def query_all(self, **_kwargs):
        return []

    def query(self, **_kwargs):
        return []


class _Ext:
    def search(self, *_a, **_kw):
        return []


def _make_mem(events: list[dict], context: dict | None = None):
    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {
            "events": events,
            "context": dict(context) if context else {},
            "attention_slots": [],
        }

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

    # summary вшит в единственный system-блок, чтобы не ломать llama.cpp chat templates
    assert msgs[0]["role"] == "system"
    assert "Сжатая история" in str(msgs[0]["content"])
    assert sum(1 for m in msgs if m.get("role") == "system") == 1
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
    assert sum(m["layer_chars"].values()) == estimate_messages_chars(msgs)
    assert m["history_chars"] == 0
    assert m["approx_prompt_tokens"] == approx_prompt_tokens_from_chars(len(str(msgs[0]["content"])))


def test_approx_prompt_tokens_from_chars_zero_and_rounding():
    assert approx_prompt_tokens_from_chars(0) == 0
    assert approx_prompt_tokens_from_chars(1) == 1
    assert approx_prompt_tokens_from_chars(4) == 1
    assert approx_prompt_tokens_from_chars(5) == 2


def test_chat_context_metrics_layer_chars_split_balances_persona_extra():
    body = (
        "PERSONA_STUB\n\n"
        "— Пользователь (CLI, явно указано в диалоге): имя — Инна.\n"
        "\n"
        "— Слоты внимания (WM):\n"
        "  • [user] ping\n"
    )
    msgs = [{"role": "system", "content": body}]
    m = chat_context_metrics(msgs, total_budget=0)
    lc = m["layer_chars"]
    assert lc["persona"] == len("PERSONA_STUB") + 2  # к persona относится ``\\n\\n`` перед extra
    assert lc["identity"] > 0
    assert lc["attention"] > 0
    assert sum(lc.values()) == len(body)


def test_chat_context_metrics_history_wm_summary_chars():
    sum_block = "— Сжатая история (ранние реплики):\n  [user] hi\n"
    sys0 = "P\n\n— Пользователь (CLI, явно указано в диалоге): имя — Z.\n\n" + sum_block
    msgs = [
        {"role": "system", "content": sys0},
        {"role": "user", "content": "hello"},
    ]
    m = chat_context_metrics(msgs, total_budget=0)
    expected_summary_chars = len("\n\n" + sum_block)
    assert m["history_chars"] == len("hello")
    assert m["wm_summary_chars"] == expected_summary_chars
    assert m["approx_layer_tokens"]["wm_summary"] == approx_prompt_tokens_from_chars(
        expected_summary_chars
    )
    assert (
        sum(m["layer_chars"].values())
        + m["history_chars"]
        == len(sys0) + len("hello")
    )


def test_cli_plan_block_when_context_set():
    class _WM:
        data = {
            "events": [],
            "context": {"cli_current_plan": "Шаг 1: проверить сборку."},
            "attention_slots": [],
        }

    class _Mem:
        working = _WM()

    text = format_cli_wm_plan_and_session_block(_Mem())
    assert "— Фокус и план (CLI, WM):" in text
    assert "Шаг 1" in text


def test_build_chat_messages_includes_cli_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    monkeypatch.delenv("EIDOS_CHAT_USER_IDENTITY", raising=False)
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("PERSONA\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    sid = "s"
    mem = _make_mem(
        [],
        context={
            "session_title": "CLI тест",
            "cli_current_plan": "Сделать X.",
        },
    )
    msgs = build_chat_messages_for_llm(mem, sid, user_message="hi")
    sys0 = str(msgs[0]["content"])
    assert "— Фокус и план (CLI, WM):" in sys0
    assert "CLI тест" in sys0 and "Сделать X." in sys0
    metrics = chat_context_metrics(msgs, total_budget=0)
    assert metrics["layers"]["wm_plan_focus"] is True
    assert metrics["layer_chars"].get("wm_plan_focus", 0) > 0


def test_cli_plan_disabled_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOS_CHAT_CLI_PLAN", "0")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")
    monkeypatch.setenv("EIDOS_CHAT_USER_IDENTITY", "0")
    persona = tmp_path / "AGENTS.md"
    persona.write_text("PERSONA\n", encoding="utf-8")
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))

    mem = _make_mem([], context={"cli_current_plan": "hidden"})
    msgs = build_chat_messages_for_llm(mem, "s", user_message="x")
    assert "hidden" not in str(msgs[0]["content"])


def test_metrics_principles_detected_when_header_has_paren_suffix():
    sys0 = (
        "PERSONA_STUB\n\n"
        "— Принципы (семантическая память):\n"
        "  • [0.90] принцип тестовый\n"
    )
    m = chat_context_metrics([{"role": "system", "content": sys0}], total_budget=0)
    assert m["layers"]["principles"] is True
    assert m["layer_chars"].get("principles", 0) > 0


def test_layer_split_keeps_unknown_mdash_inside_active_block(monkeypatch, tmp_path):
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(tmp_path / "agents.md"))
    (tmp_path / "agents.md").write_text("P\n", encoding="utf-8")
    active = (
        "— Активное извлечение из памяти (pipeline=x):\n"
        "  · строка данных\n\n"
        "Подпункт внутри блока может начинаться с тире — это не заголовок слоя.\n"
        "\n\n"
        "— Неизвестный заголовок без известных префиксов остаётся внутри куска active.\n"
    )
    sys0 = "P\n\n" + active
    m = chat_context_metrics([{"role": "system", "content": sys0}], total_budget=0)
    assert m["layer_chars"]["active_memory"] > len("— Активное извлечение из памяти") + 50
    assert m["layer_chars"]["other"] == 0


def test_finalize_messages_drops_tool_without_assistant_tool_calls():
    msgs = [
        {"role": "system", "content": "persona"},
        {"role": "tool", "tool_call_id": "call_1", "content": "orphan"},
        {"role": "user", "content": "hello"},
    ]
    out = _finalize_messages_for_chat_api(msgs)
    assert [m["role"] for m in out] == ["system", "user"]


def test_finalize_messages_keeps_tool_after_tool_calls_assistant():
    tc = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "eidos_echo", "arguments": "{}"},
        }
    ]
    msgs = [
        {"role": "system", "content": "persona"},
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": None, "tool_calls": tc},
        {"role": "tool", "tool_call_id": "call_1", "content": "{}"},
        {"role": "assistant", "content": "done"},
    ]
    out = _finalize_messages_for_chat_api(msgs)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool", "assistant"]


def test_wm_summary_compress_changes_output(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_WM_SUMMARY_STYLE", "compress")
    long_sentences = (
        "Это первое достаточно длинное предложение про контекст и память модели здесь. "
        "Это второе предложение тоже длиннее сорока символов для фильтра compress. "
        "Это третий фрагмент с подробным описанием сценария тестирования CLI. "
    )
    hist = [{"role": "user", "content": long_sentences}]
    compressed = _render_compact_history_summary(hist, max_chars=4000)

    monkeypatch.setenv("EIDOS_CHAT_WM_SUMMARY_STYLE", "timeline")
    plain = _render_compact_history_summary(hist, max_chars=4000)

    assert compressed != plain
    assert "Сжатая история" in compressed and "Сжатая история" in plain


def test_format_context_metrics_sizes_joins_nonempty():
    m = chat_context_metrics(
        [
            {
                "role": "system",
                "content": "P\n\n— Пользователь (CLI, явно указано в диалоге): имя — Ю.\n",
            },
            {"role": "user", "content": "yo"},
        ],
        total_budget=0,
    )
    s = format_context_metrics_sizes(m)
    assert "persona=" in s
    assert "id=" in s
    assert "hist=" in s

