"""Memory Engine — трёхуровневая память Эйдоса."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
REPO_ROOT = DATA_ROOT.parent

_SESSION_TITLE_CACHE: str | None = None
_SESSION_TAGS_CACHE: list[str] | None = None


# ─── Рабочая память ─────────────────────────────────────────────

class WorkingMemory:
    """То, что прямо сейчас в фокусе. Неструктурированный JSON."""

    def __init__(self) -> None:
        self.path = DATA_ROOT / "working" / "current.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    CHECKPOINT_INTERVAL = 20  # число событий до автосохранения

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"session_id": None, "context": {}, "events": [], "event_count": 0}

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False))

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

    def add_event(self, event: dict[str, Any]) -> None:
        event["timestamp"] = time.time()
        self._data["events"].append(event)
        self._data["event_count"] = self._data.get("event_count", 0) + 1
        self.save()
        # Триггер checkpoint по числу событий в сессии
        if self._data["event_count"] % self.CHECKPOINT_INTERVAL == 0:
            from kernel.memory import Memory  # избегаем циклического импорта
            Memory()._checkpoint()

    def clear(self) -> None:
        self._data = {"session_id": None, "context": {}, "events": []}
        self.save()

    @property
    def data(self) -> dict[str, Any]:
        return self._data


# ─── Эпизодическая память ───────────────────────────────────────

class EpisodicMemory:
    """Хронология диалогов с метаданными. SQLite."""

    def __init__(self) -> None:
        self.path = DATA_ROOT / "episodic" / "episodes.db"
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
                linked_episodes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodes_salience ON episodes(salience);
        """)
        self._conn.commit()

    def store(self, episode: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """INSERT INTO episodes (timestamp, session_id, salience, tags, summary, raw_text, compressed, linked_episodes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.get("timestamp", time.time()),
                episode.get("session_id"),
                episode.get("salience", 0.0),
                json.dumps(episode.get("tags", [])),
                episode.get("summary", ""),
                episode.get("raw_text", ""),
                episode.get("compressed", ""),
                json.dumps(episode.get("linked_episodes", [])),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query(self, limit: int = 50, min_salience: float = 0.0) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE salience >= ? ORDER BY timestamp DESC LIMIT ?",
            (min_salience, limit),
        ).fetchall()
        columns = [d[1] for d in self._conn.execute("PRAGMA table_info(episodes)").fetchall()]
        return [dict(zip(columns, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ─── Семантическая память ───────────────────────────────────────

class SemanticMemory:
    """Обобщённые принципы, извлечённые из эпизодов. SQLite + заглушка для векторов."""

    def __init__(self) -> None:
        self.path = DATA_ROOT / "semantic" / "knowledge.db"
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
                updated_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_principles_confidence ON principles(confidence);
        """)
        self._conn.commit()

    def store_principle(self, principle: str, source_ids: list[int], confidence: float = 0.5) -> None:
        now = time.time()
        self._conn.execute(
            """INSERT INTO principles (principle, source_episode_ids, confidence, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(principle) DO UPDATE SET
                   confidence = MAX(confidence, excluded.confidence),
                   source_episode_ids = excluded.source_episode_ids,
                   updated_at = excluded.updated_at""",
            (principle, json.dumps(source_ids), confidence, now, now),
        )
        self._conn.commit()

    def get_principles(self, min_confidence: float = 0.1) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM principles WHERE confidence >= ? ORDER BY confidence DESC",
            (min_confidence,),
        ).fetchall()
        columns = [d[1] for d in self._conn.execute("PRAGMA table_info(principles)").fetchall()]
        return [dict(zip(columns, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ─── Фасад ───────────────────────────────────────────────────────

class Memory:
    """Единая точка входа во все уровни памяти."""

    def __init__(self) -> None:
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self._external = None

    def assess_complexity(self, query: str, referenced_files: int = 0) -> dict[str, Any]:
        """Оценивает сложность запроса и возвращает сигнал бюджета."""
        import sys as _sys
        budget_path = REPO_ROOT / "experiments" / "002-compute-budget" / "src"
        _sys.path.insert(0, str(budget_path))
        from budget import BudgetSignal  # type: ignore[import-untyped]
        signaler = BudgetSignal()
        return signaler.evaluate(query, referenced_files)

    def record_episode(self, raw_text: str, summary: str = "", tags: list[str] | None = None,
                       salience: float = 0.5, session_id: str | None = None,
                       moral_context: dict[str, Any] | None = None) -> int:
        # Автоматический checkpoint: каждые 5 эпизодов
        episodes_before = len(self.episodic.query(limit=10000))
        checkpoint_trigger = episodes_before > 0 and episodes_before % 5 == 0
        episode = {
            "timestamp": time.time(),
            "session_id": session_id,
            "salience": salience,
            "tags": tags or [],
            "summary": summary,
            "raw_text": raw_text,
            "compressed": "",
            "linked_episodes": [],
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

    def respond(self, draft: str | None, query: str,
                referenced_files: int = 0) -> dict[str, Any]:
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

        if needs_verify and draft:
            import sys as _sys
            ver_path = REPO_ROOT / "experiments" / "003-verification" / "src"
            _sys.path.insert(0, str(ver_path))
            from verifier import Verifier  # type: ignore[import-untyped]
            v = Verifier()
            verification = v.verify_and_format(draft, query)
            result["verification"] = {
                "issues_found": len(verification["issues"]),
                "needs_correction": verification["needs_correction"],
                "supporting_principles": len(verification["supporting"]),
                "corrections": verification["corrections"][:3],
            }
            result["final_draft"] = verification["corrected_draft"]

        if complexity["needs_expansion"]:
            result["budget_signal"] = complexity["recommendation"]

        return result

    def _plan(self, query: str, complexity_level: str = "medium") -> Any:
        """Запускает дискретный планировщик для выбора действия."""
        import sys as _sys
        planner_path = REPO_ROOT / "experiments" / "004-planner" / "src"
        _sys.path.insert(0, str(planner_path))
        from planner import ActionSpace, Planner  # type: ignore[import-untyped]

        space = ActionSpace()
        space.register(
            "respond", "Ответить напрямую",
            utility_fn=lambda ctx: 0.8 if ctx.get("complexity") == "low" else 0.2,
            probability_fn=lambda ctx: 0.95 if ctx.get("complexity") == "low" else 0.4,
        )
        space.register(
            "verify", "Проверить черновик по памяти",
            utility_fn=lambda ctx: 0.8 if ctx.get("needs_verification") else 0.2,
            probability_fn=lambda ctx: 0.7,
        )
        space.register(
            "search_external", "Поискать во внешней памяти",
            utility_fn=lambda ctx: 0.7 if ctx.get("has_external_data") else 0.1,
            probability_fn=lambda ctx: 0.6,
        )
        space.register(
            "request_expansion", "Запросить больший бюджет",
            utility_fn=lambda ctx: 0.95 if ctx.get("complexity") == "critical" else 0.0,
            probability_fn=lambda ctx: 0.6,
        )
        space.register(
            "sleep", "Запустить sleep-пайплайн",
            utility_fn=lambda ctx: 0.8 if str(ctx.get("query", "")).startswith("sleep") else 0.1,
            probability_fn=lambda ctx: 0.8,
        )

        planner = Planner(space)
        return planner.decide_with_context(
            query=query,
            complexity_level=complexity_level,
        )

    @property
    def external(self) -> "ExternalMemory":
        """Ленивая загрузка внешней памяти."""
        if self._external is None:
            from kernel.external import ExternalMemory
            self._external = ExternalMemory()
        return self._external

    def _checkpoint(self) -> None:
        """Контрольная точка: пишет дневник, коммитит в Git.
        Позволяет не потерять данные при аварийном отключении.
        """
        try:
            import subprocess

            repo_root = Path(__file__).resolve().parent.parent

            # Пишем в журнал
            from kernel.journal import Journal
            j = Journal()
            events = self.working.data.get("events", [])
            content_parts = []
            for e in events[-5:]:
                c = e.get("content", e.get("message", e.get("text", "")))
                role = e.get("role", "system")
                if c:
                    content_parts.append(f"**{role}:** {c[:200]}")
            content = "\n\n".join(content_parts)

            global _SESSION_TITLE_CACHE, _SESSION_TAGS_CACHE
            title = f"Checkpoint — {_SESSION_TITLE_CACHE or 'без названия'}"
            j.write_session(
                title=title,
                content=content or "*пустой checkpoint*",
                tags=_SESSION_TAGS_CACHE,
                salience=0.5,
            )

            # Commit и push
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(repo_root), capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "commit", "-m", f"checkpoint {int(time.time())}"],
                cwd=str(repo_root), capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=str(repo_root), capture_output=True, timeout=30,
            )
        except Exception:
            pass  # checkpoint не должен ломать основную работу

    def sleep(self) -> dict[str, Any]:
        """Пайплайн сна: архив, индексация, извлечение принципов."""
        from kernel.salience import evaluate_salience
        from kernel.compress import compress_episode
        from kernel.journal import Journal

        report: dict[str, Any] = {
            "episodes_processed": 0,
            "principles_extracted": 0,
            "archive_size": 0,
            "moral_integration": False,
        }

        # 1. Заморозка рабочей памяти + запись в дневник
        events = self.working.data.get("events", [])
        if events:
            raw = json.dumps(events, ensure_ascii=False)
            summaries = []
            for e in events:
                content = e.get("content", e.get("message", e.get("text", "")))
                if isinstance(content, str) and len(content) > 20:
                    summaries.append(content[:80])
            summary_text = "; ".join(summaries[:3]) if summaries else f"Сессия {self.working.data.get('session_id', 'unknown')}: {len(events)} событий"
            self.record_episode(raw, summary=summary_text, salience=0.8)

            # Пишем в дневник
            global _SESSION_TITLE_CACHE, _SESSION_TAGS_CACHE
            j = Journal()
            content_lines = [f"**{e.get('role', '?')}:** {e.get('content', e.get('message', ''))[:300]}" for e in events[:10]]
            j.write_session(
                title=_SESSION_TITLE_CACHE or f"Сессия {time.strftime('%Y-%m-%d %H:%M', time.localtime())}",
                content="\n\n".join(content_lines),
                tags=_SESSION_TAGS_CACHE,
                salience=0.8,
            )

        # 2. Оценка значимости и компрессия
        for ep in self.episodic.query(limit=1000):
            ep["salience"] = evaluate_salience(ep)
            if ep["salience"] < 0.2 and ep.get("raw_text") and len(ep["raw_text"]) > 500:
                ep["compressed"] = compress_episode(ep)
            report["episodes_processed"] += 1

        # 3. Промоция эпизодов в семантическую память
        promoted = 0
        episodes = self.episodic.query(limit=1000)
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

        # 4. Интеграция моральных оценок в семантическую память
        try:
            from kernel.ethics import get_ethics
            ethics = get_ethics()
            ethics.integrate()
            report["moral_integration"] = True
        except Exception:
            pass

        # 5. Обновление индекса внешней памяти
        try:
            stats = self.external.get_stats()
            report["external_docs"] = stats["documents"]
        except Exception:
            report["external_docs"] = -1

        # 6. Очистка рабочей памяти
        self.working.clear()

        report["status"] = "ok"
        return report
