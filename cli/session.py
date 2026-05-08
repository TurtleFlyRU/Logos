"""Persistent CLI session metadata under data/cli_sessions/."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from kernel.config import CLI_SESSION_LATEST_PATH, CLI_SESSIONS_DIR
from kernel.utils import atomic_write


def new_session_id() -> str:
    return str(uuid.uuid4())


def is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s.strip())
    except ValueError:
        return False
    return True


def normalize_session_id(s: str) -> str:
    return str(uuid.UUID(s.strip()))


def session_path(session_id: str) -> Path:
    sid = session_id.strip()
    return CLI_SESSIONS_DIR / f"{sid}.json"


def save_session_record(record: dict[str, Any]) -> None:
    CLI_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = session_path(str(record["session_id"]))
    atomic_write(path, record)


def touch_session(session_id: str, **extra: Any) -> dict[str, Any]:
    """Создаёт или обновляет JSON сессии; возвращает актуальную запись."""
    sid = session_id.strip()
    path = session_path(sid)
    now = time.time()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    data.setdefault("session_id", sid)
    data.setdefault("created_at", now)
    data.setdefault("transport", "cli")
    data["updated_at"] = now
    data.update(extra)
    save_session_record(data)
    return data


def write_latest(session_id: str) -> None:
    CLI_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(
        CLI_SESSION_LATEST_PATH,
        {"active_session_id": session_id.strip(), "updated_at": time.time()},
    )


def read_latest() -> str | None:
    if not CLI_SESSION_LATEST_PATH.exists():
        return None
    try:
        raw = CLI_SESSION_LATEST_PATH.read_text(encoding="utf-8")
        j = json.loads(raw)
        sid = j.get("active_session_id")
        return str(sid).strip() if sid else None
    except (json.JSONDecodeError, OSError, TypeError):
        return None


def load_session(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
