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

- ``EIDOS_CHAT_USER_IDENTITY`` — ``0``: не добавлять строку с именем из WM ``context['user_display_name']``
  (по умолчанию вкл.; имя выставляется из фраз «меня зовут …» и т.п.).

- ``EIDOS_CHAT_TOOLS_ON_IDENTITY`` — ``1``: разрешить tool_calls даже на короткие вопросы «кто я» и т.п.
  (по умолчанию для таких реплик инструменты **не** передаются в API — только текст из памяти в system).

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
from pathlib import Path
from typing import Any

_DEFAULT_PERSONA_FALLBACK = (
    "Я Эйдос — исследователь; отвечай от первого лица («я»). "
    "Факты о пользователе и прошлые события смотри в этом же system: "
    "слоты внимания, активное извлечение из памяти, хвост чата. "
    "На короткие вопросы «кто я» отвечай по памяти, без инструментов."
)


def load_project_agents_md() -> str:
    """Базовый system-текст для CLI: читаем корневой AGENTS.md.

    Это сознательно: persona живёт в проекте, а не в захардкоженной строке.
    """
    override = os.environ.get("EIDOS_CHAT_PERSONA_PATH", "").strip()
    if override:
        try:
            text = Path(override).expanduser().resolve().read_text(encoding="utf-8").strip()
            return text if text else _DEFAULT_PERSONA_FALLBACK
        except OSError:
            return _DEFAULT_PERSONA_FALLBACK
    repo_root = Path(__file__).resolve().parents[1]
    p = repo_root / "AGENTS.md"
    try:
        text = p.read_text(encoding="utf-8").strip()
        return text if text else _DEFAULT_PERSONA_FALLBACK
    except OSError:
        return _DEFAULT_PERSONA_FALLBACK

_DEFAULT_WM_MESSAGES = 40
_DEFAULT_BOOT_SNIPPET_CHARS = 12000
_DEFAULT_PRINCIPLES_LIMIT = 5
_DEFAULT_PRINCIPLES_MIN_CONF = 0.7
_DEFAULT_ACTIVE_MEMORY_CHARS = 12000
_DEFAULT_ACTIVE_RECENT = 6
_DEFAULT_ACTIVE_KEYWORD_TOP = 12
_DEFAULT_TOTAL_CHAT_CHARS = 0  # 0/пусто — выключено (сохраняем поведение v1)
_DEFAULT_SUMMARY_CHARS = 6000
_DEFAULT_KEEP_LAST_MESSAGES = 16
_DEFAULT_LAYER_BUDGET = True


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


def _total_chat_char_budget() -> int:
    """Максимальный размер всех сообщений для LLM в символах.

    В фазе 8 бюджет вводится как простой и предсказуемый лимит:
    сначала урезаем историю WM (удаляем самые старые сообщения),
    затем в крайнем случае режем system (после сборки всех блоков).
    """
    raw = os.environ.get("EIDOS_CHAT_TOTAL_CHARS", "").strip()
    if raw == "":
        return _DEFAULT_TOTAL_CHAT_CHARS
    try:
        return max(0, min(1_000_000, int(raw)))
    except ValueError:
        return _DEFAULT_TOTAL_CHAT_CHARS


def _summarize_old_wm_enabled() -> bool:
    """Включить сжатие старой части истории WM в один system-блок."""
    return _env_flag("EIDOS_CHAT_SUMMARIZE_OLD_WM", default=False)


def _summary_char_budget() -> int:
    raw = os.environ.get("EIDOS_CHAT_SUMMARY_CHARS", "").strip()
    if raw == "":
        return _DEFAULT_SUMMARY_CHARS
    try:
        return max(800, min(120_000, int(raw)))
    except ValueError:
        return _DEFAULT_SUMMARY_CHARS


def _keep_last_messages() -> int:
    raw = os.environ.get("EIDOS_CHAT_KEEP_LAST_MESSAGES", "").strip()
    if raw == "":
        return _DEFAULT_KEEP_LAST_MESSAGES
    try:
        return max(4, min(120, int(raw)))
    except ValueError:
        return _DEFAULT_KEEP_LAST_MESSAGES


def _layer_budget_enabled(*, total_budget: int) -> bool:
    """Включить «бюджет по слоям» (8.1).

    По умолчанию включается, если задан общий бюджет ``EIDOS_CHAT_TOTAL_CHARS``.
    Можно принудительно выключить через ``EIDOS_CHAT_LAYER_BUDGET=0``.
    """
    return _env_flag("EIDOS_CHAT_LAYER_BUDGET", default=(total_budget > 0 and _DEFAULT_LAYER_BUDGET))


def estimate_messages_chars(messages: list[dict[str, Any]]) -> int:
    """Грубая оценка размера payload: суммарная длина content."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
    return total


def chat_context_metrics(
    messages: list[dict[str, Any]],
    *,
    total_budget: int,
) -> dict[str, Any]:
    """Метрики сборки контекста для вывода в CLI."""
    total_chars = estimate_messages_chars(messages)
    roles = [str(m.get("role") or "?") for m in messages]
    system_count = sum(1 for r in roles if r == "system")
    history_count = len(messages) - system_count
    history_roles = [r for r in roles if r != "system"]
    tool_count = sum(1 for r in history_roles if r == "tool")

    sys_text = ""
    if messages and isinstance(messages[0].get("content"), str):
        sys_text = str(messages[0]["content"])
    # Важно: persona сама содержит слова вроде «Активное извлечение…», поэтому
    # ищем заголовки реальных блоков, которые добавляются форматтерами ниже.
    has_identity = "\n— Пользователь (CLI" in sys_text
    has_attention = "\n— Слоты внимания (WM):" in sys_text
    has_active_memory = "\n— Активное извлечение из памяти" in sys_text
    has_boot_snippet = "\n— Фрагмент сохранённого boot-контекста" in sys_text
    has_principles = "\n— Принципы:" in sys_text

    has_summary_block = any(
        (m.get("role") == "system")
        and isinstance(m.get("content"), str)
        and "Сжатая история" in str(m.get("content"))
        for m in messages[1:3]
    )

    return {
        "budget_total_chars": int(total_budget),
        "total_chars": int(total_chars),
        "system_messages": int(system_count),
        "history_messages": int(history_count),
        "tool_messages": int(tool_count),
        "layers": {
            "identity": bool(has_identity),
            "attention": bool(has_attention),
            "active_memory": bool(has_active_memory),
            "boot_snippet": bool(has_boot_snippet),
            "principles": bool(has_principles),
            "wm_summary_block": bool(has_summary_block),
        },
    }


def _render_compact_history_summary(
    history: list[dict[str, Any]], *, max_chars: int
) -> str:
    """Сжимает историю в компактный текст (без вызова LLM).

    Идея: не терять полностью раннюю нить — хотя бы зафиксировать последовательность
    user/assistant реплик, урезая каждую до короткого фрагмента.
    """
    lines: list[str] = ["— Сжатая история (ранние реплики):"]
    used = len(lines[0]) + 1
    for m in history:
        role = str(m.get("role", "?"))
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        snippet = content.strip().replace("\n", " ")
        snippet = snippet[:240]
        line = f"  [{role}] {snippet}"
        if used + len(line) + 1 > max_chars:
            lines.append("  … (обрезано по бюджету summary)")
            break
        lines.append(line)
        used += len(line) + 1
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def _truncate_block(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = (text or "").strip()
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    if max_chars < 4:
        return s[:max_chars]
    return s[: max_chars - 1] + "…"


def _build_system_extra_with_budget(
    memory: Any,
    cli_session_id: str,
    *,
    user_message: str | None,
    budget_chars: int,
) -> str:
    """Собирает extra-блоки system с деградацией по слоям (8.1)."""
    rem = budget_chars
    parts: list[str] = []

    def add(block: str) -> None:
        nonlocal rem
        b = block.strip() if isinstance(block, str) else ""
        if not b or rem <= 0:
            return
        b2 = _truncate_block(b, max_chars=rem)
        if b2:
            parts.append(b2)
            rem -= len(b2)

    # Приоритеты: identity -> attention -> active memory -> boot snippet -> principles
    add(format_user_identity_block(memory))
    if _env_flag("EIDOS_CHAT_ATTENTION", default=True):
        add(format_attention_slots_block(memory))

    if _env_flag("EIDOS_CHAT_ACTIVE_MEMORY", default=True) and rem > 0:
        # active memory уже умеет бюджет
        add(
            format_active_memory_retrieval_block(
                memory,
                user_message,
                cli_session_id=cli_session_id,
                max_chars=min(rem, _active_memory_budget_chars()),
            )
        )

    if _env_flag("EIDOS_CHAT_BOOT_SNIPPET", default=True) and rem > 0:
        add(format_boot_context_snippet(memory, max_chars=min(rem, _boot_snippet_char_cap())))

    if _env_flag("EIDOS_CHAT_PRINCIPLES", default=True) and rem > 0:
        add(
            format_semantic_principles_block(
                memory,
                limit=_DEFAULT_PRINCIPLES_LIMIT,
                min_confidence=_DEFAULT_PRINCIPLES_MIN_CONF,
            )
        )

    return "\n\n".join(p for p in parts if p).strip()


def _apply_total_char_budget(
    messages: list[dict[str, Any]], *, total_budget: int
) -> list[dict[str, Any]]:
    if total_budget <= 0:
        return messages

    # 1) режем хвост истории (сохраняем system и последние реплики)
    out = list(messages)
    if _summarize_old_wm_enabled() and len(out) > 1:
        keep_last = _keep_last_messages()
        summary_budget = _summary_char_budget()

        # Сжимаем раннюю историю максимум один раз (детерминированно).
        # Если после этого всё ещё не влезает — продолжаем удалять.
        hist = out[1:]
        if len(hist) > keep_last + 4:
            early = hist[: -keep_last]
            tail = hist[-keep_last:]
            summary_text = _render_compact_history_summary(
                early, max_chars=summary_budget
            )
            out = [out[0], {"role": "system", "content": summary_text}, *tail]

    while len(out) > 1 and estimate_messages_chars(out) > total_budget:
        # out[0] = system, out[1] = самый старый исторический (или summary-блок)
        del out[1]

    # 2) если всё ещё не влезает — урежем system (крайний случай)
    over = estimate_messages_chars(out) - total_budget
    if over > 0 and out and isinstance(out[0].get("content"), str):
        sys_text = str(out[0]["content"])
        keep = max(2000, len(sys_text) - over - 20)
        if keep < len(sys_text):
            out[0] = {
                **out[0],
                "content": sys_text[:keep] + "…",
            }
    return out


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


_IDENTITY_QUESTION_RE = re.compile(
    r"(^|\b)(кто\s+я|как\s+(меня\s+)?зовут|какое\s+у\s+меня\s+имя|мо[ёе]\s+имя|who\s+am\s+i|what\s*\'?s\s+my\s+name)(\b|$)",
    re.I,
)


def _wm_tail_plain_text(memory: Any, cli_session_id: str, *, max_messages: int = 44) -> str:
    """Текст последних реплик этой CLI-сессии для дополнения cues (имя в прошлых сообщениях)."""
    events = memory.working.data.get("events") or []
    parts: list[str] = []
    count = 0
    for ev in reversed(events):
        if ev.get("cli_session_id") != cli_session_id:
            continue
        role = ev.get("role")
        if role not in ("user", "assistant"):
            continue
        raw = ev.get("content") or ev.get("message") or ""
        text = str(raw).strip()
        if text:
            parts.append(text)
        count += 1
        if count >= max_messages:
            break
    parts.reverse()
    return "\n".join(parts)


def _merged_retrieval_cues(user_message: str | None, wm_tail_text: str) -> list[str]:
    """Токены из текущей реплики + из хвоста WM; иначе «кто я» не матчит эпизод с именем."""
    primary = _cue_tokens_from_user(user_message)
    secondary = _cue_tokens_from_user(wm_tail_text)
    seen: set[str] = set()
    out: list[str] = []
    for tok in primary + secondary:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= 56:
            break
    return out


def _episode_identity_hint_score(ep: dict[str, Any]) -> float:
    blob = (str(ep.get("summary") or "") + "\n" + str(ep.get("raw_text") or "")).lower()
    needles = (
        "меня зовут",
        "зовут ",
        "мое имя",
        "моё имя",
        "имя пользователя",
        "my name",
        "[user]",
        " пользователь ",
        "пользователь:",
    )
    return float(sum(blob.count(n) * 3.0 for n in needles))


def _score_identity_probe_episode(ep: dict[str, Any], *, now: float) -> float:
    hint = _episode_identity_hint_score(ep)
    ts = float(ep.get("timestamp") or 0)
    age = max(0.0, now - ts)
    recency = 1.0 / (1.0 + age / 86400.0)
    salience = float(ep.get("salience") or 0)
    return hint * 15.0 + recency * 4.0 + salience * 0.45


def format_user_identity_block(memory: Any) -> str:
    if not _env_flag("EIDOS_CHAT_USER_IDENTITY", default=True):
        return ""
    ctx = memory.working.data.get("context") or {}
    raw = ctx.get("user_display_name")
    if not raw or not isinstance(raw, str):
        return ""
    name = raw.strip()
    if not name:
        return ""
    return f"— Пользователь (CLI, явно указано в диалоге): имя — {name}.\n"


def is_identity_meta_query(line: str, *, max_len: int = 160) -> bool:
    """Короткий запрос про личность пользователя — без инструментов, только память в system."""
    s = (line or "").strip()
    if len(s) > max_len:
        return False
    return bool(_IDENTITY_QUESTION_RE.search(s))


def tools_allowed_for_chat_line(line: str) -> bool:
    """Инструменты для этого ввода: по умолчанию выключаются на короткие identity-вопросы."""
    if _env_flag("EIDOS_CHAT_TOOLS_ON_IDENTITY", default=False):
        return True
    return not is_identity_meta_query(line)


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
    cli_session_id: str = "",
    max_chars: int | None = None,
) -> str:
    """На каждый ход: полный скан episodic (см. cap) + по пайплайну семантика/дневник/external."""
    budget_total = max_chars if max_chars is not None else _active_memory_budget_chars()
    if budget_total <= 0:
        return ""

    pm = _pipeline_modes()
    wm_tail = _wm_tail_plain_text(memory, cli_session_id) if cli_session_id else ""
    cues = _merged_retrieval_cues(user_message, wm_tail)
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

            identity_eps: list[dict[str, Any]] = []
            um_strip = (user_message or "").strip()
            if kw_top > 0 and um_strip and _IDENTITY_QUESTION_RE.search(um_strip):
                i_take = max(12, kw_top)
                scored_i = sorted(
                    pool,
                    key=lambda ep: -_score_identity_probe_episode(ep, now=now),
                )
                identity_eps = [
                    ep
                    for ep in scored_i[:i_take]
                    if _episode_identity_hint_score(ep) > 0
                ]

            merged: list[dict[str, Any]] = []
            seen_ids: set[Any] = set()
            for ep in [*recent, *keyword_eps, *identity_eps]:
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
    if cli_session_id and um and _IDENTITY_QUESTION_RE.search(um):
        tail_bit = wm_tail[-900:] if wm_tail else ""
        q = (um + "\n" + tail_bit).strip()[:2500]

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
    ext_q = um
    if cli_session_id and um and _IDENTITY_QUESTION_RE.search(um):
        ext_q = (um + "\n" + (wm_tail[-600:] if wm_tail else "")).strip()[:2000]
    if pm["external_semantic"] and ext_q:
        try:
            hits = memory.external.search(ext_q, top_k=8, min_score=0.12)
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

    ``cli_session_id`` — фильтр хвоста WM для cues при активном извлечении.
    ``user_message`` — триггер активного извлечения по всей памяти (см. pipeline).
    """

    parts: list[str] = []
    parts.append(format_user_identity_block(memory))
    if _env_flag("EIDOS_CHAT_ATTENTION", default=True):
        parts.append(format_attention_slots_block(memory))
    if _env_flag("EIDOS_CHAT_ACTIVE_MEMORY", default=True):
        parts.append(
            format_active_memory_retrieval_block(
                memory,
                user_message,
                cli_session_id=cli_session_id,
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

    total_budget = _total_chat_char_budget()

    # 8.1: если задан общий бюджет — собираем system-пристройку по слоям заранее,
    # чтобы минимизировать «грубую резку» system в _apply_total_char_budget.
    if _layer_budget_enabled(total_budget=total_budget):
        # резервируем место под историю (приблизительно) и саму persona
        persona = load_project_agents_md().strip()
        hist_chars = estimate_messages_chars(hist)
        # system extra получает всё, что осталось, но не меньше 0
        extra_budget = max(0, total_budget - len(persona) - hist_chars - 50)
        extra = _build_system_extra_with_budget(
            memory,
            cli_session_id,
            user_message=user_message,
            budget_chars=extra_budget,
        )
    else:
        extra = build_chat_context(memory, cli_session_id, user_message=user_message)

    system_content = load_project_agents_md().strip()
    if extra:
        system_content = f"{system_content}\n\n{extra}"

    messages = [{"role": "system", "content": system_content}, *hist]
    return _apply_total_char_budget(messages, total_budget=total_budget)
