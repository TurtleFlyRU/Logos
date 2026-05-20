"""Пайплайн в той же CLI-сессии (без отдельного ``eidos run``)."""

from __future__ import annotations

import uuid

import pytest


def test_run_pipeline_in_chat_session_research_stub(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("LOGOS_DATA_ROOT", str(tmp_path))
    from kernel.memory import Memory

    sid = str(uuid.uuid4())
    memory = Memory(auto_boot=False)
    memory.working.clear()
    memory.working.set_context("cli_session_id", sid)
    memory.working.set_context("cli_transport", "eidos")

    from cli.pipelines.runner import run_pipeline_in_chat_session

    code, blob = run_pipeline_in_chat_session(
        memory,
        sid,
        "research",
        "локальная тема для WM",
        paths=(),
        stub=True,
    )
    assert code == 0
    assert "[pipeline stub]" in blob
    pipeline_events = [
        e
        for e in memory.working.data["events"]
        if e.get("event_type") == "cli_pipeline"
    ]
    assert len(pipeline_events) >= 2
