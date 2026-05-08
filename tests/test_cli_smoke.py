"""Дымовые тесты CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EIDOS = REPO_ROOT / "eidos.py"


def _run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EIDOS), *argv],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        input=input_text,
        timeout=60,
    )


def test_help_exits_zero():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "eidos" in (r.stdout + r.stderr).lower() or "chat" in r.stdout


def test_subcommand_chat_help():
    r = _run(["chat", "--help"])
    assert r.returncode == 0


def test_chat_stub_exits_on_slash_exit():
    r = _run(["chat"], input_text="/exit\n")
    assert r.returncode == 0
    assert "stub" in r.stdout.lower() or "[stub]" in r.stdout


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
