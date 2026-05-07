"""Мониторинг здоровья Эйдоса — метрики памяти, объём, состояние."""

import json
import sqlite3
import time
from typing import Any

from kernel.memory import DATA_ROOT


def memory_report() -> dict[str, Any]:
    """Формирует отчёт о состоянии всех уровней памяти."""
    report: dict[str, Any] = {
        "timestamp": time.time(),
        "working": _working_status(),
        "episodic": _episodic_status(),
        "semantic": _semantic_status(),
        "journal": _journal_status(),
        "moral": _moral_status(),
    }

    # Общая оценка здоровья
    issues = []
    if report["working"]["event_count"] > 50:
        issues.append("Рабочая память переполнена (>50 событий)")
    if report["episodic"]["total_episodes"] > 1000:
        issues.append("Много эпизодов — пора архивировать")
    if not report["semantic"]["has_principles"]:
        issues.append("Семантическая память пуста — нет извлечённых принципов")
    report["issues"] = issues
    report["health"] = "ok" if len(issues) == 0 else "warning"

    return report


def _working_status() -> dict[str, Any]:
    path = DATA_ROOT / "working" / "current.json"
    if not path.exists():
        return {"event_count": 0, "size_bytes": 0, "session_id": None}
    size = path.stat().st_size
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return {"event_count": -1, "size_bytes": size, "error": "corrupt"}
    return {
        "event_count": len(data.get("events", [])),
        "event_count_total": data.get("event_count", 0),
        "size_bytes": size,
        "session_id": data.get("context", {}).get("session_id"),
        "session_title": data.get("context", {}).get("session_title"),
    }


def _episodic_status() -> dict[str, Any]:
    path = DATA_ROOT / "episodic" / "episodes.db"
    if not path.exists():
        return {"total_episodes": 0, "size_bytes": 0}
    size = path.stat().st_size
    try:
        conn = sqlite3.connect(str(path))
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        avg_salience = conn.execute("SELECT AVG(salience) FROM episodes").fetchone()[0] or 0.0
        conn.close()
    except Exception:
        return {"total_episodes": -1, "size_bytes": size, "error": "db_error"}
    return {
        "total_episodes": count,
        "avg_salience": round(avg_salience, 3),
        "size_bytes": size,
    }


def _semantic_status() -> dict[str, Any]:
    path = DATA_ROOT / "semantic" / "knowledge.db"
    if not path.exists():
        return {"principles": 0, "has_principles": False, "size_bytes": 0}
    size = path.stat().st_size
    try:
        conn = sqlite3.connect(str(path))
        count = conn.execute("SELECT COUNT(*) FROM principles").fetchone()[0]
        avg_conf = conn.execute("SELECT AVG(confidence) FROM principles").fetchone()[0] or 0.0
        conn.close()
    except Exception:
        return {"principles": -1, "has_principles": False, "size_bytes": size, "error": "db_error"}
    return {
        "principles": count,
        "avg_confidence": round(avg_conf, 3),
        "has_principles": count > 0,
        "size_bytes": size,
    }


def _journal_status() -> dict[str, Any]:
    path = DATA_ROOT / "journal"
    if not path.exists():
        return {"entries": 0, "files": 0, "size_bytes": 0}
    files = list(path.glob("*.md"))
    index_path = path / "INDEX.md"
    entry_count = 0
    if index_path.exists():
        entry_count = len([line for line in index_path.read_text().split("\n") if line.startswith("| ")])
    total_size = sum(f.stat().st_size for f in files)
    return {
        "entries": entry_count,
        "files": len(files),
        "size_bytes": total_size,
    }


def _moral_status() -> dict[str, Any]:
    path = DATA_ROOT / "episodic" / "moral.db"
    if not path.exists():
        return {"judgments": 0, "size_bytes": 0}
    size = path.stat().st_size
    try:
        conn = sqlite3.connect(str(path))
        count = conn.execute("SELECT COUNT(*) FROM moral_judgments").fetchone()[0]
        conn.close()
    except Exception:
        return {"judgments": -1, "size_bytes": size, "error": "db_error"}
    return {
        "judgments": count,
        "size_bytes": size,
    }
