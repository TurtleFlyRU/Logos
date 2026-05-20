"""Smoke tests for cli.memory_tools."""

from __future__ import annotations

import json

import pytest

from cli.memory_tools import (
    execute_memory_tool,
    format_memory_help,
    is_memory_tool_name,
    memory_tool_specs,
    memory_tools_enabled,
)


def test_memory_tool_names():
    assert is_memory_tool_name("memory_search_episodic")
    assert not is_memory_tool_name("read_workspace_file")


def test_specs_non_empty_when_enabled(monkeypatch):
    monkeypatch.setenv("EIDOS_MEMORY_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    assert memory_tools_enabled()
    specs = memory_tool_specs()
    names = [s["function"]["name"] for s in specs]
    assert "memory_search_episodic" in names
    assert "memory_get_episode" in names


def test_search_episodic_empty_pool(monkeypatch):
    monkeypatch.setenv("EIDOS_MEMORY_TOOLS", "1")

    class Ep:
        def recall_by_cues(self, cues, limit=5):
            return []

        def query(self, limit=50, min_salience=0.0):
            return []

        def query_all(self, min_salience=0.0, max_rows=None):
            return []

        class _Conn:
            def execute(self, *a, **k):
                return type("R", (), {"fetchall": lambda: []})()

        _conn = _Conn()

    class Mem:
        episodic = Ep()

    raw = execute_memory_tool(Mem(), "memory_search_episodic", {"limit": 5})
    data = json.loads(raw)
    assert data["count"] == 0
    assert "episodes" in data


def test_format_memory_help():
    text = format_memory_help()
    assert "Память" in text
    assert "MEMORY_AGENT_ACCESS" in text
