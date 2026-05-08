"""Фаза 6: boot без скрытого OpenCode; явный import-opencode."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kernel.boot import boot_context, boot_native_context


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


def test_boot_native_context_matches_disabled_sync(mock_memory):
    a = boot_native_context(mock_memory)
    b = boot_context(mock_memory, sync_opencode=False)
    assert a == b


def test_memory_boot_skips_opencode_without_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("EIDOS_SYNC_OPENCODE", raising=False)

    from kernel.memory import Memory

    calls: list[int] = []

    def fake_sync(_self) -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(Memory, "_sync_from_opencode", fake_sync)
    m = Memory(auto_boot=False)
    m.boot()
    assert calls == []


def test_memory_boot_calls_opencode_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGOS_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("EIDOS_SYNC_OPENCODE", "1")

    from kernel.memory import Memory

    calls: list[int] = []

    def fake_sync(_self) -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(Memory, "_sync_from_opencode", fake_sync)
    m = Memory(auto_boot=False)
    m.boot()
    assert calls == [1]


def test_boot_cli_flag_forces_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("EIDOS_SYNC_OPENCODE", raising=False)

    from kernel.memory import Memory

    calls: list[int] = []

    def fake_sync(_self) -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(Memory, "_sync_from_opencode", fake_sync)
    m = Memory(auto_boot=False)
    m.boot(sync_opencode=True)
    assert calls == [1]
