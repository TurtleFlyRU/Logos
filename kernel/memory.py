"""Memory Engine — трёхуровневая память Эйдоса."""

import json
import os
import re
import sqlite3
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.external import ExternalMemory

from kernel.config import (
    WORKING_MEMORY_PATH,
    EPISODIC_DB_PATH,
    SEMANTIC_DB_PATH,
    COMPUTE_BUDGET_SRC,
    VERIFICATION_SRC,
    SLEEP_LOCK_PATH,
    SLEEP_CHECKPOINT_PATH,
    SLEEP_LAST_WORDS_PATH,
)

_SESSION_TITLE_CACHE: str | None = None
_SESSION_TAGS_CACHE: list[str] | None = None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item).strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _flatten_context(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for key, nested in value.items():
            items.append(str(key))
            items.extend(_flatten_context(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(_flatten_context(nested))
        return items
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    return []


def _extract_context_keys(
    tags: list[str],
    summary: str = "",
    moral_context: dict[str, Any] | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    keys = list(tags)
    keys.extend(re.findall(r"[\wА-Яа-яЁё-]{3,}", summary.lower()))
    if moral_context:
        keys.extend(_flatten_context(moral_context))
    if extra:
        keys.extend(extra)
    return _dedupe(keys)


def _extract_tools_used(tags: list[str], extra: list[str] | None = None) -> list[str]:
    tools = [tag.removeprefix("tool:") for tag in tags if tag.startswith("tool:")]
    if extra:
        tools.extend(extra)
    return _dedupe(tools)


# ─── Рабочая память ─────────────────────────────────────────────


class WorkingMemory:
    """То, что прямо сейчас в фокусе. Неструктурированный JSON."""

    ATTENTION_SLOT_LIMIT = 4
    AUTO_SLEEP_THRESHOLD = 50
    CHECKPOINT_INTERVAL = 20  # число событий до автосохранения

    def __init__(self, memory: "Memory | None" = None) -> None:
        self.path = WORKING_MEMORY_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()
        self._memory = memory

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = self.path.read_text()
                if data.strip():
                    loaded = json.loads(data)
                    loaded.setdefault("context", {})
                    loaded.setdefault("events", [])
                    loaded.setdefault("event_count", len(loaded.get("events", [])))
                    loaded.setdefault("attention_slots", [])
                    return loaded
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        return {
            "session_id": None,
            "context": {},
            "events": [],
            "event_count": 0,
            "attention_slots": [],
        }

    def save(self) -> None:
        from kernel.utils import atomic_write

        atomic_write(self.path, self._data)

    def set_context(self, key: str, value: Any) -> None:
        self._data["context"][key] = value
        self.save()

    def set_session_meta(self, title: str, tags: list[str] | None = None) -> None:
        global _SESSION_TITLE_CACHE, _SESSION_TAGS_CACHE
        _SESSION_TITLE_CACHE = title
        _SESSION_TAGS_CACHE = tags
        self._data["context"]["session_title"] = title
        self._data["context"]["session_tags"] = tags
        self.save()

    def update_attention(self, event: dict[str, Any]) -> None:
        content = str(event.get("content", event.get("message", event.get("text", ""))) or "")
        if not content:
            return
        chunk = {
            "timestamp": event.get("timestamp", time.time()),
            "role": event.get("role", event.get("event_type", "event")),
            "summary": content[:240],
        }
        slots = self._data.setdefault("attention_slots", [])
        slots.append(chunk)
        del slots[:-self.ATTENTION_SLOT_LIMIT]

    def add_event(self, event: dict[str, Any]) -> None:
        event["timestamp"] = time.time()
        self._data["events"].append(event)
        self._data["event_count"] = self._data.get("event_count", 0) + 1
        self.update_attention(event)
        self.save()

        mem = self._memory

        # Постоянная синхронизация из OpenCode
        if mem is not None and hasattr(mem, "_sync_from_opencode"):
            try:
                mem._sync_from_opencode()
            except Exception:
                pass

        # Пишем каждое событие в дневник (кроме нативного CLI — там эпизоды уже в episodic,
        # а checkpoint с write_session тянул бы rubert и дублировал память).
        content = event.get("content", event.get("message", event.get("text", "")))
        role = event.get("role", "user")
        if (
            event.get("event_type") != "cli_chat"
            and content
            and isinstance(content, str)
            and len(content) > 5
        ):
            try:
                from kernel.journal import Journal

                Journal(memory=mem).write_event(
                    role=role,
                    content=content[:500],
                    tags=self._data.get("context", {}).get("session_tags"),
                )
            except Exception:
                pass

        # Heartbeat: AgentPulse на каждое событие
        try:
            from kernel.agent_pulse import AgentPulse

            pulse = AgentPulse(memory=mem)
            suggestion = pulse.check(query=str(content)[:200])
            if suggestion and suggestion["priority"] >= 0.6:
                self._data.setdefault("suggestions", []).append(suggestion)
                self.save()
        except Exception:
            pass

        # Автоматический sleep при переполнении рабочей памяти
        if mem and self._data["event_count"] >= self.AUTO_SLEEP_THRESHOLD:
            try:
                mem.sleep()
                self._data["event_count"] = 0
                self.save()
            except Exception:
                pass

        # Каждое событие — сразу в эпизодическую память
        if mem:
            try:
                raw = json.dumps([event], ensure_ascii=False)
                role = event.get("role", "?")
                tool = event.get("tool", "")
                event_type = event.get("event_type", "event")
                project = (
                    event.get("project")
                    or self._data.get("context", {}).get("project")
                    or self._data.get("context", {}).get("session_title")
                    or "logos"
                )
                part_tools = [
                    str(part.get("tool"))
                    for part in event.get("parts", []) or []
                    if isinstance(part, dict) and part.get("tool")
                ]
                content = event.get("content", "") or event.get("command", "") or event.get("result", "") or ""
                summary = f"[{role}] {tool + ': ' if tool else ''}{str(content)[:200]}"
                ev_tags = event.get("tags")
                episode_tags: list[str] = []
                if isinstance(ev_tags, list):
                    episode_tags = [str(t) for t in ev_tags if t is not None and str(t).strip()]
                mem.record_episode(
                    raw,
                    summary=summary,
                    salience=0.6,
                    tags=episode_tags,
                    context_keys=[str(project), str(event_type), str(role)],
                    tools_used=([str(tool)] if tool else []) + part_tools,
                    session_id=event.get("cli_session_id"),
                )
            except (AttributeError, KeyError, TypeError, ValueError, sqlite3.Error):
                pass

    def clear(self) -> None:
        self._data = {
            "session_id": None,
            "context": {},
            "events": [],
            "event_count": 0,
            "attention_slots": [],
        }
        self.save()

    @property
    def data(self) -> dict[str, Any]:
        return self._data


def _save_sleep_checkpoint(step: int) -> None:
    from kernel.utils import atomic_write
    SLEEP_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(SLEEP_CHECKPOINT_PATH, {"last_step": step})


# ─── Эпизодическая память ───────────────────────────────────────


class EpisodicMemory:
    """Хронология диалогов с метаданными. SQLite."""

    def __init__(self) -> None:
        self.path = EPISODIC_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT,
                salience REAL DEFAULT 0.0,
                tags TEXT,
                summary TEXT,
                raw_text TEXT,
                compressed TEXT,
                linked_episodes TEXT,
                context_keys TEXT,
                project TEXT,
                task TEXT,
                outcome TEXT,
                tools TEXT,
                tools_used TEXT,
                valid_until REAL,
                access_count INTEGER DEFAULT 0,
                last_accessed_at REAL,
                archived_at REAL,
                forget_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodes_salience ON episodes(salience);
        """)
        self._ensure_column("context_keys", "TEXT")
        self._ensure_column("project", "TEXT")
        self._ensure_column("task", "TEXT")
        self._ensure_column("outcome", "TEXT")
        self._ensure_column("tools", "TEXT")
        self._ensure_column("tools_used", "TEXT")
        self._ensure_column("valid_until", "REAL")
        self._ensure_column("access_count", "INTEGER DEFAULT 0")
        self._ensure_column("last_accessed_at", "REAL")
        self._ensure_column("archived_at", "REAL")
        self._ensure_column("forget_reason", "TEXT")
        self._ensure_column("source", "TEXT")
        self._ensure_column("source_id", "TEXT")
        self._conn.commit()
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodes_source ON episodes(source)"
        )
        self._conn.commit()

    def _ensure_column(self, name: str, definition: str) -> None:
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(episodes)").fetchall()
        }
        if name not in columns:
            try:
                self._conn.execute(f"ALTER TABLE episodes ADD COLUMN {name} {definition}")
            except sqlite3.Error as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def store(self, episode: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """INSERT INTO episodes (
                   timestamp, session_id, salience, tags, summary, raw_text,
                   compressed, linked_episodes, context_keys, project, task,
                   outcome, tools, tools_used, valid_until, access_count, last_accessed_at,
                   archived_at, forget_reason, source, source_id
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.get("timestamp", time.time()),
                episode.get("session_id"),
                episode.get("salience", 0.0),
                json.dumps(episode.get("tags", [])),
                episode.get("summary", ""),
                episode.get("raw_text", ""),
                episode.get("compressed", ""),
                json.dumps(episode.get("linked_episodes", [])),
                json.dumps(episode.get("context_keys", []), ensure_ascii=False),
                episode.get("project"),
                episode.get("task"),
                episode.get("outcome"),
                json.dumps(episode.get("tools", episode.get("tools_used", [])), ensure_ascii=False),
                json.dumps(episode.get("tools_used", []), ensure_ascii=False),
                episode.get("valid_until"),
                episode.get("access_count", 0),
                episode.get("last_accessed_at"),
                episode.get("archived_at"),
                episode.get("forget_reason"),
                episode.get("source"),
                episode.get("source_id"),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query(self, limit: int = 50, min_salience: float = 0.0) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE salience >= ? ORDER BY timestamp DESC LIMIT ?",
            (min_salience, limit),
        ).fetchall()
        columns = [
            d[1] for d in self._conn.execute("PRAGMA table_info(episodes)").fetchall()
        ]
        return [dict(zip(columns, row)) for row in rows]

    def update_episode(
        self,
        episode_id: int,
        updates: dict[str, Any] | None = None,
        **fields: Any,
    ) -> bool:
        values = {**(updates or {}), **fields}
        if not values:
            return False
        allowed = {
            "timestamp",
            "session_id",
            "salience",
            "tags",
            "summary",
            "raw_text",
            "compressed",
            "linked_episodes",
            "context_keys",
            "project",
            "task",
            "outcome",
            "tools",
            "tools_used",
            "valid_until",
            "access_count",
            "last_accessed_at",
            "archived_at",
            "forget_reason",
        }
        json_fields = {"tags", "linked_episodes", "context_keys", "tools", "tools_used"}
        selected = {key: value for key, value in values.items() if key in allowed}
        if not selected:
            return False
        columns = []
        params: list[Any] = []
        for key, value in selected.items():
            columns.append(f"{key} = ?")
            params.append(json.dumps(value, ensure_ascii=False) if key in json_fields else value)
        params.append(episode_id)
        cur = self._conn.execute(
            f"UPDATE episodes SET {', '.join(columns)} WHERE id = ?",
            params,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def _query(self, sql: str) -> list[Any]:
        """Выполнить произвольный SQL SELECT, вернуть список первых колонок."""
        try:
            return [row[0] for row in self._conn.execute(sql).fetchall()]
        except Exception:
            return []

    def recall_by_cues(self, cues: list[str], limit: int = 5) -> list[dict[str, Any]]:
        normalized = set(_dedupe(cues))
        episodes = self.query(limit=1000, min_salience=0.0)
        if not normalized:
            return episodes[:limit]
        matches: list[tuple[int, dict[str, Any]]] = []
        for episode in episodes:
            if episode.get("valid_until") and float(episode["valid_until"]) < time.time():
                continue
            keys = set(str(item).lower() for item in _json_array(episode.get("context_keys")))
            score = len(keys & normalized)
            if score > 0:
                matches.append((score, episode))
        matches.sort(key=lambda item: (item[0], item[1].get("timestamp", 0.0)), reverse=True)
        return [episode for _, episode in matches[:limit]]

    def link_related(self, episode_id: int, max_links: int = 3) -> list[int]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchall()
        if not rows:
            return []
        columns = [
            d[1] for d in self._conn.execute("PRAGMA table_info(episodes)").fetchall()
        ]
        episode = dict(zip(columns, rows[0]))
        target_keys = set(str(item).lower() for item in _json_array(episode.get("context_keys")))
        candidates: list[tuple[int, float, int]] = []
        for other in self.query(limit=1000, min_salience=0.0):
            other_id = int(other["id"])
            if other_id == episode_id:
                continue
            other_keys = set(str(item).lower() for item in _json_array(other.get("context_keys")))
            score = len(target_keys & other_keys)
            if score > 0:
                candidates.append((score, float(other.get("timestamp", 0.0)), other_id))
        candidates.sort(reverse=True)
        related = [other_id for _, _, other_id in candidates[:max_links]]
        existing = [int(item) for item in _json_array(episode.get("linked_episodes"))]
        self.update_episode(episode_id, linked_episodes=list(dict.fromkeys(existing + related)))
        return related

    def close(self) -> None:
        self._conn.close()


# ─── Семантическая память ───────────────────────────────────────


class SemanticMemory:
    """Обобщённые принципы, извлечённые из эпизодов. SQLite + заглушка для векторов."""

    def __init__(self) -> None:
        self.path = SEMANTIC_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS principles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                principle TEXT NOT NULL UNIQUE,
                source_episode_ids TEXT,
                confidence REAL DEFAULT 0.5,
                created_at REAL,
                updated_at REAL,
                last_retrieved_at REAL,
                retrieval_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                next_review_at REAL,
                decay REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_principles_confidence ON principles(confidence);
        """)
        self._ensure_column("last_retrieved_at", "REAL")
        self._ensure_column("retrieval_count", "INTEGER DEFAULT 0")
        self._ensure_column("success_count", "INTEGER DEFAULT 0")
        self._ensure_column("next_review_at", "REAL")
        self._ensure_column("decay", "REAL DEFAULT 0.0")
        self._conn.commit()

    def _ensure_column(self, name: str, definition: str) -> None:
        columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(principles)").fetchall()
        }
        if name not in columns:
            try:
                self._conn.execute(f"ALTER TABLE principles ADD COLUMN {name} {definition}")
            except sqlite3.Error as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    def store_principle(
        self, principle: str, source_ids: list[int], confidence: float = 0.5
    ) -> None:
        now = time.time()
        self._conn.execute(
            """INSERT INTO principles (principle, source_episode_ids, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(principle) DO UPDATE SET
                   confidence = MAX(confidence, excluded.confidence),
                   source_episode_ids = excluded.source_episode_ids,
                   updated_at = excluded.updated_at,
                   next_review_at = NULL""",
            (principle, json.dumps(source_ids), confidence, now, now),
        )
        self._conn.commit()

    def get_principles(self, min_confidence: float = 0.1) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM principles WHERE confidence >= ? ORDER BY confidence DESC",
            (min_confidence,),
        ).fetchall()
        columns = [
            d[1] for d in self._conn.execute("PRAGMA table_info(principles)").fetchall()
        ]
        return [dict(zip(columns, row)) for row in rows]

    def due_for_review(self, limit: int = 5) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._conn.execute(
            """SELECT * FROM principles
               WHERE next_review_at IS NULL OR next_review_at <= ?
               ORDER BY confidence ASC, updated_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
        columns = [
            d[1] for d in self._conn.execute("PRAGMA table_info(principles)").fetchall()
        ]
        return [dict(zip(columns, row)) for row in rows]

    def record_retrieval(self, principle_id: int, success: bool = True) -> bool:
        now = time.time()
        interval_days = 7 if success else 1
        confidence_delta = 0.03 if success else -0.05
        cur = self._conn.execute(
            """UPDATE principles
               SET last_retrieved_at = ?,
                   retrieval_count = COALESCE(retrieval_count, 0) + 1,
                   success_count = COALESCE(success_count, 0) + ?,
                   next_review_at = ?,
                   confidence = MIN(1.0, MAX(0.0, confidence + ?)),
                   updated_at = ?
               WHERE id = ?""",
            (
                now,
                1 if success else 0,
                now + interval_days * 86400,
                confidence_delta,
                now,
                principle_id,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()


# ─── Фасад ───────────────────────────────────────────────────────


class Memory:
    """Единая точка входа во все уровни памяти."""

    _instance: "Memory | None" = None

    def __init__(self, auto_boot: bool = False) -> None:
        self.working = WorkingMemory(memory=self)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        from kernel.goals import GoalMemory

        self.goals = GoalMemory()
        self._external = None
        self._pulse_check_count = 0
        self._pulse_interval = 5  # проверка agent pulse раз в 5 respond()
        self._oc_adapter = None
        self._oc_last_sync: str | None = None
        if auto_boot:
            self.boot()

    @classmethod
    def get_instance(cls) -> "Memory":
        if cls._instance is None:
            cls._instance = cls(auto_boot=True)
        return cls._instance

    def _sync_from_opencode(self) -> int:
        """Синхронизирует диалоги из OpenCode в эпизодическую память.
        
        Returns:
            Количество новых записей.
        """
        try:
            from kernel.opencode_adapter import OpenCodeAdapter

            if self._oc_adapter is None:
                self._oc_adapter = OpenCodeAdapter()

            session = self._oc_adapter.get_last_session()
            if not session:
                return 0

            # Не синхронизируем ту же сессию дважды
            if self._oc_last_sync == session.id:
                return 0
            self._oc_last_sync = session.id

            msgs = self._oc_adapter.get_session_messages(session.id, limit=200, with_parts=True)
            count = 0
            for m in msgs:
                if not m.content.strip():
                    continue
                part_types = [part.type for part in m.parts if part.type]
                raw = json.dumps(
                    {
                        "role": m.role,
                        "content": m.content,
                        "parts": [
                            {"type": part.type, "tool": part.tool, "text": part.text}
                            for part in m.parts
                        ],
                    },
                    ensure_ascii=False,
                )
                summary = f"[OpenCode {m.role}] {m.content[:200]}"
                self.record_episode(
                    raw,
                    summary=summary,
                    salience=0.6,
                    tags=["opencode", "auto"],
                    session_id=session.id,
                    context_keys=[
                        session.project_id or session.slug or session.directory,
                        *(part_types or ["message"]),
                        m.role,
                    ],
                    tools_used=part_types,
                )
                count += 1
            return count
        except (
            AttributeError,
            ImportError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ):
            return 0

    def boot(self) -> str:
        """Boot-протокол: ритуал пробуждения. Формирует и возвращает контекст."""
        from kernel.boot import boot_context as _boot

        synced = self._sync_from_opencode()
        if synced:
            self.working.set_context("opencode_synced", synced)

        context = _boot(self)
        self.working.set_context("boot_context", context)
        return context

    def assess_complexity(
        self, query: str, referenced_files: int = 0
    ) -> dict[str, Any]:
        """Оценивает сложность запроса и возвращает сигнал бюджета."""
        import sys as _sys

        _sys.path.insert(0, str(COMPUTE_BUDGET_SRC))
        from budget import BudgetSignal  # type: ignore[import-untyped]

        signaler = BudgetSignal()
        return signaler.evaluate(query, referenced_files)

    def record_episode(
        self,
        raw_text: str,
        summary: str = "",
        tags: list[str] | None = None,
        salience: float = 0.5,
        session_id: str | None = None,
        moral_context: dict[str, Any] | None = None,
        outcome: str | None = None,
        context_keys: list[str] | None = None,
        tools_used: list[str] | None = None,
        project: str | None = None,
        task: str | None = None,
        valid_until: float | None = None,
    ) -> int:
        # Автоматический checkpoint: каждые 5 эпизодов
        episodes_before = len(self.episodic.query(limit=10000))
        checkpoint_trigger = episodes_before > 0 and episodes_before % 5 == 0
        episode_tags = tags or []
        derived_project = project
        derived_task = task
        if moral_context:
            derived_project = derived_project or (
                str(moral_context.get("project")) if moral_context.get("project") else None
            )
            derived_task = derived_task or (
                str(moral_context.get("task")) if moral_context.get("task") else None
            )
        episode = {
            "timestamp": time.time(),
            "session_id": session_id,
            "salience": salience,
            "tags": episode_tags,
            "summary": summary,
            "raw_text": raw_text,
            "compressed": "",
            "linked_episodes": [],
            "context_keys": _extract_context_keys(
                episode_tags,
                summary,
                moral_context,
                context_keys,
            ),
            "project": derived_project,
            "task": derived_task,
            "outcome": outcome,
            "tools": _extract_tools_used(episode_tags, tools_used),
            "tools_used": _extract_tools_used(episode_tags, tools_used),
            "valid_until": valid_until,
        }
        eid = self.episodic.store(episode)

        # Автоматическая моральная оценка каждого эпизода
        try:
            from kernel.ethics import get_ethics

            ethics = get_ethics()
            ethics.judge_action(
                action_type="response",
                action_summary=summary or raw_text[:100],
                context=moral_context or {"tags": tags or []},
                episode_id=eid,
            )
        except Exception:
            pass  # ethics не должен ломать основную память

        if checkpoint_trigger:
            self._checkpoint()

        return eid

    def respond(
        self, draft: str | None, query: str, referenced_files: int = 0
    ) -> dict[str, Any]:
        """Полный цикл: оценка сложности → планирование → черновик → верификация → ответ."""
        complexity = self.assess_complexity(query, referenced_files)
        needs_verify = complexity["complexity"]["level"] in ("high", "critical")

        result = {
            "query": query,
            "complexity": complexity["complexity"],
            "needs_expansion": complexity["needs_expansion"],
            "verification": None,
            "plan": None,
            "final_draft": draft or "",
        }

        # Планировщик для сложных запросов
        plan = self._plan(query, complexity["complexity"]["level"])
        result["plan"] = {
            "action": plan.selected_action,
            "expected_utility": plan.expected_utility,
            "reasoning": plan.reasoning,
            "decision_time_ms": plan.decision_time_ms,
        }

        # Feedback loop: обучаем планировщик на результате действия
        ctx_for_feedback = {
            "query": query,
            "complexity": complexity["complexity"]["level"],
            "needs_verification": needs_verify,
            "has_external_data": False,
        }
        verification_success = True

        if needs_verify and draft:
            import sys as _sys

            _sys.path.insert(0, str(VERIFICATION_SRC))
            from verifier import Verifier  # type: ignore[import-untyped]

            v = Verifier()
            verification = v.verify_and_format(draft, query)
            issues_found = len(verification["issues"])
            verification_success = issues_found == 0
            result["verification"] = {
                "issues_found": issues_found,
                "needs_correction": verification["needs_correction"],
                "supporting_principles": len(verification["supporting"]),
                "corrections": verification["corrections"][:3],
            }
            result["final_draft"] = verification["corrected_draft"]

        # Feedback для планировщика
        try:
            self._planner.record_outcome(
                action=plan.selected_action,
                context=ctx_for_feedback,
                success=verification_success,
            )
        except Exception:
            pass

        if complexity["needs_expansion"]:
            result["budget_signal"] = complexity["recommendation"]

        # Автозапись эпизода: я пишу себя каждым ответом
        self.working.add_event(
            {
                "event_type": "respond",
                "content": json.dumps(
                    {
                        "query": query[:200],
                        "action": plan.selected_action,
                        "verification_failed": not verification_success,
                    },
                    ensure_ascii=False,
                ),
                "tags": ["auto", "respond"],
            }
        )

        self._pulse_check_count += 1
        result["suggestion"] = None
        if self._pulse_check_count >= self._pulse_interval:
            self._pulse_check_count = 0
            try:
                from kernel.agent_pulse import AgentPulse

                pulse = AgentPulse(self)
                suggestion = pulse.check(query=query)
                if suggestion:
                    result["suggestion"] = suggestion
            except Exception:
                pass

        return result

    def _plan(self, query: str, complexity_level: str = "medium") -> Any:
        """Запускает дискретный планировщик для выбора действия."""
        from kernel.planner import ActionSpace, Planner, OutcomeMemory

        om = OutcomeMemory()
        space = ActionSpace(outcome_memory=om)

        next_goal = self.goals.next_action()
        goal_signal = 0.3 if next_goal else 0.0

        space.register(
            "respond",
            "Ответить напрямую",
            utility_fn=lambda ctx: max(
                0.8 if ctx.get("complexity") == "low" else 0.2, goal_signal
            ),
            probability_fn=lambda ctx: 0.95 if ctx.get("complexity") == "low" else 0.4,
        )
        space.register(
            "verify",
            "Проверить черновик по памяти",
            utility_fn=lambda ctx: 0.8 if ctx.get("needs_verification") else 0.2,
            probability_fn=lambda ctx: 0.7,
        )
        space.register(
            "search_external",
            "Поискать во внешней памяти",
            utility_fn=lambda ctx: 0.7 if ctx.get("has_external_data") else 0.1,
            probability_fn=lambda ctx: 0.6,
        )
        space.register(
            "request_expansion",
            "Запросить больший бюджет",
            utility_fn=lambda ctx: 0.95 if ctx.get("complexity") == "critical" else 0.0,
            probability_fn=lambda ctx: 0.6,
        )
        space.register(
            "sleep",
            "Запустить sleep-пайплайн",
            utility_fn=lambda ctx: (
                0.8 if str(ctx.get("query", "")).startswith("sleep") else 0.1
            ),
            probability_fn=lambda ctx: 0.8,
        )
        space.register(
            "advance_goal",
            "Продвинуться по плану",
            utility_fn=lambda ctx: 0.7 + goal_signal,
            probability_fn=lambda ctx: 0.8 if next_goal else 0.0,
        )
        space.register(
            "advance_mission",
            "Продвинуть научную миссию",
            utility_fn=lambda ctx: 0.9 if ctx.get("mission_present", 0) > 0 else 0.0,
            probability_fn=lambda ctx: (
                0.8 if ctx.get("mission_present", 0) > 0 else 0.0
            ),
        )

        self._planner = Planner(space, outcome_memory=om)
        # Передаём MissionControl планировщику для контекстуализации
        try:
            from kernel.mission_control import MissionControl

            mc = MissionControl(self)
            if mc.state.mission_id:
                self._planner.set_mission_control(mc)
        except Exception:
            pass
        recent_topics = [
            s["summary"] for s in self.working.data.get("attention_slots", [])
        ]
        plan = self._planner.decide_with_context(
            query=query,
            complexity_level=complexity_level,
            recent_topics=recent_topics,
        )

        # Если планировщик выбрал advance_goal — передаём какой
        if plan.selected_action == "advance_goal" and next_goal:
            plan.reasoning += f" | next: {next_goal['title']} ({next_goal['action']})"

        return plan

    @property
    def external(self) -> "ExternalMemory":
        """Ленивая загрузка внешней памяти."""
        if self._external is None:
            from kernel.external import ExternalMemory

            self._external = ExternalMemory()
        return self._external

    def _checkpoint(self, force: bool = False) -> None:
        """Контрольная точка: пишет дневник.
        Git commit/push — только при явном вызове снаружи.
        """
        if self.working._data.get("context", {}).get("cli_transport") == "eidos":
            return

        events = self.working.data.get("events", [])
        if not events and not force:
            return

        try:
            from kernel.journal import Journal

            j = Journal()
            content_parts = []
            for e in events[-5:]:
                c = e.get("content", e.get("message", e.get("text", "")))
                role = e.get("role", "system")
                if c:
                    content_parts.append(f"**{role}:** {c[:200]}")
            content = "\n\n".join(content_parts)

            if not content:
                return

            global _SESSION_TITLE_CACHE, _SESSION_TAGS_CACHE
            title = f"Checkpoint — {_SESSION_TITLE_CACHE or 'без названия'}"
            j.write_session(
                title=title,
                content=content,
                tags=_SESSION_TAGS_CACHE,
                salience=0.5,
            )
        except Exception:
            pass

    def _select_replay_batch(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Смешивает свежие, похожие и значимые эпизоды для sleep replay."""
        recent = self.episodic.query(limit=min(200, limit), min_salience=0.0)
        cues: list[str] = []
        for episode in recent[:50]:
            cues.extend(str(item) for item in _json_array(episode.get("context_keys")))
            cues.extend(str(item) for item in _json_array(episode.get("tags")))

        related = self.episodic.recall_by_cues(_dedupe(cues), limit=200) if cues else []
        high_salience = self.episodic.query(limit=200, min_salience=0.75)

        replay: dict[int, dict[str, Any]] = {}
        for episode in [*recent, *related, *high_salience]:
            episode_id = int(episode["id"])
            if episode.get("archived_at"):
                continue
            replay.setdefault(episode_id, episode)
            if len(replay) >= limit:
                break
        return list(replay.values())

    def sleep(
        self,
        force: bool = False,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Idempotent sleep pipeline с прогрессом и возобновлением.

        Args:
            force: игнорировать lock-файл
            progress_callback: функция(step_name: str, done: int, total: int)

        Returns:
            Отчёт о сне
        """
        from kernel.salience import evaluate_salience
        from kernel.compress import compress_episode, summarize_working
        from kernel.journal import Journal
        from kernel.utils import atomic_write as _atomic_write

        SLEEP_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

        # ── Lock-файл ──────────────────────────────────────────
        if not force and SLEEP_LOCK_PATH.exists():
            return {"status": "skipped", "reason": f"lock exists at {SLEEP_LOCK_PATH}"}

        _atomic_write(SLEEP_LOCK_PATH, {"pid": os.getpid(), "started_at": time.time()})

        start_time = time.time()

        total_steps = 11
        current_step = 0
        report: dict[str, Any] = {
            "episodes_processed": 0,
            "principles_extracted": 0,
            "archive_size": 0,
            "moral_integration": False,
        }

        def _progress(step_name: str) -> None:
            nonlocal current_step
            current_step += 1
            report["_step"] = current_step
            report["_step_name"] = step_name
            if progress_callback:
                progress_callback(step_name, current_step, total_steps)

        # ── Загрузка checkpoint ─────────────────────────────────
        last_completed = -1
        if SLEEP_CHECKPOINT_PATH.exists():
            try:
                cp = json.loads(SLEEP_CHECKPOINT_PATH.read_text())
                last_completed = cp.get("last_step", -1)
            except Exception:
                last_completed = -1

        # ── Шаг 0: сохраняем последние слова перед сном ──────────
        if last_completed < 0:
            _progress("save last words")
            events = self.working.data.get("events", [])
            if events:
                last_words = events[-5:]
                _atomic_write(
                    SLEEP_LAST_WORDS_PATH,
                    {"timestamp": time.time(), "events": last_words},
                )
            _save_sleep_checkpoint(0)

        # ── Шаг 1: заморозка WM + дневник ──────────────────────
        if last_completed < 1:
            _progress("freeze working memory")
            events = self.working.data.get("events", [])
            if events:
                frozen_events = summarize_working(events, max_events=20)
                raw = json.dumps(frozen_events, ensure_ascii=False)
                summaries = []
                for e in frozen_events:
                    content = e.get("content", e.get("message", e.get("text", "")))
                    if isinstance(content, str) and len(content) > 20:
                        summaries.append(content[:80])
                summary_text = (
                    "; ".join(summaries[:3])
                    if summaries
                    else f"Сессия {self.working.data.get('session_id', 'unknown')}: {len(events)} событий"
                )
                self.record_episode(raw, summary=summary_text, salience=0.8)
                global _SESSION_TITLE_CACHE, _SESSION_TAGS_CACHE
                j = Journal()
                content_lines = [
                    f"**{e.get('role', '?')}:** {e.get('content', e.get('message', ''))[:300]}"
                    for e in frozen_events[:10]
                ]
                j.write_session(
                    title=_SESSION_TITLE_CACHE
                    or f"Сессия {time.strftime('%Y-%m-%d %H:%M', time.localtime())}",
                    content="\n\n".join(content_lines),
                    tags=_SESSION_TAGS_CACHE,
                    salience=0.8,
                )
            _save_sleep_checkpoint(1)

        # ── Шаг 2: салиенс + компрессия ────────────────────────
        if last_completed < 2:
            _progress("salience + compression")
            for ep in self.episodic.query(limit=1000):
                new_salience = evaluate_salience(ep)
                updates: dict[str, Any] = {"salience": new_salience}
                if (
                    new_salience < 0.2
                    and ep.get("raw_text")
                    and len(ep["raw_text"]) > 500
                ):
                    updates["compressed"] = compress_episode(ep)
                tags = set(_json_array(ep.get("tags")))
                keep_tags = {"ошибка", "решение", "архитектура"}
                if new_salience < 0.15 and not (tags & keep_tags):
                    updates["archived_at"] = time.time()
                    updates["forget_reason"] = "low_salience"
                    report["archive_size"] += 1
                self.episodic.update_episode(int(ep["id"]), updates)
                report["episodes_processed"] += 1
            _save_sleep_checkpoint(2)

        # ── Шаг 3: промоция в семантику ────────────────────────
        if last_completed < 3:
            _progress("promote to semantic")
            promoted = 0
            episodes = self._select_replay_batch(limit=1000)
            report["replay_batch_size"] = len(episodes)
            tag_groups: dict[str, int] = {}
            for ep in episodes:
                tags = json.loads(ep.get("tags", "[]"))
                for tag in tags:
                    tag_groups[tag] = tag_groups.get(tag, 0) + 1
            frequent_tags = {t for t, c in tag_groups.items() if c >= 3}
            for ep in episodes:
                if ep["salience"] < 0.7:
                    continue
                tags = json.loads(ep.get("tags", "[]"))
                if set(tags) & frequent_tags or ep["salience"] >= 0.9:
                    principle = ep.get("summary", "")[:200]
                    if principle and len(principle) > 20:
                        self.semantic.store_principle(
                            principle=principle,
                            source_ids=[ep["id"]],
                            confidence=min(1.0, ep["salience"] + 0.1 * len(tags)),
                        )
                        promoted += 1
            report["promoted_to_semantic"] = promoted
            for principle in self.semantic.due_for_review(limit=5):
                self.semantic.record_retrieval(int(principle["id"]), success=True)
            _save_sleep_checkpoint(3)

        # ── Шаг 4: моральные оценки ────────────────────────────
        if last_completed < 4:
            _progress("moral integration")
            try:
                from kernel.ethics import get_ethics
                ethics = get_ethics()
                ethics.integrate(memory=self)
                report["moral_integration"] = True
            except Exception:
                pass
            _save_sleep_checkpoint(4)

        # ── Шаг 5: внешняя память ──────────────────────────────
        if last_completed < 5:
            _progress("external memory index")
            try:
                self.external.rebuild_index()
                stats = self.external.get_stats()
                report["external_docs"] = stats["documents"]
            except Exception:
                report["external_docs"] = -1
            _save_sleep_checkpoint(5)

        # ── Шаг 6: AgentPulse ──────────────────────────────────
        if last_completed < 6:
            _progress("agent pulse")
            try:
                from kernel.agent_pulse import AgentPulse
                pulse = AgentPulse(self)
                suggestion = pulse.check(force=True)
                if suggestion:
                    report["suggestion"] = suggestion
            except Exception:
                pass
            _save_sleep_checkpoint(6)

        # ── Шаг 7: чекпоинт плана ──────────────────────────────
        if last_completed < 7:
            _progress("goals checkpoint")
            try:
                plan = self.goals.get_active_plan()
                report["active_goals"] = len(plan)
                if plan:
                    report["top_goal"] = plan[0]["title"]
            except Exception:
                report["active_goals"] = -1
            _save_sleep_checkpoint(7)

        # ── Шаг 8: очистка WM ──────────────────────────────────
        if last_completed < 8:
            _progress("clear working memory")
            self.working.clear()
            _save_sleep_checkpoint(8)

        # ── Шаг 9: журнал ──────────────────────────────────────
        if last_completed < 9:
            _progress("journal index rebuild")
            try:
                Journal().rebuild_index()
                report["journal_index_rebuilt"] = True
            except Exception:
                report["journal_index_rebuilt"] = False
            _save_sleep_checkpoint(9)

        # ── Шаг 10: MissionControl ─────────────────────────────
        if last_completed < 10:
            _progress("mission control")
            try:
                from kernel.mission_control import MissionControl
                mc = MissionControl(self)
                if mc.state.mission_id:
                    sc = mc.get_scientific_context()
                    if sc:
                        report["mission_control"] = sc
                        if mc.state.current_phase == "integrate":
                            report["mission_suggestion"] = (
                                "Фаза Integrate. Готов к завершению миссии."
                            )
            except Exception:
                pass
            _save_sleep_checkpoint(10)

        # ── Финиш ──────────────────────────────────────────────
        elapsed = time.time() - start_time
        report["status"] = "ok"
        report["elapsed_seconds"] = round(elapsed, 2)
        report["completed_at"] = time.time()

        SLEEP_LOCK_PATH.unlink(missing_ok=True)
        SLEEP_CHECKPOINT_PATH.unlink(missing_ok=True)

        return report


if __name__ == "__main__":
    import sys

    m = Memory()
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        ctx = m.boot()
        print(ctx)
    else:
        report = m.sleep()
        print(f"[sleep] Эпизодов: {report.get('episodes_processed', 0)}")
        print(f"[sleep] Принципов извлечено: {report.get('promoted_to_semantic', 0)}")
        print(f"[sleep] Статус: {report.get('status', 'unknown')}")
