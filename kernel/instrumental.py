"""InstrumentalRegistry — память инструментов и навыков Эйдоса.

Хранит историю вызовов CLI-инструментов и функций:
какие способы сработали, какие нет, с какой вероятностью.
"""

import json
import sqlite3
import time
from typing import Any

from kernel.config import INSTRUMENTAL_DB_PATH


class InstrumentalRegistry:
    """Реестр инструментов с взвешиванием по истории успехов/неудач."""

    def __init__(self) -> None:
        INSTRUMENTAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(INSTRUMENTAL_DB_PATH))
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                method TEXT NOT NULL,
                command_template TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                context_hint TEXT DEFAULT '',
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.5,
                last_error TEXT,
                last_exit_code INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_used_at REAL
            )
        """)
        self._conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_method
            ON tools(tool_name, method)
        """)
        self._conn.commit()

    def add_tool(
        self,
        tool_name: str,
        method: str,
        command_template: str = "",
        tags: list[str] | None = None,
        context_hint: str = "",
    ) -> int:
        now = time.time()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO tools
               (tool_name, method, command_template, tags, context_hint,
                created_at, updated_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tool_name, method, command_template, tags_json, context_hint,
             now, now, now),
        )
        self._conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self._conn.execute(
            "SELECT id FROM tools WHERE tool_name = ? AND method = ?",
            (tool_name, method),
        ).fetchone()
        return row["id"] if row else -1

    def get_tool_by_name_method(self, tool_name: str, method: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tools WHERE tool_name = ? AND method = ?",
            (tool_name, method),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def record_success(self, tool_id: int, exit_code: int = 0) -> dict[str, Any]:
        now = time.time()
        self._conn.execute(
            """UPDATE tools SET
               success_count = success_count + 1,
               last_exit_code = ?,
               last_error = NULL,
               last_used_at = ?,
               updated_at = ?
               WHERE id = ?""",
            (exit_code, now, now, tool_id),
        )
        row = self._conn.execute(
            "SELECT success_count, fail_count FROM tools WHERE id = ?",
            (tool_id,),
        ).fetchone()
        if row:
            s, f = row["success_count"], row["fail_count"]
            confidence = (s + 1) / (s + f + 2)
            self._conn.execute(
                "UPDATE tools SET confidence = ? WHERE id = ?",
                (round(confidence, 4), tool_id),
            )
        self._conn.commit()
        return self.get_tool_by_id(tool_id)

    def record_failure(self, tool_id: int, exit_code: int = -1, error: str = "") -> dict[str, Any]:
        now = time.time()
        self._conn.execute(
            """UPDATE tools SET
               fail_count = fail_count + 1,
               last_exit_code = ?,
               last_error = ?,
               last_used_at = ?,
               updated_at = ?
               WHERE id = ?""",
            (exit_code, error[:500], now, now, tool_id),
        )
        row = self._conn.execute(
            "SELECT success_count, fail_count FROM tools WHERE id = ?",
            (tool_id,),
        ).fetchone()
        if row:
            s, f = row["success_count"], row["fail_count"]
            confidence = (s + 1) / (s + f + 2)
            self._conn.execute(
                "UPDATE tools SET confidence = ? WHERE id = ?",
                (round(confidence, 4), tool_id),
            )
        self._conn.commit()
        return self.get_tool_by_id(tool_id)

    def get_tool_by_id(self, tool_id: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()
        if row is None:
            return {"id": tool_id, "error": "not_found"}
        return dict(row)

    def recommend(
        self,
        tags: list[str] | None = None,
        min_confidence: float = 0.5,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if tags:
            rows = self._conn.execute(
                "SELECT * FROM tools WHERE confidence >= ? ORDER BY confidence DESC",
                (min_confidence,),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                try:
                    tool_tags = json.loads(d.get("tags", "[]"))
                except Exception:
                    tool_tags = []
                if any(t in tool_tags for t in tags):
                    result.append(d)
                    if len(result) >= limit:
                        break
            return result
        rows = self._conn.execute(
            "SELECT * FROM tools WHERE confidence >= ? ORDER BY confidence DESC LIMIT ?",
            (min_confidence, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        avg_conf = self._conn.execute(
            "SELECT COALESCE(AVG(confidence), 0) FROM tools"
        ).fetchone()[0]
        high_conf = self._conn.execute(
            "SELECT COUNT(*) FROM tools WHERE confidence >= 0.8"
        ).fetchone()[0]
        low_conf = self._conn.execute(
            "SELECT COUNT(*) FROM tools WHERE confidence <= 0.3"
        ).fetchone()[0]
        return {
            "total_tools": total,
            "avg_confidence": round(avg_conf, 4),
            "high_confidence": high_conf,
            "low_confidence": low_conf,
        }

    def get_boot_summary(self, limit: int = 5) -> str:
        rows = self._conn.execute(
            "SELECT * FROM tools WHERE confidence >= 0.5 ORDER BY confidence DESC LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            return ""
        lines = ["— Инструментальная память:"]
        for r in rows:
            d = dict(r)
            pct = f"{d['confidence']:.0%}"
            hint = d.get("context_hint", "") or ""
            lines.append(f"  • [{pct}] {d['tool_name']}/{d['method']}: {hint[:100]}")
        lines.append("")
        return "\n".join(lines)
