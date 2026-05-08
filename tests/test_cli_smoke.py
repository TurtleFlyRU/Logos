"""Дымовые тесты CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

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
