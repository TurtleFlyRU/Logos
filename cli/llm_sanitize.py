"""Санитизация сырого текста от локальных моделей (Gemma thinking, псевдо-tool_call).

Некоторые OpenAI-совместимые прокси отдают в ``message.content`` внутренние каналы
(``<|channel>thought``) и вызовы инструментов текстом (``<|tool_call>call:…``),
без поля ``tool_calls``. CLI приводит это к ожидаемому формату chat API.

Отключить: ``EIDOS_STRIP_MODEL_THOUGHT=0`` (по умолчанию включено).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

_THOUGHT_OPEN = re.compile(r"<\|channel>thought\b", re.IGNORECASE)
_CHANNEL_OR_TOOL = re.compile(
    r"<\|(?:channel>(?:final|comment|response)|tool_call>|think\|>)",
    re.IGNORECASE,
)
_CHANNEL_FINAL_PREFIX = re.compile(
    r"<\|channel>(?:final|comment|response)\s*",
    re.IGNORECASE,
)
_JUNK_TOKENS = (
    re.compile(r"<\|\"\|>", re.IGNORECASE),
    re.compile(r"<\|think\|>", re.IGNORECASE),
    re.compile(r"<\|end\|>", re.IGNORECASE),
)
_TOOL_CALL_MARKER = "<|tool_call>call:"


def strip_model_thought_enabled() -> bool:
    v = os.environ.get("EIDOS_STRIP_MODEL_THOUGHT", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def strip_model_channels(text: str) -> str:
    """Убрать блоки ``<|channel>thought`` и служебные токены; оставить видимый ответ."""
    out = text
    while True:
        m = _THOUGHT_OPEN.search(out)
        if not m:
            break
        start = m.start()
        tail = out[m.end() :]
        end_m = _CHANNEL_OR_TOOL.search(tail)
        if end_m:
            out = out[:start] + tail[end_m.start() :]
        else:
            out = out[:start]
            break
    out = _CHANNEL_FINAL_PREFIX.sub("", out)
    inline = _iter_gemma_inline_tool_calls(out)
    out = _remove_inline_tool_call_spans(out, inline)
    for pat in _JUNK_TOKENS:
        out = pat.sub("", out)
    return out.strip()


def _parse_pseudo_tool_args(raw: str) -> dict[str, Any]:
    """Разбор ``max_chars:1,selector:…`` из Gemma-текста в dict для JSON arguments."""
    s = raw.replace('<|"|>', '"').strip()
    out: dict[str, Any] = {}
    m_chars = re.match(r"max_chars\s*:\s*(\d+)", s)
    if m_chars:
        out["max_chars"] = int(m_chars.group(1))
        s = s[m_chars.end() :].lstrip(", ")
    m_sel = re.search(r"selector\s*:\s*(.+)\s*$", s, re.DOTALL)
    if m_sel:
        val = m_sel.group(1).strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        out["selector"] = val
        return out
    m_url = re.search(r"url\s*:\s*(.+)\s*$", s, re.DOTALL)
    if m_url:
        val = m_url.group(1).strip().strip('"')
        out["url"] = val
        return out
    if s.startswith("{"):
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    for part in re.split(r",(?=\w+\s*:)", s):
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "max_chars":
            try:
                out[key] = int(val)
            except ValueError:
                out[key] = val
        elif val:
            out[key] = val
    return out


def _iter_gemma_inline_tool_calls(text: str) -> list[tuple[str, str, int, int]]:
    """Найти ``<|tool_call>call:name{args}<tool_call|>`` с балансом фигурных скобок."""
    found: list[tuple[str, str, int, int]] = []
    pos = 0
    while True:
        idx = text.find(_TOOL_CALL_MARKER, pos)
        if idx < 0:
            break
        name_start = idx + len(_TOOL_CALL_MARKER)
        brace = text.find("{", name_start)
        if brace < 0:
            break
        name = text[name_start:brace].strip()
        depth = 0
        j = brace
        end_brace = -1
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_brace = j
                    break
            j += 1
        if end_brace < 0:
            break
        args_raw = text[brace + 1 : end_brace]
        close_m = re.match(
            r"\s*(?:<tool_call\|>|<\|tool_call\|>)",
            text[end_brace + 1 :],
            re.IGNORECASE,
        )
        if not close_m:
            pos = end_brace + 1
            continue
        span_end = end_brace + 1 + close_m.end()
        found.append((name, args_raw, idx, span_end))
        pos = span_end
    return found


def _to_openai_tool_calls(
    inline: list[tuple[str, str, int, int]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, args_raw, _start, _end in inline:
        args = _parse_pseudo_tool_args(args_raw)
        out.append(
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        )
    return out


def _remove_inline_tool_call_spans(text: str, spans: list[tuple[str, str, int, int]]) -> str:
    if not spans:
        return text
    parts: list[str] = []
    last = 0
    for _n, _a, start, end in spans:
        parts.append(text[last:start])
        last = end
    parts.append(text[last:])
    return "".join(parts)


def sanitize_assistant_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Очистить content и извлечь inline tool_calls, если есть."""
    inline = _iter_gemma_inline_tool_calls(text)
    body = _remove_inline_tool_call_spans(text, inline)
    body = strip_model_channels(body)
    tool_calls = _to_openai_tool_calls(inline)
    return body, tool_calls


def normalize_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Привести assistant ``message`` к формату OpenAI chat (content / tool_calls)."""
    if not strip_model_thought_enabled():
        return msg
    if msg.get("tool_calls"):
        content = msg.get("content")
        if isinstance(content, str) and (
            "<|channel" in content or "<|tool_call>" in content
        ):
            cleaned, _extra = sanitize_assistant_text(content)
            out = dict(msg)
            out["content"] = cleaned if cleaned else None
            return out
        return msg

    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        return msg
    if "<|channel" not in content and "<|tool_call>" not in content and "<|think" not in content:
        return msg

    cleaned, parsed = sanitize_assistant_text(content)
    out = dict(msg)
    if parsed:
        out["tool_calls"] = parsed
        out["content"] = cleaned if cleaned else None
    else:
        out["content"] = cleaned
    return out


def sanitize_assistant_content_for_history(text: str) -> str:
    """Только текст для истории WM (без подъёма tool_calls из старых событий)."""
    if not strip_model_thought_enabled():
        return text
    if "<|channel" not in text and "<|tool_call>" not in text and "<|think" not in text:
        return text
    cleaned, _ = sanitize_assistant_text(text)
    return cleaned
