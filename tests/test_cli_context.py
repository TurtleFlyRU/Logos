"""Тесты сборки контекста CLI."""

from __future__ import annotations

from cli.context import (
    build_chat_messages_for_llm,
    tools_allowed_for_chat_line,
    wm_events_to_chat_messages,
)


class _Ep:
    """Эпизодическая память для моков: полный скан через query_all."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def query_all(self, min_salience: float = 0.0, max_rows: int | None = None):
        del min_salience
        if max_rows is None:
            return list(self._rows)
        return self._rows[:max_rows]

    def query(self, limit: int = 50, min_salience: float = 0.0):
        del min_salience
        return self._rows[:limit]


class _Ext:
    def search(self, *_a, **_kw):
        return []


def test_tools_allowed_for_chat_line_identity(monkeypatch):
    monkeypatch.delenv("EIDOS_CHAT_TOOLS_ON_IDENTITY", raising=False)

    assert tools_allowed_for_chat_line("кто я") is False
    assert tools_allowed_for_chat_line("прочитай README.md и summary") is True


def test_tools_on_identity_env_overrides(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_TOOLS_ON_IDENTITY", "1")

    assert tools_allowed_for_chat_line("кто я") is True


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
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

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
        episodic = _Ep([])
        external = _Ext()

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
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    class Sem:
        def get_principles(self, **_kwargs):
            return [{"principle": "x", "confidence": 0.99}]

    class WM:
        data = {"events": [], "context": {}, "attention_slots": []}

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep([])
        external = _Ext()

    msgs = build_chat_messages_for_llm(Mem(), "sid")
    assert "Принципы" not in msgs[0]["content"]


def test_build_chat_messages_includes_boot_snippet(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.delenv("EIDOS_CHAT_BOOT_SNIPPET_CHARS", raising=False)
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {
            "events": [],
            "context": {"boot_context": "snippet-from-boot-pipeline"},
            "attention_slots": [],
        }

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep([])
        external = _Ext()

    msgs = build_chat_messages_for_llm(Mem(), "sid")
    assert "snippet-from-boot-pipeline" in msgs[0]["content"]
    assert "Фрагмент сохранённого boot" in msgs[0]["content"]


def test_build_chat_messages_boot_snippet_disabled(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {
            "events": [],
            "context": {"boot_context": "hidden-snippet"},
            "attention_slots": [],
        }

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep([])
        external = _Ext()

    msgs = build_chat_messages_for_llm(Mem(), "sid")
    assert "hidden-snippet" not in msgs[0]["content"]


def test_active_memory_retrieval_keyword_match(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    rows = [
        {
            "id": 1,
            "timestamp": 1_699_000_000,
            "summary": "noise",
            "raw_text": "old irrelevant",
            "salience": 0.5,
        },
        {
            "id": 42,
            "timestamp": 1_700_000_000,
            "summary": "",
            "raw_text": "Пользователь представился: меня зовут Александр.",
            "salience": 0.5,
        },
    ]

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {"events": [], "context": {}, "attention_slots": []}

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep(rows)
        external = _Ext()

    msgs = build_chat_messages_for_llm(
        Mem(), "sid", user_message="как меня зовут напомни"
    )
    assert "Активное извлечение из памяти" in msgs[0]["content"]
    assert "2 записей в выборке" in msgs[0]["content"]
    assert "Александр" in msgs[0]["content"]


def test_active_memory_disabled(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {"events": [], "context": {}, "attention_slots": []}

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep(
            [
                {
                    "id": 99,
                    "timestamp": 1_700_000_000,
                    "summary": "",
                    "raw_text": "секретное имя Зета",
                    "salience": 0.9,
                }
            ]
        )
        external = _Ext()

    msgs = build_chat_messages_for_llm(Mem(), "sid", user_message="Зета")
    assert "(pipeline=" not in msgs[0]["content"]
    assert "Зета" not in msgs[0]["content"]


def test_who_am_i_uses_wm_tail_for_episode_cues(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_MEMORY_PIPELINE", "episodic_only")

    sid = "sess-1"
    rows: list[dict] = []
    base_ts = 1_700_000_000
    for i in range(12):
        rows.append(
            {
                "id": i + 1,
                "timestamp": float(base_ts + i),
                "summary": "",
                "raw_text": f"служебный шум сообщение {i}",
                "salience": 0.5,
            }
        )
    rows.append(
        {
            "id": 99,
            "timestamp": 1_698_000_000,
            "summary": "[user]",
            "raw_text": "меня зовут Сергей, это для теста cues из WM",
            "salience": 0.55,
        }
    )

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {
            "events": [
                {
                    "role": "user",
                    "content": "меня зовут Сергей",
                    "cli_session_id": sid,
                },
                {
                    "role": "user",
                    "content": "кто я",
                    "cli_session_id": sid,
                },
            ],
            "context": {},
            "attention_slots": [],
        }

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep(rows)
        external = _Ext()

    msgs = build_chat_messages_for_llm(
        Mem(),
        sid,
        user_message="кто я",
    )
    assert "Сергей" in msgs[0]["content"]
    assert "Активное извлечение из памяти" in msgs[0]["content"]


def test_user_identity_block_from_context(monkeypatch):
    monkeypatch.setenv("EIDOS_CHAT_PRINCIPLES", "0")
    monkeypatch.setenv("EIDOS_CHAT_BOOT_SNIPPET", "0")
    monkeypatch.setenv("EIDOS_CHAT_ACTIVE_MEMORY", "0")

    class Sem:
        def get_principles(self, **_kwargs):
            return []

    class WM:
        data = {
            "events": [],
            "context": {"user_display_name": "Инна"},
            "attention_slots": [],
        }

    class Mem:
        working = WM()
        semantic = Sem()
        episodic = _Ep([])
        external = _Ext()

    msgs = build_chat_messages_for_llm(Mem(), "sid", user_message="привет")
    assert "Инна" in msgs[0]["content"]
    assert "явно указано" in msgs[0]["content"]
