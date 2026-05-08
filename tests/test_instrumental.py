"""Tests for InstrumentalRegistry."""

import json
import os
import tempfile

import pytest

from kernel.instrumental import InstrumentalRegistry


@pytest.fixture
def registry():
    old = os.environ.get("INSTRUMENTAL_DB_PATH")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    os.environ["INSTRUMENTAL_DB_PATH"] = db_path
    from kernel import config
    orig = config.INSTRUMENTAL_DB_PATH
    config.INSTRUMENTAL_DB_PATH = db_path
    ir = InstrumentalRegistry()
    ir._conn.execute("DELETE FROM tools")
    ir._conn.commit()
    yield ir
    config.INSTRUMENTAL_DB_PATH = orig
    if old is None:
        del os.environ["INSTRUMENTAL_DB_PATH"]
    else:
        os.environ["INSTRUMENTAL_DB_PATH"] = old
    os.unlink(db_path)


class TestInstrumentalRegistry:
    def test_add_tool(self, registry):
        tid = registry.add_tool("pytest", "run", "pytest {path}", ["test", "python"], "Run pytest tests")
        assert tid > 0
        tool = registry.get_tool_by_id(tid)
        assert tool["tool_name"] == "pytest"
        assert tool["method"] == "run"
        assert tool["confidence"] == 0.5

    def test_add_tool_duplicate(self, registry):
        tid1 = registry.add_tool("pytest", "run")
        tid2 = registry.add_tool("pytest", "run")
        assert tid1 == tid2

    def test_record_success_confidence(self, registry):
        tid = registry.add_tool("git", "clone")
        tool = registry.record_success(tid)
        assert tool["success_count"] == 1
        assert tool["fail_count"] == 0
        assert tool["confidence"] == pytest.approx(2 / 3, rel=1e-3)

    def test_record_success_multiple_confidence(self, registry):
        tid = registry.add_tool("git", "clone")
        for _ in range(9):
            registry.record_success(tid)
        tool = registry.record_success(tid)
        assert tool["success_count"] == 10
        assert tool["fail_count"] == 0
        assert tool["confidence"] == pytest.approx(11 / 12, rel=1e-3)

    def test_record_failure_confidence(self, registry):
        tid = registry.add_tool("pip", "install")
        tool = registry.record_failure(tid, exit_code=1, error="permission denied")
        assert tool["success_count"] == 0
        assert tool["fail_count"] == 1
        assert tool["confidence"] == pytest.approx(1 / 3, rel=1e-3)
        assert tool["last_error"] == "permission denied"
        assert tool["last_exit_code"] == 1

    def test_record_mixed_outcomes(self, registry):
        tid = registry.add_tool("download", "git-clone")
        for _ in range(3):
            registry.record_success(tid)
        for _ in range(2):
            registry.record_failure(tid, exit_code=128, error="timeout")
        tool = registry.record_success(tid)
        assert tool["success_count"] == 4
        assert tool["fail_count"] == 2
        assert tool["confidence"] == pytest.approx(5 / 8, rel=1e-3)

    def test_recommend_by_tags(self, registry):
        t1 = registry.add_tool("agent", "cursor", "agent {params}", ["cursor", "automation"], "Cursor Agent CLI")
        registry.add_tool("pytest", "run", "pytest {path}", ["test", "python"], "Run tests")
        registry.add_tool("rg", "search", "rg {pattern}", ["search", "code"], "Code search")
        registry.record_success(t1)
        recommended = registry.recommend(tags=["cursor"], min_confidence=0.1, limit=5)
        names = [r["tool_name"] for r in recommended]
        assert "agent" in names

    def test_recommend_empty_tags(self, registry):
        registry.add_tool("ls", "list")
        registry.add_tool("pwd", "print")
        recommended = registry.recommend(tags=[], min_confidence=0.1, limit=5)
        assert len(recommended) == 2

    def test_recommend_confidence_filter(self, registry):
        tid = registry.add_tool("risky", "run")
        for _ in range(3):
            registry.record_failure(tid, exit_code=1)
        recommended = registry.recommend(min_confidence=0.5, limit=5)
        names = [r["tool_name"] for r in recommended]
        assert "risky" not in names

    def test_get_stats(self, registry):
        registry.add_tool("a", "m1")
        registry.add_tool("b", "m2")
        stats = registry.get_stats()
        assert stats["total_tools"] == 2
        assert stats["avg_confidence"] == 0.5

    def test_get_tool_by_name_method(self, registry):
        registry.add_tool("curl", "get")
        tool = registry.get_tool_by_name_method("curl", "get")
        assert tool is not None
        assert tool["tool_name"] == "curl"
        assert registry.get_tool_by_name_method("curl", "post") is None

    def test_get_boot_summary_empty(self, registry):
        summary = registry.get_boot_summary()
        assert summary == ""

    def test_get_boot_summary_with_tools(self, registry):
        tid = registry.add_tool("agent", "cursor", "agent {params}", ["cursor"], "Cursor Agent CLI")
        for _ in range(4):
            registry.record_success(tid)
        summary = registry.get_boot_summary(limit=3)
        assert "Инструментальная память" in summary
        assert "agent/cursor" in summary
