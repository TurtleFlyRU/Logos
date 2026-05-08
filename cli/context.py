"""Пайплайны сборки контекста для CLI (фаза 5 — единая сборка для chat).

Переменные окружения (все опционально):

Общие
- ``EIDOS_CHAT_WM_MESSAGES`` — хвост WM в API (4–80, по умолчанию 40).
- ``EIDOS_CHAT_MEMORY_PIPELINE`` — режим активного доступа к памяти перед ответом:
  ``full`` (по умолчанию) — эпизодическая **полная выборка** + семантика по всем принципам +
  дневник (семантика ruBERT при наличии индекса) + ExternalMemory (вектора); ``lexical`` —
  то же без векторов External и без семантики по дневнику (только substring по файлам);
  ``episodic_only`` — только эпизодическая память.
- ``EIDOS_CHAT_ACTIVE_MEMORY`` — ``0``: выключить весь блок активной памяти (по умолчанию вкл.).
- ``EIDOS_CHAT_ACTIVE_MEMORY_CHARS`` — суммарный бюджет символов активного блока (1500–50000).
- ``EIDOS_CHAT_EPISODIC_SCAN_CAP`` — необязательный верхний LIMIT строк episodic при скане
  (для отладки; ``0`` или пусто = без лимита, вся таблица).

Эпизодическая подстройка (внутри активного блока)
- ``EIDOS_CHAT_ACTIVE_RECENT`` — сколько самых свежих эпизодов всегда включать (по умолчанию 6).
- ``EIDOS_CHAT_ACTIVE_KEYWORD_TOP`` — дополнительно топ совпадений по словам реплики (по умолчанию 12).

WM / boot / принципы (статичный блок в system)
- ``EIDOS_CHAT_ATTENTION``, ``EIDOS_CHAT_BOOT_SNIPPET``, ``EIDOS_CHAT_BOOT_SNIPPET_CHARS``,
  ``EIDOS_CHAT_PRINCIPLES``.

Эпизодическая память обрабатывается **лексическим скорингом по всей выборке** (полный скан базы,
если нет ``EPISODIC_SCAN_CAP``). Дневник и External при пайплайне ``full`` — через локальные
эмбеддинги по **всему проиндексированному корпусу** (если индекс есть и модель грузится).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

CLI_CHAT_PERSONA = (
    "Ты Эйдос — со-исследователь; отвечай от первого лица («я»), не называй себя «ты Эйдос». "
    "Если в system ниже есть выгрузка из памяти (эпизоды, принципы, дневник, внешние документы — "
    "по выбранному пайплайну), опирайся на неё для фактов; если факта нет там и в текущем диалоге — "
    "честно скажи, что не знаешь, не выдумывай. "
    "Если нужно проверить цикл инструментов — доступны функции eidos_echo и "
    "read_workspace_file (только файлы внутри репозитория)."
)

_DEFAULT_WM_MESSAGES = 40
_DEFAULT_BOOT_SNIPPET_CHARS = 12000
_DEFAULT_PRINCIPLES_LIMIT = 5
_DEFAULT_PRINCIPLES_MIN_CONF = 0.7
_DEFAULT_ACTIVE_MEMORY_CHARS = 12000
_DEFAULT_ACTIVE_RECENT = 6
_DEFAULT_ACTIVE_KEYWORD_TOP = 12


def _env_flag(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw not in ("0", "false", "no", "off")


def _wm_message_budget() -> int:
    raw = os.environ.get("EIDOS_CHAT_WM_MESSAGES", "").strip()
    if not raw:
        return _DEFAULT_WM_MESSAGES
    try:
        return max(4, min(80, int(raw)))
    except ValueError:
        return _DEFAULT_WM_MESSAGES


def _boot_snippet_char_cap() -> int:
    raw = os.environ.get("EIDOS_CHAT_BOOT_SNIPPET_CHARS", "").strip()
    if raw:
        try:
            return max(800, min(120_000, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_BOOT_SNIPPET_CHARS


def _active_memory_budget_chars() -> int:
    raw = os.environ.get("EIDOS_CHAT_ACTIVE_MEMORY_CHARS", "").strip()
    if raw:
        try:
            return max(1500, min(50_000, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_ACTIVE_MEMORY_CHARS


def _episodic_scan_cap() -> int | None:
    raw = os.environ.get("EIDOS_CHAT_EPISODIC_SCAN_CAP", "").strip()
    if raw == "":
        return None
    try:
        v = int(raw)
        if v <= 0:
            return None
        return min(v, 2_000_000)
    except ValueError:
        return None


def _active_recent_n() -> int:
    raw = os.environ.get("EIDOS_CHAT_ACTIVE_RECENT", "").strip()
    if raw:
        try:
            return max(1, min(40, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_ACTIVE_RECENT


def _active_keyword_top() -> int:
    raw = os.environ.get("EIDOS_CHAT_ACTIVE_KEYWORD_TOP", "").strip()
    if raw:
        try:
            return max(0, min(40, int(raw)))
        except ValueError:
            pass
    return _DEFAULT_ACTIVE_KEYWORD_TOP


def _pipeline_modes() -> dict[str, Any]:
    name = os.environ.get("EIDOS_CHAT_MEMORY_PIPELINE", "full").strip().lower()
    base_full = {
        "name": "full",
        "episodic": True,
        "semantic_lexical": True,
        "journal_semantic": True,
        "journal_lexical": False,
        "external_semantic": True,
    }
    if name in ("", "full", "all"):
        return dict(base_full)
    if name == "lexical":
        return {
            "name": "lexical",
            "episodic": True,
            "semantic_lexical": True,
            "journal_semantic": False,
            "journal_lexical": True,
            "external_semantic": False,
        }
    if name == "episodic_only":
        return {
            "name": "episodic_only",
            "episodic": True,
            "semantic_lexical": False,
            "journal_semantic": False,
            "journal_lexical": False,
            "external_semantic": False,
        }
    return dict(base_full)


def _cue_tokens_from_user(text: str | None) -> list[str]:
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


def _lex_score_blob(blob: str, cues: list[str]) -> float:
    if not cues:
        return 0.0
    b = blob.lower()
    return float(sum(b.count(c) for c in cues))


def _score_episode_for_cues(ep: dict[str, Any], cues: list[str], *, now: float) -> float:
    blob = (
        (str(ep.get("summary") or "") + "\n" + str(ep.get("raw_text") or "")).lower()[:20000]
    )
    hits = _lex_score_blob(blob, cues)
    salience = float(ep.get("salience") or 0)
    ts = float(ep.get("timestamp") or 0)
    age = max(0.0, now - ts)
    recency = 1.0 / (1.0 + age / 86400.0)
    return hits * 18.0 + salience * 0.55 + recency * 3.0


def _score_principle_row(row: dict[str, Any], cues: list[str]) -> float:
    text = str(row.get("principle") or "")
    hits = _lex_score_blob(text, cues)
    conf = float(row.get("confidence") or 0)
    return hits * 14.0 + conf * 2.0


def _append_lines_budget(lines_out: list[str], budget_remaining: list[int], new_lines: list[str]) -> None:
    """mutates lines_out and budget_remaining[0] — символы UTF-8 длиной как len(str)."""
    rem = budget_remaining[0]
    for line in new_lines:
        if rem <= 0:
            break
        chunk = line if len(line) <= rem else line[:rem]
        if chunk:
            lines_out.append(chunk)
            rem -= len(chunk)
        if len(line) > len(chunk):
            break
    budget_remaining[0] = rem


def _episodic_pool(memory: Any) -> list[dict[str, Any]]:
    cap = _episodic_scan_cap()
    try:
        ep = memory.episodic
        if hasattr(ep, "query_all"):
            return ep.query_all(min_salience=0.0, max_rows=cap)
    except Exception:
        return []
    try:
        limit = cap if cap is not None else 2_000_000
        return memory.episodic.query(limit=limit, min_salience=0.0)
    except Exception:
        return []


def format_active_memory_retrieval_block(
    memory: Any,
    user_message: str | None,
    *,
    max_chars: int | None = None,
) -> str:
    """На каждый ход: полный скан episodic (см. cap) + по пайплайну семантика/дневник/external."""
    budget_total = max_chars if max_chars is not None else _active_memory_budget_chars()
    if budget_total <= 0:
        return ""

    pm = _pipeline_modes()
    cues = _cue_tokens_from_user(user_message)
    now = time.time()
    recent_n = _active_recent_n()
    kw_top = _active_keyword_top()

    budget_remaining = [budget_total]
    lines_out: list[str] = []

    def emit_raw(prefix_lines: list[str]) -> None:
        _append_lines_budget(lines_out, budget_remaining, prefix_lines)

    header = (
        "— Активное извлечение из памяти (pipeline="
        f"{pm['name']}; эпизодический скан "
        + ("без искусственного LIMIT «последние N»" if _episodic_scan_cap() is None else f"cap={_episodic_scan_cap()}")
        + "):\n"
    )
    emit_raw([header])
    if budget_remaining[0] <= 0:
        return "".join(lines_out)

    # ─── Эпизодическая ───────────────────────────────────────────────
    if pm["episodic"]:
        pool = _episodic_pool(memory)
        if pool:
            by_ts = sorted(pool, key=lambda e: float(e.get("timestamp") or 0), reverse=True)
            recent = by_ts[:recent_n]

            keyword_eps: list[dict[str, Any]] = []
            if cues and kw_top > 0:
                scored = [
                    (_score_episode_for_cues(ep, cues, now=now), ep) for ep in pool
                ]
                scored.sort(
                    key=lambda x: (-x[0], -float(x[1].get("timestamp") or 0))
                )
                keyword_eps = [
                    ep
                    for sc, ep in scored[:kw_top]
                    if _score_episode_for_cues(ep, cues, now=now) > 0
                ]

            merged: list[dict[str, Any]] = []
            seen_ids: set[Any] = set()
            for ep in [*recent, *keyword_eps]:
                eid = ep.get("id")
                key = eid if eid is not None else id(ep)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                merged.append(ep)

            emit_raw([f"  · Эпизодическая память ({len(pool)} записей в выборке; в блок — до лимита):\n"])
            for ep in merged:
                ts = float(ep.get("timestamp") or 0)
                date_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
                eid = ep.get("id", "?")
                raw_t = str(ep.get("raw_text") or "").strip()
                summ = str(ep.get("summary") or "").strip()
                body = raw_t if raw_t else summ
                body = body.replace("\n", " ").strip()
                if len(body) > 520:
                    body = body[:519] + "…"
                line = f"    [{date_str}] id={eid} | {body}\n"
                emit_raw([line])
                if budget_remaining[0] <= 0:
                    emit_raw([f"    … (обрезано по бюджету {budget_total} символов)\n"])
                    break
        else:
            emit_raw(["  · Эпизодическая память: пусто или недоступна.\n"])

    if budget_remaining[0] <= 0:
        return "".join(lines_out).rstrip() + "\n"

    # ─── Семантика (все принципы → лексический ранг) ──────────────────
    if pm["semantic_lexical"]:
        try:
            rows = memory.semantic.get_principles(min_confidence=0.0)
        except Exception:
            rows = []
        if rows:
            ranked = sorted(
                rows,
                key=lambda r: (-_score_principle_row(r, cues), -float(r.get("confidence") or 0)),
            )
            take = ranked[: max(8, kw_top + 4)] if cues else ranked[:8]
            emit_raw(["  · Семантическая память (принципы, скоринг по реплике):\n"])
            for row in take:
                p = str(row.get("principle") or "").strip().replace("\n", " ")
                if len(p) > 420:
                    p = p[:419] + "…"
                cf = float(row.get("confidence") or 0)
                pid = row.get("id", "?")
                emit_raw([f"    id={pid} [{cf:.2f}] {p}\n"])
                if budget_remaining[0] <= 0:
                    break

    if budget_remaining[0] <= 0:
        return "".join(lines_out).rstrip() + "\n"

    # ─── Дневник ─────────────────────────────────────────────────────
    um = (user_message or "").strip()
    q = um if um else " "
    if pm["journal_semantic"]:
        try:
            from kernel.journal import Journal

            hits = Journal(memory=None).search_semantic(q, top_k=10, fallback=True)
        except Exception:
            hits = []
        if hits:
            emit_raw(["  · Дневник (семантический/строчный поиск по файлам):\n"])
            for h in hits:
                snippet = str(h.get("snippet") or h.get("section") or "")[:300]
                fn = h.get("file", "?")
                emit_raw([f"    [{fn}] {snippet}\n"])
                if budget_remaining[0] <= 0:
                    break
    elif pm["journal_lexical"]:
        try:
            from kernel.journal import Journal

            hits = Journal(memory=None).search_substring(q)
        except Exception:
            hits = []
        if hits:
            emit_raw(["  · Дневник (лексический поиск по строкам):\n"])
            for h in hits[:12]:
                snippet = str(h.get("snippet") or "")[:300]
                fn = h.get("file", "?")
                sec = h.get("section", "")
                emit_raw([f"    [{fn} — {sec}] {snippet}\n"])
                if budget_remaining[0] <= 0:
                    break

    if budget_remaining[0] <= 0:
        return "".join(lines_out).rstrip() + "\n"

    # ─── Внешняя память (вектор по всему индексу) ────────────────────
    if pm["external_semantic"] and um:
        try:
            hits = memory.external.search(um, top_k=8, min_score=0.12)
        except Exception:
            hits = []
        if hits:
            emit_raw(["  · Внешняя память (векторный поиск по всем документам):\n"])
            for h in hits:
                title = str(h.get("title") or h.get("source") or "")
                sn = str(h.get("snippet") or "")[:360]
                emit_raw([f"    [{title}] {sn}\n"])
                if budget_remaining[0] <= 0:
                    break

    return "".join(lines_out).rstrip() + "\n"


def wm_events_to_chat_messages(
    events: list[dict[str, Any]],
    cli_session_id: str,
    *,
    max_messages: int = 40,
) -> list[dict[str, Any]]:
    """События WM с данным cli_session_id → сообщения для chat/completions."""
    out: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("cli_session_id") != cli_session_id:
            continue
        role = ev.get("role")
        if role == "tool":
            tid = ev.get("tool_call_id")
            if not tid:
                continue
            content = ev.get("content") or ""
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tid),
                    "content": str(content),
                }
            )
            continue
        if role == "assistant":
            tc = ev.get("tool_calls")
            if tc:
                msg_a: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": tc,
                    "content": ev["content"] if "content" in ev else None,
                }
                out.append(msg_a)
                continue
            content_a = ev.get("content") or ev.get("message") or ""
            text_a = str(content_a).strip()
            if not text_a:
                continue
            out.append({"role": "assistant", "content": text_a})
            continue
        if role == "user":
            content = ev.get("content") or ev.get("message") or ""
            text = str(content).strip()
            if not text:
                continue
            out.append({"role": "user", "content": text})
            continue
    return out[-max_messages:]


def format_attention_slots_block(memory: Any) -> str:
    slots = (memory.working.data.get("attention_slots") or [])[-4:]
    if not slots:
        return ""
    lines = ["— Слоты внимания (WM):"]
    for slot in slots:
        summary = str(slot.get("summary", ""))[:200]
        role = slot.get("role", "event")
        lines.append(f"  • [{role}] {summary}")
    return "\n".join(lines) + "\n"


def format_boot_context_snippet(
    memory: Any,
    *,
    max_chars: int = _DEFAULT_BOOT_SNIPPET_CHARS,
) -> str:
    ctx = memory.working.data.get("context") or {}
    boot = ctx.get("boot_context")
    if not boot or not isinstance(boot, str):
        return ""
    text = boot.strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return (
        "— Фрагмент сохранённого boot-контекста (из WM, без повторного boot):\n"
        + text
        + "\n\n"
    )


def format_semantic_principles_block(
    memory: Any,
    *,
    limit: int = _DEFAULT_PRINCIPLES_LIMIT,
    min_confidence: float = _DEFAULT_PRINCIPLES_MIN_CONF,
) -> str:
    rows = memory.semantic.get_principles(min_confidence=min_confidence)[:limit]
    if not rows:
        return ""
    lines = ["— Принципы (семантическая память):"]
    for row in rows:
        p = str(row.get("principle", "")).strip()
        if not p:
            continue
        conf = float(row.get("confidence") or 0)
        lines.append(f"  • [{conf:.2f}] {p[:400]}")
    return "\n".join(lines) + "\n"


def build_chat_context(
    memory: Any,
    cli_session_id: str,
    *,
    user_message: str | None = None,
) -> str:
    """Текстовые блоки для дополнения system-сообщения (не включает персону).

    ``cli_session_id`` зарезервирован под фильтрацию episodic по сессии (позже).
    ``user_message`` — триггер активного извлечения по всей памяти (см. pipeline).
    """
    del cli_session_id

    parts: list[str] = []
    if _env_flag("EIDOS_CHAT_ATTENTION", default=True):
        parts.append(format_attention_slots_block(memory))
    if _env_flag("EIDOS_CHAT_ACTIVE_MEMORY", default=True):
        parts.append(
            format_active_memory_retrieval_block(
                memory,
                user_message,
                max_chars=_active_memory_budget_chars(),
            )
        )
    if _env_flag("EIDOS_CHAT_BOOT_SNIPPET", default=True):
        parts.append(
            format_boot_context_snippet(memory, max_chars=_boot_snippet_char_cap())
        )
    if _env_flag("EIDOS_CHAT_PRINCIPLES", default=True):
        parts.append(
            format_semantic_principles_block(
                memory,
                limit=_DEFAULT_PRINCIPLES_LIMIT,
                min_confidence=_DEFAULT_PRINCIPLES_MIN_CONF,
            )
        )
    return "\n".join(p for p in parts if p).strip()


def build_chat_messages_for_llm(
    memory: Any,
    cli_session_id: str,
    *,
    max_wm_messages: int | None = None,
    tools_compatible_history: bool = True,
    user_message: str | None = None,
) -> list[dict[str, Any]]:
    """Полный список сообщений для chat/completions: system (персона + контекст) + хвост WM."""
    from cli.tools import tools_enabled

    max_wm = max_wm_messages if max_wm_messages is not None else _wm_message_budget()
    hist = wm_events_to_chat_messages(
        memory.working.data["events"],
        cli_session_id,
        max_messages=max_wm,
    )
    if tools_compatible_history and not tools_enabled():
        hist = [h for h in hist if h.get("role") in ("user", "assistant")]

    extra = build_chat_context(memory, cli_session_id, user_message=user_message)
    system_content = CLI_CHAT_PERSONA.strip()
    if extra:
        system_content = f"{system_content}\n\n{extra}"

    return [{"role": "system", "content": system_content}, *hist]
