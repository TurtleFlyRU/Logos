"""GoalMemory — долгосрочное хранилище целей и планов Эйдоса.

Каждая цель — узел в дереве:
- Может иметь подцели (subgoals)
- Хранит статус, прогресс, приоритет
- Сериализуется в JSON и сохраняется в SQLite
- Загружается при boot и доступна между сессиями
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from kernel.memory import DATA_ROOT


GOAL_STATUS_TODO = "todo"
GOAL_STATUS_IN_PROGRESS = "in_progress"
GOAL_STATUS_DONE = "done"
GOAL_STATUS_CANCELLED = "cancelled"


@dataclass
class Goal:
    title: str
    description: str = ""
    status: str = GOAL_STATUS_TODO
    priority: float = 0.5
    progress: float = 0.0
    tags: list[str] = field(default_factory=list)
    subgoals: list["Goal"] = field(default_factory=list)
    parent_id: int | None = None
    id: int | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["subgoals"] = [sg.to_dict() for sg in self.subgoals]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Goal":
        subgoals_data = d.pop("subgoals", [])
        g = Goal(**d)
        g.subgoals = [Goal.from_dict(sg) for sg in subgoals_data]
        return g

    def advance(self, delta: float = 0.1) -> None:
        self.progress = min(1.0, self.progress + delta)
        self.updated_at = time.time()
        if self.progress >= 1.0:
            self.status = GOAL_STATUS_DONE


class GoalMemory:
    """Хранилище целей. SQLite для persistence, Python API для управления."""

    def __init__(self) -> None:
        self._path = DATA_ROOT / "goals" / "goals.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path = DATA_ROOT / "goals" / "checkpoint.json"
        self._conn = sqlite3.connect(str(self._path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'todo',
                priority REAL DEFAULT 0.5,
                progress REAL DEFAULT 0.0,
                tags TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_goals_parent ON goals(parent_id);
            CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
        """)
        self._conn.commit()

    def add_goal(self, title: str, description: str = "",
                 priority: float = 0.5, tags: list[str] | None = None,
                 parent_id: int | None = None) -> int:
        now = time.time()
        cur = self._conn.execute(
            """INSERT INTO goals (parent_id, title, description, status, priority, progress, tags, notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (parent_id, title, description, GOAL_STATUS_TODO, priority, 0.0,
             json.dumps(tags or []), "", now, now),
        )
        self._conn.commit()
        gid = cur.lastrowid
        self._checkpoint()
        return gid  # type: ignore[return-value]

    def update_goal(self, goal_id: int, **kwargs: Any) -> None:
        allowed = {"title", "description", "status", "priority", "progress", "tags", "notes"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = time.time()
        if "tags" in updates and isinstance(updates["tags"], list):
            updates["tags"] = json.dumps(updates["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [goal_id]
        self._conn.execute(f"UPDATE goals SET {set_clause} WHERE id = ?", vals)
        self._conn.commit()
        self._checkpoint()

    def advance_goal(self, goal_id: int, delta: float = 0.1) -> None:
        row = self._conn.execute(
            "SELECT progress, status FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not row:
            return
        progress = min(1.0, row[0] + delta)
        status = GOAL_STATUS_DONE if progress >= 1.0 else GOAL_STATUS_IN_PROGRESS
        self._conn.execute(
            "UPDATE goals SET progress = ?, status = ?, updated_at = ? WHERE id = ?",
            (progress, status, time.time(), goal_id),
        )
        self._conn.commit()
        self._checkpoint()

    def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_goals(self, status: str | None = None,
                  parent_id: int | None = None,
                  limit: int = 50) -> list[dict[str, Any]]:
        query = "SELECT * FROM goals WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if parent_id is not None:
            query += " AND parent_id = ?"
            params.append(parent_id)
        query += " ORDER BY priority DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_active_plan(self) -> list[dict[str, Any]]:
        top = self.get_goals(status=GOAL_STATUS_IN_PROGRESS, parent_id=None, limit=5)
        if not top:
            top = self.get_goals(status=GOAL_STATUS_TODO, parent_id=None, limit=5,
                                 priority=0.0)
            if not top:
                top = self.get_goals(limit=1)
        result = []
        for g in top:
            d = self._row_to_dict(self._conn.execute(
                "SELECT * FROM goals WHERE id = ?", (g["id"],)
            ).fetchone())
            if d:
                d["subgoals"] = self.get_goals(parent_id=d["id"])
                result.append(d)
        return result

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        columns = [d[1] for d in self._conn.execute("PRAGMA table_info(goals)").fetchall()]
        d = dict(zip(columns, row))
        if isinstance(d.get("tags"), str):
            d["tags"] = json.loads(d["tags"])
        return d

    def _checkpoint(self) -> None:
        goals = self._conn.execute("SELECT * FROM goals ORDER BY id").fetchall()
        serializable = [self._row_to_dict(g) for g in goals]
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path.write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False)
        )

    def summary(self) -> str:
        active = self.get_goals(status=GOAL_STATUS_IN_PROGRESS, limit=3)
        todo = self.get_goals(status=GOAL_STATUS_TODO, limit=5)
        done = self.get_goals(status=GOAL_STATUS_DONE, limit=3)
        lines: list[str] = []
        if active:
            lines.append("— В работе:")
            for g in active:
                lines.append(f"  [{g['progress']:.0%}] {g['title']}")
        if todo:
            lines.append("— В очереди:")
            for g in todo[:3]:
                lines.append(f"  · {g['title']} (приоритет: {g['priority']:.2f})")
        if done:
            lines.append("— Завершено:")
            for g in done:
                lines.append(f"  ✔ {g['title']}")
        if not any([active, todo, done]):
            lines.append("— Нет целей. Пора ставить!")
        return "\n".join(lines)

    def close(self) -> None:
        self._conn.close()
