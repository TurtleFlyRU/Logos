"""Адаптер к SQLite-базе OpenCode.

Читает историю сессий, сообщений и частей (parts) напрямую из БД.
OpenCode хранит текст диалога в таблице `part` (type='text'),
а сообщения в `message` — только метаданные и tool calls.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OPEnCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


@dataclass
class OpenCodePart:
    id: str
    message_id: str
    type: str
    text: str
    tool: str = ""
    time_created: float = 0.0


@dataclass
class OpenCodeMessage:
    id: str
    session_id: str
    role: str
    content: str
    time_created: float
    tokens: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    parts: list[OpenCodePart] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenCodeSession:
    id: str
    project_id: str
    slug: str
    title: str
    directory: str
    time_created: float
    time_updated: float
    model: str = ""
    agent: str = ""


class OpenCodeAdapter:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.path = Path(db_path or OPEnCODE_DB)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_recent_sessions(self, limit: int = 10) -> list[OpenCodeSession]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT id, project_id, slug, title, directory,
                      time_created, time_updated, model, agent
               FROM session
               ORDER BY time_created DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        result: list[OpenCodeSession] = []
        for r in rows:
            model_raw = r["model"] or ""
            if model_raw.startswith("{"):
                try:
                    model_raw = json.loads(model_raw).get("id", model_raw)
                except Exception:
                    pass
            result.append(
                OpenCodeSession(
                    id=r["id"],
                    project_id=r["project_id"],
                    slug=r["slug"],
                    title=r["title"] or "",
                    directory=r["directory"] or "",
                    time_created=r["time_created"] / 1000.0,
                    time_updated=r["time_updated"] / 1000.0,
                    model=str(model_raw),
                    agent=r["agent"] or "",
                )
            )
        return result

    def _get_parts_for_message(self, message_id: str) -> list[OpenCodePart]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT id, message_id, time_created, data
               FROM part
               WHERE message_id = ?
               ORDER BY time_created ASC""",
            (message_id,),
        ).fetchall()
        parts: list[OpenCodePart] = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            ptype = data.get("type", "")
            ptool = data.get("tool", "")
            ptext = (
                data.get("text")
                or data.get("reasoning")
                or json.dumps(data.get("state", {}), ensure_ascii=False)[:1000]
                or ""
            )
            parts.append(
                OpenCodePart(
                    id=r["id"],
                    message_id=r["message_id"],
                    type=ptype,
                    text=str(ptext)[:2000],
                    tool=ptool,
                    time_created=r["time_created"] / 1000.0,
                )
            )
        return parts

    def get_session_messages(
        self, session_id: str, limit: int = 200, with_parts: bool = True
    ) -> list[OpenCodeMessage]:
        conn = self.connect()
        rows = conn.execute(
            """SELECT id, session_id, time_created, data
               FROM message
               WHERE session_id = ?
               ORDER BY time_created ASC
               LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        result: list[OpenCodeMessage] = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            role = data.get("role", "unknown")

            # Собираем текст из parts
            parts: list[OpenCodePart] = []
            if with_parts:
                parts = self._get_parts_for_message(r["id"])

            # Формируем content из text-parts
            text_parts = [p.text for p in parts if p.type == "text"]
            content = "\n".join(text_parts)

            tokens = data.get("tokens", {}) or {}
            if isinstance(tokens, dict):
                tokens = {k: int(v) for k, v in tokens.items() if isinstance(v, (int, float))}
            elif isinstance(tokens, (int, float)):
                tokens = {"total": int(tokens)}

            result.append(
                OpenCodeMessage(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=role,
                    content=str(content)[:5000],
                    time_created=r["time_created"] / 1000.0,
                    tokens=tokens,
                    cost=float(data.get("cost", 0) or 0),
                    parts=parts,
                    raw=data,
                )
            )
        return result

    def get_session_dialog(
        self, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Возвращает диалог в формате [{role, content}, ...] — удобно для контекста."""
        msgs = self.get_session_messages(session_id, limit=limit)
        dialog: list[dict[str, Any]] = []
        for m in msgs:
            if m.content.strip():
                dialog.append({"role": m.role, "content": m.content})
        return dialog

    def get_last_session(self) -> OpenCodeSession | None:
        sessions = self.get_recent_sessions(limit=1)
        return sessions[0] if sessions else None

    def get_last_dialog(self, limit: int = 10) -> list[dict[str, Any]]:
        """Последние N реплик диалога из последней сессии."""
        session = self.get_last_session()
        if not session:
            return []
        return self.get_session_dialog(session.id, limit=limit)

    def get_current_session_id(self) -> str | None:
        """Возвращает ID текущей (самой свежей) сессии."""
        s = self.get_last_session()
        return s.id if s else None

    def search_messages(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Поиск по тексту диалога (по parts)."""
        conn = self.connect()
        pattern = f"%{query}%"
        rows = conn.execute(
            """SELECT p.message_id, p.session_id, p.data
               FROM part p
               WHERE p.data LIKE ?
               ORDER BY p.time_created DESC
               LIMIT ?""",
            (pattern, limit),
        ).fetchall()
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            txt = data.get("text", "") or data.get("reasoning", "") or ""
            if query.lower() not in txt.lower():
                continue
            mid = r["message_id"]
            if mid in seen:
                continue
            seen.add(mid)

            msg_rows = conn.execute(
                "SELECT session_id, data FROM message WHERE id = ?", (mid,)
            ).fetchone()
            if msg_rows is None:
                continue
            try:
                msg_data = json.loads(msg_rows["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            result.append(
                {
                    "role": msg_data.get("role", "unknown"),
                    "content": str(txt)[:2000],
                    "session_id": r["session_id"],
                    "message_id": mid,
                }
            )
        return result


if __name__ == "__main__":
    oc = OpenCodeAdapter()
    print("=== Последние сессии ===")
    for s in oc.get_recent_sessions(5):
        print(f"  {s.slug:25s} | {s.title[:50]:50s} | {s.model[:20]}")

    last = oc.get_last_session()
    if last:
        print(f"\n=== Последняя сессия: {last.title} ===")
        print(f"  ID: {last.id}")
        for m in oc.get_session_messages(last.id, limit=10):
            c = m.content[:120] if m.content else "(no text)"
            print(f"  [{m.role}] {c}")