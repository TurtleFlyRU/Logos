from __future__ import annotations

import json
from pathlib import Path

import pytest

from kernel.memory import EpisodicMemory


@pytest.fixture
def episodic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EpisodicMemory:
    import kernel.config as cfg
    import kernel.memory as mem_mod

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(cfg, "EPISODIC_DB_PATH", db_path)
    monkeypatch.setattr(mem_mod, "EPISODIC_DB_PATH", db_path)
    mem_mod.Memory._instance = None
    return EpisodicMemory()


def test_recall_by_cues_returns_intersecting_episodes(episodic: EpisodicMemory) -> None:
    expected = episodic.store({
        "timestamp": 100.0,
        "raw_text": "memory episode",
        "summary": "memory",
        "context_keys": ["logos", "engram"],
    })
    episodic.store({
        "timestamp": 200.0,
        "raw_text": "sleep episode",
        "summary": "sleep",
        "context_keys": ["sleep"],
    })

    results = episodic.recall_by_cues(["engram"])

    assert [row["id"] for row in results] == [expected]


def test_recall_by_cues_with_empty_cues_returns_latest(episodic: EpisodicMemory) -> None:
    old = episodic.store({"timestamp": 100.0, "raw_text": "old", "summary": "old"})
    middle = episodic.store({"timestamp": 200.0, "raw_text": "middle", "summary": "middle"})
    latest = episodic.store({"timestamp": 300.0, "raw_text": "latest", "summary": "latest"})

    results = episodic.recall_by_cues([], limit=2)

    assert [row["id"] for row in results] == [latest, middle]
    assert old not in [row["id"] for row in results]


def test_link_related_links_similar_episodes(episodic: EpisodicMemory) -> None:
    target = episodic.store({
        "timestamp": 100.0,
        "raw_text": "target",
        "summary": "target",
        "context_keys": ["logos", "memory"],
    })
    related = episodic.store({
        "timestamp": 200.0,
        "raw_text": "related",
        "summary": "related",
        "context_keys": ["memory", "engram"],
    })
    episodic.store({
        "timestamp": 300.0,
        "raw_text": "other",
        "summary": "other",
        "context_keys": ["sleep"],
    })

    linked = episodic.link_related(target, max_links=3)
    stored_target = next(row for row in episodic.query(limit=10) if row["id"] == target)

    assert linked == [related]
    assert json.loads(stored_target["linked_episodes"]) == [related]


def test_update_episode_changes_fields(episodic: EpisodicMemory) -> None:
    episode_id = episodic.store({"raw_text": "before", "summary": "before"})

    updated = episodic.update_episode(
        episode_id,
        summary="after",
        context_keys=["updated"],
        tools_used=["pytest"],
        outcome="passed",
    )
    stored = episodic.query(limit=1)[0]

    assert updated is True
    assert stored["summary"] == "after"
    assert json.loads(stored["context_keys"]) == ["updated"]
    assert json.loads(stored["tools_used"]) == ["pytest"]
    assert stored["outcome"] == "passed"


def test_record_episode_extracts_context_keys_from_tags_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kernel.config as cfg
    import kernel.memory as mem_mod

    monkeypatch.setattr(cfg, "WORKING_MEMORY_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(cfg, "EPISODIC_DB_PATH", tmp_path / "episodic.db")
    monkeypatch.setattr(cfg, "SEMANTIC_DB_PATH", tmp_path / "semantic.db")
    monkeypatch.setattr(cfg, "GOALS_DB_PATH", tmp_path / "goals.db")
    monkeypatch.setattr(mem_mod, "WORKING_MEMORY_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(mem_mod, "EPISODIC_DB_PATH", tmp_path / "episodic.db")
    monkeypatch.setattr(mem_mod, "SEMANTIC_DB_PATH", tmp_path / "semantic.db")
    mem_mod.Memory._instance = None

    memory = mem_mod.Memory(auto_boot=False)
    memory.record_episode(
        "raw",
        summary="Контекстная память Эйдоса",
        tags=["engram", "tool:pytest"],
        outcome="ok",
    )
    episode = memory.episodic.query(limit=1)[0]
    context_keys = json.loads(episode["context_keys"])

    assert "engram" in context_keys
    assert "контекстная" in context_keys
    assert "память" in context_keys
    assert json.loads(episode["tools_used"]) == ["pytest"]
    assert episode["outcome"] == "ok"
