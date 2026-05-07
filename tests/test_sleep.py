"""Тесты idempotent sleep pipeline: lock, checkpoint, resume, progress."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kernel.memory import Memory


@pytest.fixture
def mem(tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.memory as mem_mod

    mem_attrs = [
        "WORKING_MEMORY_PATH", "EPISODIC_DB_PATH", "SEMANTIC_DB_PATH",
        "SLEEP_LOCK_PATH", "SLEEP_CHECKPOINT_PATH",
    ]
    for attr in mem_attrs:
        patched = tmp_path / attr.lower().replace("_path", "").replace("_dir", "")
        monkeypatch.setattr(cfg, attr, patched)
        monkeypatch.setattr(mem_mod, attr, patched)

    cfg_attrs = [
        "GOALS_DB_PATH", "GOALS_CHECKPOINT_PATH",
        "JOURNAL_DIR", "JOURNAL_VECTOR_INDEX_PATH",
        "MISSION_STATE_PATH", "MISSION_HYPOTHESES_PATH",
        "MISSION_EXPERIMENTS_PATH", "MISSION_PROTOCOL_PATH",
    ]
    for attr in cfg_attrs:
        monkeypatch.setattr(cfg, attr, tmp_path / attr.lower().replace("_path", "").replace("_dir", ""))

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.respond("тестовый ответ", "тестовый запрос")
    return m


def test_lock_prevents_parallel_sleep(mem):
    import kernel.config as cfg

    cfg.SLEEP_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.SLEEP_LOCK_PATH.write_text('{"pid": 99999, "started_at": 0}')

    r = mem.sleep()
    assert r["status"] == "skipped"
    assert "lock" in r.get("reason", "")


def test_force_bypasses_lock(mem):
    r1 = mem.sleep(force=True)
    assert r1["status"] == "ok"

    r2 = mem.sleep(force=True)
    assert r2["status"] == "ok"


def test_sleep_clears_working_memory(mem):
    import kernel.config as cfg

    wm_path: Path = cfg.WORKING_MEMORY_PATH
    before = json.loads(wm_path.read_text())
    assert len(before.get("events", [])) > 0

    mem.sleep()

    after = json.loads(wm_path.read_text())
    assert len(after.get("events", [])) == 0
    assert after.get("event_count", -1) == 0


def test_sleep_checkpoint_persistence(tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.memory as mem_mod

    mem_attrs = [
        "WORKING_MEMORY_PATH", "EPISODIC_DB_PATH", "SEMANTIC_DB_PATH",
        "SLEEP_LOCK_PATH", "SLEEP_CHECKPOINT_PATH",
    ]
    for attr in mem_attrs:
        patched = tmp_path / attr.lower().replace("_path", "").replace("_dir", "")
        monkeypatch.setattr(cfg, attr, patched)
        monkeypatch.setattr(mem_mod, attr, patched)

    cfg_attrs = [
        "GOALS_DB_PATH", "GOALS_CHECKPOINT_PATH",
        "JOURNAL_DIR", "JOURNAL_VECTOR_INDEX_PATH",
        "MISSION_STATE_PATH", "MISSION_HYPOTHESES_PATH",
        "MISSION_EXPERIMENTS_PATH", "MISSION_PROTOCOL_PATH",
    ]
    for attr in cfg_attrs:
        monkeypatch.setattr(cfg, attr, tmp_path / attr.lower().replace("_path", "").replace("_dir", ""))

    mem_mod.Memory._instance = None
    m = Memory(auto_boot=False)
    m.respond("данные", "запрос")

    m.sleep()

    assert not cfg.SLEEP_LOCK_PATH.exists()
    assert not cfg.SLEEP_CHECKPOINT_PATH.exists()


    episodes = m.episodic.query(limit=10)
    assert len(episodes) >= 1


def test_sleep_progress_callback(mem):
    steps: list[tuple[str, int, int]] = []

    def track(name: str, step: int, total: int):
        steps.append((name, step, total))

    r = mem.sleep(progress_callback=track)
    assert r["status"] == "ok"

    assert len(steps) == 11
    for i, (name, step, total) in enumerate(steps, 1):
        assert step == i
        assert total == 11
        assert isinstance(name, str) and len(name) > 0


def test_sleep_report_contains_metrics(mem):
    r = mem.sleep()
    assert "elapsed_seconds" in r
    assert r["elapsed_seconds"] >= 0
    assert "completed_at" in r
    assert "status" in r
    assert r["status"] == "ok"
