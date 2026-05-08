"""Data aggregation for Eidos memory dashboard.

Collects all available metrics from memory subsystems
and returns them as flat dicts for Streamlit/JSON rendering.
"""

import json
import sqlite3
import time
from collections import Counter
from datetime import datetime
from typing import Any

from kernel.config import (
    EPISODIC_DB_PATH,
    EXTERNAL_DB_PATH,
    GOALS_DB_PATH,
    INSTRUMENTAL_DB_PATH,
    JOURNAL_DIR,
    MORAL_DB_PATH,
    SEMANTIC_DB_PATH,
    WORKING_MEMORY_PATH,
)
from kernel.health import memory_report
from kernel.instrumental import InstrumentalRegistry


def _query(db_path, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _parse_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def extended_report() -> dict[str, Any]:
    """Full metrics snapshot combining basic health + extended stats."""
    report: dict[str, Any] = {}
    report["timestamp"] = time.time()
    report["ts_human"] = _parse_timestamp(time.time())

    # Base health
    health = memory_report()
    report.update(health)

    # ── Episodic: depth stats ──
    ep = report.get("episodic", {})
    ep["salience_distribution"] = {
        "high_0.8+": len(_query(EPISODIC_DB_PATH, "SELECT 1 FROM episodes WHERE salience >= 0.8")),
        "mid_0.5_0.8": len(_query(EPISODIC_DB_PATH, "SELECT 1 FROM episodes WHERE salience >= 0.5 AND salience < 0.8")),
        "low_<0.5": len(_query(EPISODIC_DB_PATH, "SELECT 1 FROM episodes WHERE salience < 0.5")),
    }
    cols = _query(EPISODIC_DB_PATH, "PRAGMA table_info(episodes)")
    col_names = {col[1] for col in cols}
    if "access_count" in col_names:
        rows = _query(EPISODIC_DB_PATH, "SELECT COALESCE(AVG(access_count), 0), COALESCE(SUM(access_count), 0) FROM episodes")
        ep["avg_access_count"] = round(rows[0][0], 2) if rows else 0
        ep["total_access_count"] = rows[0][1] if rows else 0
    else:
        ep["avg_access_count"] = None
        ep["total_access_count"] = None

    # Tag frequency
    all_tags: list[str] = []
    tag_rows = _query(EPISODIC_DB_PATH, "SELECT tags FROM episodes WHERE tags IS NOT NULL AND tags != ''")
    for (tags_json,) in tag_rows:
        try:
            all_tags.extend(json.loads(tags_json))
        except Exception:
            pass
    ep["top_tags"] = Counter(all_tags).most_common(10)
    report["episodic"] = ep

    # ── Semantic: by confidence ──
    sm = report.get("semantic", {})
    conf_low = len(_query(SEMANTIC_DB_PATH, "SELECT 1 FROM principles WHERE confidence < 0.5"))
    conf_mid = len(_query(SEMANTIC_DB_PATH, "SELECT 1 FROM principles WHERE confidence >= 0.5 AND confidence < 0.8"))
    conf_high = len(_query(SEMANTIC_DB_PATH, "SELECT 1 FROM principles WHERE confidence >= 0.8"))
    sm["confidence_distribution"] = {"high_0.8+": conf_high, "mid_0.5_0.8": conf_mid, "low_<0.5": conf_low}
    report["semantic"] = sm

    # ── External memory ──
    ext_rows = _query(EXTERNAL_DB_PATH, "SELECT COUNT(*), COUNT(DISTINCT source) FROM documents")
    report["external"] = {
        "documents": ext_rows[0][0] if ext_rows else 0,
        "unique_sources": ext_rows[0][1] if ext_rows else 0,
        "size_bytes": EXTERNAL_DB_PATH.stat().st_size if EXTERNAL_DB_PATH.exists() else 0,
    }

    # ── Goals ──
    goals = {}
    all_goals = _query(GOALS_DB_PATH, "SELECT status, COUNT(*) FROM goals GROUP BY status")
    for status, cnt in all_goals:
        goals[status] = cnt
    report["goals"] = goals

    # ── Instrumental memory ──
    try:
        ir = InstrumentalRegistry()
        report["instrumental"] = ir.get_stats()
        report["instrumental"]["tools_detail"] = ir.recommend(min_confidence=0.0, limit=50)
    except Exception:
        report["instrumental"] = {"total_tools": 0}

    # ── Journal: recent sessions ──
    idx_path = JOURNAL_DIR / "INDEX.md"
    journal_lines = []
    if idx_path.exists():
        lines = idx_path.read_text().split("\n")
        journal_lines = [l for l in lines if l.startswith("| ") and "entry" not in l.lower()][-20:]
    report["journal_recent"] = journal_lines

    # ── Working memory: session breakdown ──
    wm = report.get("working", {})
    if WORKING_MEMORY_PATH.exists():
        try:
            wm_data = json.loads(WORKING_MEMORY_PATH.read_text())
            events = wm_data.get("events", [])
            roles = Counter(e.get("role", "?") for e in events)
            wm["role_breakdown"] = dict(roles.most_common())
        except Exception:
            wm["role_breakdown"] = {}
    report["working"] = wm

    return report


def timeseries_report(limit: int = 1000) -> list[dict[str, Any]]:
    """Chronological episode data for trend charts.

    Returns list of dicts with timestamp, salience, tags, summary length.
    """
    rows = _query(
        EPISODIC_DB_PATH,
        "SELECT timestamp, salience, tags, summary FROM episodes ORDER BY timestamp ASC LIMIT ?",
        (limit,),
    )
    series = []
    for ts, sal, tags_json, summary in rows:
        tags = []
        if tags_json:
            try:
                tags = json.loads(tags_json)
            except Exception:
                pass
        series.append({
            "timestamp": ts,
            "ts_human": _parse_timestamp(ts),
            "salience": sal,
            "tags": tags,
            "summary_len": len(summary or ""),
        })
    return series
