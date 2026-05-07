"""Тесты EpisodicMemory: store, query с фильтрами, порядок, пустая БД."""

from __future__ import annotations

import json
import time

import pytest

from kernel.memory import EpisodicMemory


@pytest.fixture
def epi(tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.memory as mem_mod

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(cfg, "EPISODIC_DB_PATH", db_path)
    monkeypatch.setattr(mem_mod, "EPISODIC_DB_PATH", db_path)

    mem_mod.Memory._instance = None
    return EpisodicMemory()


def test_store_returns_valid_id(epi):
    eid = epi.store({
        "raw_text": "тестовый эпизод",
        "summary": "тест",
        "salience": 0.5,
    })
    assert isinstance(eid, int)
    assert eid > 0


def test_query_returns_ordered_by_timestamp_desc(epi):
    epi.store({"timestamp": 100.0, "raw_text": "старый", "summary": "s1", "salience": 0.5})
    epi.store({"timestamp": 300.0, "raw_text": "новый", "summary": "s2", "salience": 0.5})
    epi.store({"timestamp": 200.0, "raw_text": "средний", "summary": "s3", "salience": 0.5})
    results = epi.query(limit=10)
    timestamps = [r["timestamp"] for r in results]
    assert timestamps == sorted(timestamps, reverse=True)


def test_query_respects_min_salience(epi):
    epi.store({"raw_text": "низкая салиенс", "summary": "s1", "salience": 0.1})
    epi.store({"raw_text": "высокая салиенс", "summary": "s2", "salience": 0.9})
    results = epi.query(min_salience=0.5)
    assert len(results) == 1
    assert results[0]["salience"] >= 0.5


def test_query_respects_limit(epi):
    for i in range(10):
        epi.store({
            "raw_text": f"эпизод {i}",
            "summary": f"s{i}",
            "salience": 0.5,
        })
    results = epi.query(limit=3)
    assert len(results) == 3


def test_empty_db_returns_empty_list(epi):
    results = epi.query()
    assert results == []


def test_store_preserves_all_fields(epi):
    now = time.time()
    eid = epi.store({
        "timestamp": now,
        "session_id": "test_session",
        "salience": 0.8,
        "tags": ["ai", "test"],
        "summary": "тестовое резюме",
        "raw_text": "сырой текст эпизода",
        "compressed": "сжатая версия",
        "linked_episodes": [1, 2, 3],
        "context_keys": ["ai", "memory"],
        "outcome": "success",
        "tools_used": ["pytest"],
    })
    results = epi.query(limit=1)
    assert len(results) == 1
    r = results[0]
    assert r["id"] == eid
    assert r["session_id"] == "test_session"
    assert r["tags"] == json.dumps(["ai", "test"])
    assert r["linked_episodes"] == json.dumps([1, 2, 3])
    assert r["context_keys"] == json.dumps(["ai", "memory"], ensure_ascii=False)
    assert r["outcome"] == "success"
    assert r["tools_used"] == json.dumps(["pytest"], ensure_ascii=False)


def test_query_returns_empty_with_high_salience_filter(epi):
    epi.store({"raw_text": "эпизод", "summary": "s", "salience": 0.3})
    results = epi.query(min_salience=0.9)
    assert results == []


def test_multiple_stores_increment_ids(epi):
    ids = []
    for i in range(5):
        eid = epi.store({
            "raw_text": f"эпизод {i}",
            "summary": f"s{i}",
            "salience": 0.5,
        })
        ids.append(eid)
    assert ids == sorted(ids)
    assert len(set(ids)) == 5


def test_recall_by_cues_returns_intersecting_episodes(epi):
    first = epi.store({
        "timestamp": 100.0,
        "raw_text": "эпизод памяти",
        "summary": "memory work",
        "salience": 0.5,
        "context_keys": ["memory", "logos"],
    })
    epi.store({
        "timestamp": 200.0,
        "raw_text": "эпизод сна",
        "summary": "sleep work",
        "salience": 0.5,
        "context_keys": ["sleep"],
    })

    results = epi.recall_by_cues(["memory"])

    assert [r["id"] for r in results] == [first]


def test_recall_by_cues_with_empty_cues_returns_latest(epi):
    old = epi.store({"timestamp": 100.0, "raw_text": "old", "summary": "old"})
    newest = epi.store({"timestamp": 300.0, "raw_text": "new", "summary": "new"})
    middle = epi.store({"timestamp": 200.0, "raw_text": "middle", "summary": "middle"})

    results = epi.recall_by_cues([], limit=2)

    assert [r["id"] for r in results] == [newest, middle]
    assert old not in [r["id"] for r in results]


def test_link_related_links_similar_episodes(epi):
    target = epi.store({
        "timestamp": 100.0,
        "raw_text": "target",
        "summary": "target",
        "tags": ["архитектура"],
        "context_keys": ["memory", "logos"],
    })
    related = epi.store({
        "timestamp": 200.0,
        "raw_text": "related",
        "summary": "related",
        "tags": ["архитектура"],
        "context_keys": ["memory"],
    })
    epi.store({
        "timestamp": 300.0,
        "raw_text": "other",
        "summary": "other",
        "tags": ["sleep"],
        "context_keys": ["dream"],
    })

    linked = epi.link_related(target)
    stored = epi.query(limit=10)
    target_row = next(row for row in stored if row["id"] == target)

    assert linked == [related]
    assert json.loads(target_row["linked_episodes"]) == [related]


def test_update_episode_changes_fields(epi):
    eid = epi.store({"raw_text": "before", "summary": "before"})

    updated = epi.update_episode(
        eid,
        {
            "summary": "after",
            "context_keys": ["updated"],
            "tools_used": ["pytest"],
            "outcome": "passed",
        },
    )
    result = epi.query(limit=1)[0]

    assert updated is True
    assert result["summary"] == "after"
    assert json.loads(result["context_keys"]) == ["updated"]
    assert json.loads(result["tools_used"]) == ["pytest"]
    assert result["outcome"] == "passed"


def test_record_episode_extracts_context_keys_from_tags(tmp_path, monkeypatch):
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
        summary="Контекстная память",
        tags=["engram", "tool:pytest"],
        moral_context={"project": "logos"},
        outcome="ok",
    )
    episode = memory.episodic.query(limit=1)[0]

    assert "engram" in json.loads(episode["context_keys"])
    assert "logos" in json.loads(episode["context_keys"])
    assert json.loads(episode["tools_used"]) == ["pytest"]
    assert episode["outcome"] == "ok"
