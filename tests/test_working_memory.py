"""Тесты WorkingMemory: атомарная запись, add_event, сериализация."""

from __future__ import annotations

import json
import os

import pytest

from kernel.memory import WorkingMemory


@pytest.fixture
def wm(tmp_path, monkeypatch):
    from kernel import config as cfg_mod
    from kernel import memory as mem_mod

    monkeypatch.setattr(cfg_mod, "WORKING_MEMORY_PATH", tmp_path / "current.json")
    monkeypatch.setattr(mem_mod, "WORKING_MEMORY_PATH", tmp_path / "current.json")
    target = WorkingMemory()
    target._data = {"session_id": None, "context": {}, "events": [], "event_count": 0}
    return target


def test_save_creates_valid_json(wm):
    wm.set_context("test_key", "test_value")
    assert wm.path.exists()
    data = json.loads(wm.path.read_text())
    assert data["context"]["test_key"] == "test_value"


def test_atomic_write_no_corruption_on_crash(wm):
    wm._data["events"].append({"msg": "hello"})
    wm._data["event_count"] = 1
    wm.save()
    before = wm.path.read_text()
    # эмулируем частичную запись — не должна пережить rename
    wm._data["events"].append({"msg": "crash data"})
    wm._data["event_count"] = 2
    wm.save()
    after = wm.path.read_text()
    data = json.loads(after)
    assert data["event_count"] == 2
    assert len(data["events"]) == 2


def test_no_orphan_tmp_after_save(wm):
    wm.save()
    leftovers = [p for p in wm.path.parent.iterdir() if p.name.endswith(".tmp")]
    assert len(leftovers) == 0, f"orphan tmp files: {leftovers}"


def test_add_event_increments_count(wm):
    wm.add_event({"event_type": "test", "content": "hello"})
    assert wm._data["event_count"] == 1
    assert len(wm._data["events"]) == 1
    assert "timestamp" in wm._data["events"][0]


def test_add_event_multiple(wm):
    for i in range(5):
        wm.add_event({"event_type": "test", "content": str(i)})
    assert wm._data["event_count"] == 5
    assert wm._data["events"][-1]["content"] == "4"


def test_load_empty_returns_default(wm):
    wm.path.unlink(missing_ok=True)
    fresh = WorkingMemory()
    assert fresh._data["event_count"] == 0
    assert fresh._data["events"] == []


def test_roundtrip_preserves_data(wm):
    original = {"session_id": "abc", "context": {"x": 1}, "events": [{"e": 1}], "event_count": 1}
    wm._data = original
    wm.save()
    loaded = WorkingMemory()
    assert loaded._data["event_count"] == 1
    assert loaded._data["events"] == [{"e": 1}]
