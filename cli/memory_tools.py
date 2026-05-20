"""LLM tools для on-demand доступа к памяти Эйдос (P0–P1).

Включается при ``EIDOS_TOOLS=1`` и ``EIDOS_MEMORY_TOOLS`` не ``0``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from kernel.config import JOURNAL_DIR

_DEFAULT_EPISODIC_LIMIT = 20
_DEFAULT_SEMANTIC_LIMIT = 24
_DEFAULT_JOURNAL_TOP_K = 12
_DEFAULT_EXTERNAL_TOP_K = 8
_MAX_EPISODE_BODY = 48_000
_MAX_JOURNAL_FILE = 64_000


def memory_tools_enabled() -> bool:
    if os.environ.get("EIDOS_TOOLS", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    v = os.environ.get("EIDOS_MEMORY_TOOLS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def memory_tool_specs() -> list[dict[str, Any]]:
    """OpenAI-compatible tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "memory_search_episodic",
                "description": (
                    "Поиск в эпизодической памяти (SQLite episodes). "
                    "Укажите query (слова из реплики) и/или cues (список ключей). "
                    "Без query — последние эпизоды по времени."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Подстрока в summary/raw_text"},
                        "cues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ключи context_keys (как в recall_by_cues)",
                        },
                        "limit": {"type": "integer", "description": "Макс. записей (1–80)"},
                        "min_salience": {"type": "number"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_get_episode",
                "description": "Получить один эпизод episodic по числовому id (полный raw/summary).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "episode_id": {"type": "integer", "description": "id из episodic"},
                    },
                    "required": ["episode_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_list_semantic",
                "description": "Список семантических принципов (knowledge.db), с опциональным фильтром.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Подстрока в тексте принципа"},
                        "limit": {"type": "integer"},
                        "min_confidence": {"type": "number"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_search_journal",
                "description": "Поиск по markdown-дневнику (data/journal/*.md).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                        "mode": {
                            "type": "string",
                            "enum": ["auto", "semantic", "lexical"],
                            "description": "auto: rubert если индекс есть, иначе substring",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_read_journal",
                "description": "Прочитать файл дневника (только имя, напр. 2025-05-20.md).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "memory_search_external",
                "description": (
                    "Векторный поиск по внешней памяти (documents.db + index). "
                    "Требует проиндексированный корпус."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                        "min_score": {"type": "number"},
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def is_memory_tool_name(name: str) -> bool:
    return name.startswith("memory_")


def _cue_tokens(text: str | None) -> list[str]:
    if not text or not str(text).strip():
        return []
    words = re.findall(r"[\wА-Яа-яЁё-]{3,}", str(text).lower())
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= 36:
            break
    return out


def _episode_by_id(episodic: Any, episode_id: int) -> dict[str, Any] | None:
    rows = episodic._conn.execute(  # noqa: SLF001
        "SELECT * FROM episodes WHERE id = ?",
        (episode_id,),
    ).fetchall()
    if not rows:
        return None
    columns = [
        d[1] for d in episodic._conn.execute("PRAGMA table_info(episodes)").fetchall()  # noqa: SLF001
    ]
    return dict(zip(columns, rows[0]))


def _truncate_episode(ep: dict[str, Any]) -> dict[str, Any]:
    out = dict(ep)
    for key in ("raw_text", "summary", "compressed"):
        val = str(out.get(key) or "")
        if len(val) > 1200:
            out[key] = val[:1199] + "…"
    return out


def execute_memory_tool(memory: Any, name: str, args: dict[str, Any]) -> str:
    """Выполнить memory_*; возвращает JSON-строку для роли tool."""
    try:
        if name == "memory_search_episodic":
            payload = _search_episodic(memory, args)
        elif name == "memory_get_episode":
            payload = _get_episode(memory, args)
        elif name == "memory_list_semantic":
            payload = _list_semantic(memory, args)
        elif name == "memory_search_journal":
            payload = _search_journal(memory, args)
        elif name == "memory_read_journal":
            payload = _read_journal(args)
        elif name == "memory_search_external":
            payload = _search_external(memory, args)
        else:
            payload = {"error": f"неизвестный memory tool: {name}"}
        return json.dumps(payload, ensure_ascii=False, indent=0)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _search_episodic(memory: Any, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or _DEFAULT_EPISODIC_LIMIT)
    limit = max(1, min(limit, 80))
    min_salience = float(args.get("min_salience") or 0.0)
    query = str(args.get("query") or "").strip()
    cues_raw = args.get("cues")
    cues: list[str] = []
    if isinstance(cues_raw, list):
        cues = [str(c).strip().lower() for c in cues_raw if str(c).strip()]
    elif query:
        cues = _cue_tokens(query)

    episodic = memory.episodic
    hits: list[dict[str, Any]] = []

    if cues:
        hits = episodic.recall_by_cues(cues, limit=limit)
    elif query:
        q = query.lower()
        pool = episodic.query_all(min_salience=min_salience, max_rows=5000)
        scored: list[tuple[float, dict[str, Any]]] = []
        for ep in pool:
            body = (
                str(ep.get("raw_text") or "")
                + " "
                + str(ep.get("summary") or "")
            ).lower()
            if q in body:
                scored.append((float(ep.get("timestamp") or 0), ep))
        scored.sort(reverse=True)
        hits = [ep for _, ep in scored[:limit]]
    else:
        hits = episodic.query(limit=limit, min_salience=min_salience)

    return {
        "count": len(hits),
        "episodes": [_truncate_episode(ep) for ep in hits],
    }


def _get_episode(memory: Any, args: dict[str, Any]) -> dict[str, Any]:
    eid = int(args.get("episode_id") or 0)
    if eid <= 0:
        return {"error": "episode_id required"}
    ep = _episode_by_id(memory.episodic, eid)
    if not ep:
        return {"error": f"episode {eid} not found"}
    for key in ("raw_text", "summary"):
        val = str(ep.get(key) or "")
        if len(val) > _MAX_EPISODE_BODY:
            ep[key] = val[: _MAX_EPISODE_BODY - 1] + "…"
    return {"episode": ep}


def _list_semantic(memory: Any, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or _DEFAULT_SEMANTIC_LIMIT)
    limit = max(1, min(limit, 100))
    min_conf = float(args.get("min_confidence") or 0.0)
    query = str(args.get("query") or "").strip().lower()
    rows = memory.semantic.get_principles(min_confidence=min_conf)
    if query:
        rows = [
            r
            for r in rows
            if query in str(r.get("principle") or "").lower()
        ]
    rows = rows[:limit]
    return {"count": len(rows), "principles": rows}


def _search_journal(_memory: Any, args: dict[str, Any]) -> dict[str, Any]:
    from kernel.journal import Journal

    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query required"}
    top_k = int(args.get("top_k") or _DEFAULT_JOURNAL_TOP_K)
    top_k = max(1, min(top_k, 30))
    mode = str(args.get("mode") or "auto").strip().lower()
    j = Journal(memory=None)
    if mode == "lexical":
        hits = j.search_substring(query)
    elif mode == "semantic":
        hits = j.search_semantic(query, top_k=top_k, fallback=True)
    else:
        hits = j.search_semantic(query, top_k=top_k, fallback=True)
    return {"count": len(hits), "hits": hits[:top_k]}


def _read_journal(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("filename") or "").strip().replace("\\", "/")
    if not name or ".." in name or "/" in name.strip("/"):
        return {"error": "filename must be a bare .md name, e.g. 2025-05-20.md"}
    if not name.endswith(".md"):
        name = f"{name}.md"
    path = (JOURNAL_DIR / name).resolve()
    if not path.is_file() or path.parent != JOURNAL_DIR.resolve():
        return {"error": f"not found: {name}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    max_chars = int(args.get("max_chars") or _MAX_JOURNAL_FILE)
    max_chars = max(1000, min(max_chars, 200_000))
    truncated = len(text) > max_chars
    if truncated:
        text = text[: max_chars - 1] + "…"
    return {"filename": name, "chars": len(text), "truncated": truncated, "content": text}


def _search_external(memory: Any, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "query required"}
    top_k = int(args.get("top_k") or _DEFAULT_EXTERNAL_TOP_K)
    top_k = max(1, min(top_k, 20))
    min_score = float(args.get("min_score") or 0.12)
    try:
        hits = memory.external.search(query, top_k=top_k, min_score=min_score)
    except Exception as exc:
        return {"error": f"external search failed: {exc}", "hits": []}
    return {"count": len(hits), "hits": hits}


def format_memory_help() -> str:
    """Текст для slash ``/memory``."""
    pipe = os.environ.get("EIDOS_CHAT_MEMORY_PIPELINE", "full").strip() or "full"
    active = os.environ.get("EIDOS_CHAT_ACTIVE_MEMORY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    tools_on = memory_tools_enabled()
    lines = [
        "Память Эйдос — два контура",
        "",
        "1) Пассивно (каждый ход): блок «Активное извлечение» в system.",
        f"   pipeline={pipe}, active_memory={'on' if active else 'off'}",
        "   Env: EIDOS_CHAT_MEMORY_PIPELINE, EIDOS_CHAT_ACTIVE_MEMORY_CHARS, …",
        "",
        "2) По запросу (tools):",
        f"   memory tools={'on' if tools_on else 'off'} (EIDOS_MEMORY_TOOLS)",
    ]
    if tools_on:
        for spec in memory_tool_specs():
            fn = spec.get("function") or {}
            lines.append(f"   · {fn.get('name', '?')}")
    else:
        lines.append("   (выключено: EIDOS_MEMORY_TOOLS=0)")
    lines.append("")
    lines.append("Документация: docs/MEMORY_AGENT_ACCESS.md")
    return "\n".join(lines)
