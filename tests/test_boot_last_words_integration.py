"""Интеграционные тесты: sleep → last_words → boot с последними словами."""

from __future__ import annotations

import json

import pytest

from kernel.memory import Memory


def _patch_all(monkeypatch, tmp_path):
    import kernel.config as cfg
    import kernel.memory as mem_mod
    import kernel.boot as boot_mod

    # config — all paths
    cfg_paths = {
        "WORKING_MEMORY_PATH": tmp_path / "wm.json",
        "EPISODIC_DB_PATH": tmp_path / "episodic.db",
        "SEMANTIC_DB_PATH": tmp_path / "semantic.db",
        "SLEEP_LOCK_PATH": tmp_path / "sleep" / ".sleep.lock",
        "SLEEP_CHECKPOINT_PATH": tmp_path / "sleep" / "checkpoint.json",
        "SLEEP_LAST_WORDS_PATH": tmp_path / "sleep" / "last_words.json",
        "GOALS_DB_PATH": tmp_path / "goals" / "goals.db",
        "GOALS_CHECKPOINT_PATH": tmp_path / "goals" / "checkpoint.json",
        "JOURNAL_DIR": tmp_path / "journal",
        "JOURNAL_VECTOR_INDEX_PATH": tmp_path / "journal_vector_index.pkl",
        "MISSION_STATE_PATH": tmp_path / "mission" / "state.json",
        "MISSION_HYPOTHESES_PATH": tmp_path / "mission" / "hypotheses.json",
        "MISSION_EXPERIMENTS_PATH": tmp_path / "mission" / "experiments.json",
        "MISSION_PROTOCOL_PATH": tmp_path / "mission" / "protocol.log",
        "PLANNER_DATA_DIR": tmp_path / "planner",
        "EXPERIMENTS_ROOT": tmp_path / "experiments",
    }

    for attr, val in cfg_paths.items():
        monkeypatch.setattr(cfg, attr, val)

    # memory.py imports only specific paths from config
    mem_attrs = [
        "WORKING_MEMORY_PATH", "EPISODIC_DB_PATH", "SEMANTIC_DB_PATH",
        "SLEEP_LOCK_PATH", "SLEEP_CHECKPOINT_PATH", "SLEEP_LAST_WORDS_PATH",
    ]
    for attr in mem_attrs:
        monkeypatch.setattr(mem_mod, attr, cfg_paths[attr])

    # boot.py imports SLEEP_LAST_WORDS_PATH
    monkeypatch.setattr(boot_mod, "SLEEP_LAST_WORDS_PATH", cfg_paths["SLEEP_LAST_WORDS_PATH"])


@pytest.fixture
def mem_with_events(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.working.add_event({"role": "user", "content": "привет, Эйдос"})
    m.working.add_event({"role": "assistant", "content": "здравствуй, человек"})
    return m


def test_add_event_then_sleep_then_boot_shows_last_words(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.working.add_event({"role": "user", "content": "последний вопрос перед сном"})
    m.sleep(force=True)

    m2 = Memory(auto_boot=False)
    ctx = m2.boot()
    assert "последний вопрос перед сном" in ctx


def test_multiple_events_before_sleep_all_visible_in_boot(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    messages = ["шаг 1", "шаг 2", "шаг 3"]
    for msg in messages:
        m.working.add_event({"role": "user", "content": msg})
    m.sleep(force=True)

    m2 = Memory(auto_boot=False)
    ctx = m2.boot()
    for msg in messages:
        assert msg in ctx


def test_boot_without_sleep_no_last_words_graceful(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.working.add_event({"role": "user", "content": "привет"})

    ctx = m.boot()
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_boot_after_two_sleep_cycles_shows_latest_words(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.working.add_event({"role": "user", "content": "цикл 1 сообщение"})
    m.sleep(force=True)

    m.working.add_event({"role": "user", "content": "цикл 2 сообщение"})
    m.sleep(force=True)

    m2 = Memory(auto_boot=False)
    ctx = m2.boot()
    assert "цикл 2 сообщение" in ctx


def test_last_words_limited_to_five_events(tmp_path, monkeypatch):
    _patch_all(monkeypatch, tmp_path)
    import kernel.memory as mem_mod

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    for i in range(10):
        m.working.add_event({"role": "user", "content": f"событие {i}"})
    m.sleep(force=True)

    import kernel.config as cfg
    lw = json.loads(cfg.SLEEP_LAST_WORDS_PATH.read_text())
    assert len(lw["events"]) <= 5
