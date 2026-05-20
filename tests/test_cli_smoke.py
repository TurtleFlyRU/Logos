"""Дымовые тесты CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
EIDOS = REPO_ROOT / "eidos.py"


def _run(
    argv: list[str],
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ}
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(EIDOS), *argv],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        input=input_text,
        timeout=120,
        env=merged,
    )


def test_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "eidos" in (r.stdout + r.stderr).lower() or "chat" in r.stdout


def test_subcommand_chat_help():
    r = _run(["chat", "--help"])
    assert r.returncode == 0


def test_chat_stub_exits_on_slash_exit(tmp_path):
    r = _run(
        ["chat", "--stub"],
        input_text="/exit\n",
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0
    assert "сессия" in r.stdout.lower()


def test_chat_new_writes_session_files(tmp_path):
    r = _run(
        ["chat", "--new", "--stub"],
        input_text="/exit\n",
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0
    latest = tmp_path / "cli_sessions" / "latest.json"
    assert latest.exists()
    data = json.loads(latest.read_text(encoding="utf-8"))
    sid = data["active_session_id"]
    sess_file = tmp_path / "cli_sessions" / f"{sid}.json"
    assert sess_file.exists()


def test_chat_invalid_session_uuid(tmp_path):
    r = _run(
        ["chat", "--session", "not-a-uuid", "--stub"],
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 2


def test_chat_new_and_session_mutually_exclusive(tmp_path):
    r = _run(
        ["chat", "--new", "--session", str(uuid.uuid4()), "--stub"],
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 2


def test_ask_stub_flag():
    r = _run(["ask", "--stub", "hello"])
    assert r.returncode == 0
    assert "hello" in r.stdout


def test_ask_missing_key_returns_2(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    r = _run(["ask", "ping"])
    assert r.returncode == 2
    assert "LLM_API_KEY" in r.stderr or "DEEPSEEK" in r.stderr


def test_chat_keyboard_interrupt_during_llm_no_traceback(monkeypatch, capsys):
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    class FakeWM:
        def __init__(self) -> None:
            self.events: list = []
            self.data = {"events": self.events}

        def add_event(self, ev):
            self.events.append(ev)

    class FakeSemantic:
        def get_principles(self, **_kwargs):
            return []

    class FakeEpisodic:
        def query_all(self, **_kwargs):
            return []

        def query(self, **_kwargs):
            return []

    class FakeExternal:
        def search(self, *_a, **_kw):
            return []

    class FakeMemory:
        def __init__(self) -> None:
            self.working = FakeWM()
            self.semantic = FakeSemantic()
            self.episodic = FakeEpisodic()
            self.external = FakeExternal()

    inputs = iter(["hi", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))

    def boom(*_a, **_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr("cli.runtime._cli_chat_llm_reply", boom)
    monkeypatch.setattr("cli.session.touch_session", lambda *a, **k: None)

    from cli.runtime import run_chat_interactive

    run_chat_interactive(FakeMemory(), sid, use_llm=True)
    out = capsys.readouterr().out
    assert "прерван" in out.lower()


def test_chat_pipeline_http_status_error_no_traceback(monkeypatch, capsys):
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    class FakeWM:
        def __init__(self) -> None:
            self.events: list = []
            self.data = {"events": self.events}

        def add_event(self, ev):
            self.events.append(ev)

    class FakeSemantic:
        def get_principles(self, **_kwargs):
            return []

    class FakeEpisodic:
        def query_all(self, **_kwargs):
            return []

        def query(self, **_kwargs):
            return []

    class FakeExternal:
        def search(self, *_a, **_kw):
            return []

    class FakeMemory:
        def __init__(self) -> None:
            self.working = FakeWM()
            self.semantic = FakeSemantic()
            self.episodic = FakeEpisodic()
            self.external = FakeExternal()

    inputs = iter(["/review help me", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))

    req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    resp = httpx.Response(
        400,
        request=req,
        json={"error": {"message": "bad request"}},
    )

    def boom(*_a, **_k):
        raise httpx.HTTPStatusError("boom", request=req, response=resp)

    monkeypatch.setattr("cli.pipelines.runner.run_pipeline_in_chat_session", boom)
    monkeypatch.setattr("cli.session.touch_session", lambda *a, **k: None)

    from cli.runtime import run_chat_interactive

    run_chat_interactive(FakeMemory(), sid, use_llm=True)
    out = capsys.readouterr().out
    assert "bad request" in out.lower()
    assert "traceback" not in out.lower()


def test_ask_keyboard_interrupt_returns_130(monkeypatch):
    def fake(*_a, **_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr("cli.runtime.chat_completions", fake)
    from cli.runtime import run_ask

    assert run_ask("q", use_llm=True) == 130


def test_friendly_http_status_hints():
    from cli.runtime import _friendly_http_status_line

    assert _friendly_http_status_line(503) and "503" in _friendly_http_status_line(503)
    assert _friendly_http_status_line(429) and "429" in _friendly_http_status_line(429)
    assert _friendly_http_status_line(999) is None


def test_http_error_body_snippet():
    from cli.runtime import _http_error_body_snippet

    req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    resp = httpx.Response(
        503,
        content=b'{"error":{"message":"overload"}}',
        request=req,
    )
    assert "overload" in (_http_error_body_snippet(resp) or "")


def test_run_help_lists_pipelines():
    r = _run(["run", "--help"])
    assert r.returncode == 0
    assert "research" in r.stdout
    assert "experiment" in r.stdout
    assert "code_review" in r.stdout


def test_review_help():
    r = _run(["review", "--help"])
    assert r.returncode == 0


def test_run_research_stub(tmp_path):
    r = _run(
        ["run", "--no-boot", "--stub", "research", "тема для пайплайна"],
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0
    assert "[pipeline stub]" in r.stdout


def test_run_research_missing_topic_returns_2(tmp_path):
    r = _run(
        ["run", "--no-boot", "--stub", "research"],
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 2


def test_chat_pipeline_help_in_stub(tmp_path):
    r = _run(
        ["chat", "--new", "--stub", "--no-boot"],
        input_text="/pipeline help\n/exit\n",
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0
    assert "research" in r.stdout and "/pipeline" in r.stdout


def test_chat_start_prints_env_report(tmp_path):
    r = _run(
        ["chat", "--new", "--stub", "--no-boot"],
        input_text="/exit\n",
        env={
            "LOGOS_DATA_ROOT": str(tmp_path),
            "EIDOS_PLAYWRIGHT": "1",
            "EIDOS_AGENTS_CONFIG": str(REPO_ROOT / "config" / "agents.defaults.yaml"),
        },
    )
    assert r.returncode == 0
    assert "[env] Настройки CLI" in r.stdout
    assert "EIDOS_PLAYWRIGHT=1" in r.stdout
    assert "[tool_routing]" in r.stdout
    assert "read_workspace_file -> openai_compatible_local" in r.stdout


def test_chat_start_prints_budget_report(tmp_path):
    r = _run(
        ["chat", "--new", "--stub", "--no-boot"],
        input_text="/exit\n",
        env={
            "LOGOS_DATA_ROOT": str(tmp_path),
            "EIDOS_CHAT_TOTAL_CHARS": "4321",
        },
    )
    assert r.returncode == 0
    assert "[budget] Chat budgets and fill:" in r.stdout
    assert "4321" in r.stdout


def test_chat_env_command_active_only(tmp_path):
    r = _run(
        ["chat", "--new", "--stub", "--no-boot"],
        input_text="/env active\n/exit\n",
        env={
            "LOGOS_DATA_ROOT": str(tmp_path),
            "EIDOS_PLAYWRIGHT": "1",
            "EIDOS_AGENT_PROFILE": "local-browser",
        },
    )
    assert r.returncode == 0
    assert "EIDOS_PLAYWRIGHT=1" in r.stdout
    assert "EIDOS_AGENT_PROFILE=local-browser" in r.stdout


def test_chat_budget_command(tmp_path):
    r = _run(
        ["chat", "--new", "--stub", "--no-boot"],
        input_text="/budget\n/exit\n",
        env={
            "LOGOS_DATA_ROOT": str(tmp_path),
            "EIDOS_CHAT_TOTAL_CHARS": "3456",
        },
    )
    assert r.returncode == 0
    assert r.stdout.count("[budget] Chat budgets and fill:") >= 2
    assert "3456" in r.stdout


def test_review_stub_with_paths(tmp_path):
    r = _run(
        [
            "review",
            "--no-boot",
            "--stub",
            "--paths",
            "requirements/README.md",
            "поверхностный",
            "обзор",
        ],
        env={"LOGOS_DATA_ROOT": str(tmp_path)},
    )
    assert r.returncode == 0
    assert "[pipeline stub]" in r.stdout
