"""Инструменты CLI и выполнение вызовов из ответа модели (фаза 4).

Переменные окружения:
- EIDOS_TOOLS — ``0``/``false``: не передавать ``tools`` в API (по умолчанию включено).
- EIDOS_TOOL_ROUNDS — максимум циклов «ответ → tool_calls → повтор» (1–32, по умолчанию 8).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from kernel.config import REPO_ROOT
from kernel.instrumental import InstrumentalRegistry


MAX_READ_FILE_BYTES = 65536


def tools_enabled() -> bool:
    v = os.environ.get("EIDOS_TOOLS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def max_tool_rounds() -> int:
    raw = os.environ.get("EIDOS_TOOL_ROUNDS", "8").strip()
    try:
        return max(1, min(32, int(raw)))
    except ValueError:
        return 8


def progress_echo_enabled() -> bool:
    v = os.environ.get("LLM_PROGRESS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def builtin_tool_specs() -> list[dict[str, Any]]:
    """Схемы инструментов в формате OpenAI-compatible chat/completions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "eidos_echo",
                "description": "Вернуть переданный текст без изменений (отладка и проверка цикла).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Строка для возврата"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_workspace_file",
                "description": (
                    "Прочитать текстовый файл внутри корня репозитория Logos "
                    "(относительный путь, без выхода из каталога)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Путь относительно корня репозитория, например README.md",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
    ]


def assistant_message_for_api(msg: dict[str, Any]) -> dict[str, Any]:
    """Урезать поля assistant-сообщения до того, что ожидает chat/completions."""
    out: dict[str, Any] = {"role": "assistant"}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
        out["content"] = msg["content"] if "content" in msg else None
        return out
    if "content" in msg:
        out["content"] = msg["content"]
    return out


def _resolve_under_repo(rel: str) -> Path:
    rel = rel.strip().replace("\\", "/").lstrip("/")
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError("path must not contain '..'")
    root = REPO_ROOT.resolve()
    target = (root / rel).resolve()
    target.relative_to(root)
    return target


def execute_tool(
    name: str,
    arguments_json: str,
    *,
    registry: InstrumentalRegistry | None,
) -> str:
    """Выполнить один инструмент; результат — строка для роли ``tool``."""
    tid: int | None = None
    if registry is not None:
        tid = registry.add_tool("eidos_cli", name, tags=["cli", "eidos"])

    try:
        args: dict[str, Any]
        try:
            raw = json.loads(arguments_json or "{}")
            args = raw if isinstance(raw, dict) else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"Неверный JSON аргументов: {exc}") from exc

        if name == "eidos_echo":
            text = str(args.get("text", ""))
            out = text
        elif name == "read_workspace_file":
            rel_path = str(args.get("path", "")).strip()
            if not rel_path:
                raise ValueError("path required")
            path = _resolve_under_repo(rel_path)
            if not path.is_file():
                raise FileNotFoundError(f"Не файл: {rel_path}")
            data = path.read_bytes()
            if len(data) > MAX_READ_FILE_BYTES:
                raise ValueError(
                    f"Файл больше {MAX_READ_FILE_BYTES} байт ({len(data)}); "
                    "укажите меньший файл."
                )
            out = data.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Неизвестный инструмент: {name}")

        if tid is not None and tid > 0 and registry is not None:
            registry.record_success(tid)
        return out
    except Exception as exc:
        if tid is not None and tid > 0 and registry is not None:
            registry.record_failure(tid, error=str(exc))
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
