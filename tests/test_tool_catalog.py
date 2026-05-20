"""Tests for cli.tool_catalog."""

from __future__ import annotations

from cli.tool_catalog import (
    collect_tool_specs,
    format_tools_catalog_block,
    tool_names_from_specs,
    tools_catalog_enabled,
)


def test_catalog_enabled_when_tools_on(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    assert tools_catalog_enabled()
    monkeypatch.setenv("EIDOS_TOOLS", "0")
    assert not tools_catalog_enabled()


def test_catalog_block_lists_tools(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    monkeypatch.setenv("EIDOS_MEMORY_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOL_SEARCH", "0")
    text = format_tools_catalog_block(user_line="прочитай README")
    assert "Доступные инструменты" in text
    assert "tool_calls: разрешены" in text
    specs = collect_tool_specs()
    names = tool_names_from_specs(specs)
    assert "read_workspace_file" in names
    assert "memory_search_episodic" in names
    for name in names:
        assert name in text


def test_identity_line_disables_tool_calls_in_catalog(monkeypatch):
    monkeypatch.setenv("EIDOS_TOOLS", "1")
    monkeypatch.setenv("EIDOS_TOOL_SEARCH", "0")
    text = format_tools_catalog_block(user_line="кто я")
    assert "tool_calls: для этой реплики отключены" in text
