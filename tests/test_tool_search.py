"""Tests for cli.tool_search."""

from __future__ import annotations

from cli.tool_search import (
    TOOL_SEARCH_FN,
    ToolSearchSession,
    execute_tool_search,
    tool_search_enabled,
)


def test_tool_search_partitions_deferred(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOL_SEARCH", "1")
    monkeypatch.setenv("EIDOS_MEMORY_TOOLS", "1")
    session = ToolSearchSession.start()
    api = session.build_api_tool_specs()
    names = [
        (s.get("function") or {}).get("name")
        for s in api
        if (s.get("function") or {}).get("name")
    ]
    assert TOOL_SEARCH_FN in names
    assert "read_workspace_file" in names
    assert "memory_search_episodic" not in names


def test_tool_search_loads_memory_namespace(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOL_SEARCH", "1")
    monkeypatch.setenv("EIDOS_MEMORY_TOOLS", "1")
    session = ToolSearchSession.start()
    text, newly = execute_tool_search(session, {"namespace": "memory"})
    assert "memory_search_episodic" in newly
    api_names = [
        (s.get("function") or {}).get("name")
        for s in session.build_api_tool_specs()
    ]
    assert "memory_search_episodic" in api_names
    assert "tool_search_output" in text


def test_tool_search_off_exports_all(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOL_SEARCH", "0")
    assert not tool_search_enabled()
    session = ToolSearchSession.start()
    names = [
        (s.get("function") or {}).get("name")
        for s in session.build_api_tool_specs()
    ]
    assert "memory_search_episodic" in names
    assert TOOL_SEARCH_FN not in names
