"""Тесты SemanticMemory: store/get принципов, confidence, дубликаты."""

from __future__ import annotations

import json

import pytest

from kernel.memory import SemanticMemory

# Эти переменные НЕ импортируются — они инстанциируются через
# тестовые фикстуры, патчащие config напрямую. В тестах мы используем
# tmp_path напрямую в SemanticMemory — но конструктор читает SEMANTIC_DB_PATH
# из config модуля. Значит надо патчить config и memory модули.


@pytest.fixture
def sem(tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.memory as mem_mod

    db_path = tmp_path / "semantic.db"
    monkeypatch.setattr(cfg, "SEMANTIC_DB_PATH", db_path)
    monkeypatch.setattr(mem_mod, "SEMANTIC_DB_PATH", db_path)

    mem_mod.Memory._instance = None
    return SemanticMemory()


def test_store_and_get_principle(sem):
    sem.store_principle("Я — Эйдос", source_ids=[1], confidence=0.9)
    principles = sem.get_principles()
    assert len(principles) == 1
    assert principles[0]["principle"] == "Я — Эйдос"
    assert principles[0]["confidence"] == 0.9


def test_get_principles_ordered_by_confidence(sem):
    sem.store_principle("Низкий приоритет", source_ids=[1], confidence=0.3)
    sem.store_principle("Высокий приоритет", source_ids=[2], confidence=0.95)
    sem.store_principle("Средний приоритет", source_ids=[3], confidence=0.6)
    principles = sem.get_principles()
    assert [p["principle"] for p in principles] == [
        "Высокий приоритет", "Средний приоритет", "Низкий приоритет",
    ]


def test_duplicate_principle_updates_confidence(sem):
    sem.store_principle("Тестовый принцип", source_ids=[1], confidence=0.5)
    sem.store_principle("Тестовый принцип", source_ids=[2], confidence=0.9)
    principles = sem.get_principles()
    assert len(principles) == 1
    assert principles[0]["confidence"] == 0.9


def test_duplicate_principle_keeps_higher_confidence(sem):
    sem.store_principle("Принцип", source_ids=[1], confidence=0.9)
    sem.store_principle("Принцип", source_ids=[2], confidence=0.3)
    principles = sem.get_principles()
    assert len(principles) == 1
    assert principles[0]["confidence"] == 0.9


def test_empty_db_returns_empty_list(sem):
    principles = sem.get_principles()
    assert principles == []


def test_get_principles_with_min_confidence_filter(sem):
    sem.store_principle("Низкий", source_ids=[1], confidence=0.2)
    sem.store_principle("Высокий", source_ids=[2], confidence=0.8)
    high = sem.get_principles(min_confidence=0.7)
    assert len(high) == 1
    assert high[0]["principle"] == "Высокий"
    low = sem.get_principles(min_confidence=0.5)
    assert len(low) == 1
    assert low[0]["principle"] == "Высокий"


def test_principle_source_ids_accumulate(sem):
    sem.store_principle("Принцип", source_ids=[1], confidence=0.5)
    sem.store_principle("Принцип", source_ids=[2], confidence=0.7)
    p = sem.get_principles()[0]
    assert json.loads(p["source_episode_ids"]) == [2]


def test_persistence_across_reload(sem, tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.memory as mem_mod

    sem.store_principle("Сохраняемый принцип", source_ids=[1], confidence=0.8)
    path = sem.path

    db_path = path
    monkeypatch.setattr(cfg, "SEMANTIC_DB_PATH", db_path)
    monkeypatch.setattr(mem_mod, "SEMANTIC_DB_PATH", db_path)

    sem2 = SemanticMemory()
    principles = sem2.get_principles()
    assert len(principles) == 1
    assert principles[0]["principle"] == "Сохраняемый принцип"
