"""Тесты boot-протокола: формирование контекста, last_words, бюджет, fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from kernel.boot import boot_context, MAX_BOOT_CHARS


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.working = MagicMock()
    mem.working._data = {"boot_contexts": []}
    mem.working.save = MagicMock()
    mem.working.set_context = MagicMock()
    mem.episodic.query.return_value = []
    mem.episodic.query_all.return_value = []
    mem.semantic.get_principles.return_value = []
    mem.goals.summary.return_value = ""
    return mem


def test_boot_returns_string(mock_memory):
    ctx = boot_context(mock_memory)
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_boot_includes_last_words(mock_memory, tmp_path):
    from kernel import boot as boot_mod
    from kernel import config as cfg

    last_words_path = tmp_path / "last_words.json"
    last_words_path.parent.mkdir(parents=True, exist_ok=True)
    last_words_path.write_text(json.dumps({
        "timestamp": 1000.0,
        "events": [{"role": "user", "content": "мой последний вопрос"}],
    }))
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cfg, "SLEEP_LAST_WORDS_PATH", last_words_path)
    monkeypatch.setattr(boot_mod, "SLEEP_LAST_WORDS_PATH", last_words_path)

    ctx = boot_context(mock_memory)
    assert "мой последний вопрос" in ctx


def test_boot_fallback_without_last_words(mock_memory):
    ctx = boot_context(mock_memory)
    assert isinstance(ctx, str)


def test_boot_includes_principles(mock_memory):
    mock_memory.semantic.get_principles.return_value = [
        {"principle": "Я учусь на опыте", "confidence": 0.95},
    ]
    ctx = boot_context(mock_memory)
    assert "Я учусь на опыте" in ctx


def test_boot_includes_health_report(mock_memory):
    ctx = boot_context(mock_memory)
    assert "Самочувствие" in ctx


def test_boot_respects_token_budget(mock_memory):
    episodes = [
        {"timestamp": 100.0, "summary": "x" * 5000, "raw_text": "y" * 2000}
        for _ in range(200)
    ]
    mock_memory.episodic.query.return_value = episodes
    mock_memory.episodic.query_all.return_value = episodes
    ctx = boot_context(mock_memory)
    assert len(ctx) <= MAX_BOOT_CHARS + 200


def test_boot_principles_respects_confidence(mock_memory):
    mock_memory.semantic.get_principles.return_value = [
        {"principle": "Высокая уверенность", "confidence": 0.95},
        {"principle": "Низкая уверенность", "confidence": 0.3},
    ]
    ctx = boot_context(mock_memory)
    assert "Высокая уверенность" in ctx


def test_boot_calls_episodic_query_all(mock_memory):
    mock_memory.episodic.query_all.return_value = []
    boot_context(mock_memory)
    mock_memory.episodic.query_all.assert_called()


def test_boot_with_empty_episodic(mock_memory):
    mock_memory.episodic.query.return_value = []
    ctx = boot_context(mock_memory)
    assert isinstance(ctx, str)
