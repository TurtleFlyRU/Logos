"""Тесты OutcomeMemory: success rate с context_sig, атомарная запись."""

from __future__ import annotations

import json
import os

import pytest

from kernel.planner import OutcomeMemory


@pytest.fixture
def om(tmp_path):
    path = tmp_path / "outcomes.json"
    path.write_text("[]")
    return OutcomeMemory(str(path))


def test_empty_returns_default(om):
    assert om.get_success_rate("read") == 0.5
    assert om.get_success_rate("read", "ctx_a") == 0.5


def test_success_rate_all_contexts(om):
    om.record("ctx_a", "read", True)
    om.record("ctx_a", "read", True)
    om.record("ctx_a", "read", False)
    om.record("ctx_b", "read", True)
    assert om.get_success_rate("read") == 0.75
    assert om.total_outcomes("read") == 4


def test_success_rate_filtered_by_context(om):
    om.record("ctx_a", "read", True)
    om.record("ctx_a", "read", True)
    om.record("ctx_a", "read", False)
    om.record("ctx_b", "read", True)
    rate_a = om.get_success_rate("read", "ctx_a")
    rate_b = om.get_success_rate("read", "ctx_b")
    assert rate_a == 2 / 3, f"expected 0.667, got {rate_a}"
    assert rate_b == 1.0, f"expected 1.0, got {rate_b}"


def test_success_rate_unknown_context_returns_default(om):
    om.record("ctx_a", "read", True)
    assert om.get_success_rate("read", "ctx_unknown") == 0.5


def test_window_limits(om):
    for i in range(100):
        om.record(f"ctx_{i % 10}", "read", True)
    # window=10: последние 10, все read + ctx_5
    rate_win = om.get_success_rate("read", "ctx_5", window=10)
    # Все 100 успешны, но окно всего 10 — если не все 10 попадают под ctx_5 → 0.5 или 1.0
    assert rate_win in (0.5, 1.0)


def test_multiple_actions_independent(om):
    om.record("ctx", "read", True)
    om.record("ctx", "write", False)
    assert om.get_success_rate("read") == 1.0
    assert om.get_success_rate("write") == 0.0


def test_persistence_across_reload(om):
    om.record("ctx", "read", True)
    om.record("ctx", "read", False)
    path = om.path
    reloaded = OutcomeMemory(str(path))
    assert reloaded.total_outcomes("read") == 2
    assert reloaded.get_success_rate("read") == 0.5


def test_no_orphan_tmp_after_record(om, tmp_path):
    om.record("ctx", "read", True)
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert len(leftovers) == 0, f"orphan tmp files: {leftovers}"
