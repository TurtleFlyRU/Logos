"""Тесты опционального публичного CLI-лога в каталоге репозитория."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pub_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "publog"
    monkeypatch.setenv("EIDOS_REPO_PUBLIC_LOG", "1")
    monkeypatch.setenv("EIDOS_REPO_PUBLIC_LOG_DIR", str(d))
    return d


def test_repo_public_log_skipped_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EIDOS_REPO_PUBLIC_LOG", raising=False)
    monkeypatch.setenv("EIDOS_REPO_PUBLIC_LOG_DIR", str(tmp_path / "x"))
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={
            "role": "user",
            "content": "hello",
            "event_type": "cli_chat",
        },
        context={"cli_transport": "eidos"},
    )
    assert not list(tmp_path.glob("**/*"))


def test_repo_public_log_user_message(pub_log_dir: Path) -> None:
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={
            "role": "user",
            "content": "ping",
            "event_type": "cli_chat",
            "cli_session_id": "sess-abc",
        },
        context={"cli_transport": "eidos"},
    )
    files = list(pub_log_dir.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "ping" in text
    assert "user" in text
    assert "sess-abc"[:12] in text


def test_repo_public_log_masks_secrets(pub_log_dir: Path) -> None:
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={
            "role": "user",
            "content": "LLM_API_KEY=sk-123456789012345678901234567890",
            "event_type": "cli_chat",
        },
        context={"cli_transport": "eidos"},
    )
    text = next(pub_log_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "sk-123456789012345678901234567890" not in text
    assert "redacted" in text


def test_repo_public_log_omits_code_fence(pub_log_dir: Path) -> None:
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={
            "role": "assistant",
            "content": "see\n```python\nSECRET=1\n```\nend",
            "event_type": "cli_chat",
        },
        context={"cli_transport": "eidos"},
    )
    text = next(pub_log_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "SECRET=1" not in text
    assert "omitted: code block" in text


def test_repo_public_log_tool_names_without_tool_role(pub_log_dir: Path) -> None:
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {"name": "bash", "arguments": '{"cmd": "rm -rf /"}'},
                }
            ],
            "event_type": "cli_chat",
        },
        context={"cli_transport": "eidos"},
    )
    text = next(pub_log_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "bash" in text
    assert "rm -rf" not in text


def test_repo_public_log_skips_non_eidos_transport(pub_log_dir: Path) -> None:
    from kernel.repo_public_log import maybe_append_cli_public_log

    maybe_append_cli_public_log(
        event={"role": "user", "content": "x", "event_type": "cli_chat"},
        context={"cli_transport": "other"},
    )
    assert not pub_log_dir.exists()
