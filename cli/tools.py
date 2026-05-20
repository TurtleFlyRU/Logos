"""Инструменты CLI и выполнение вызовов из ответа модели (фаза 4).

Переменные окружения:
- EIDOS_TOOLS — ``0``/``false``: не передавать ``tools`` в API (по умолчанию включено).
- EIDOS_TOOL_ROUNDS — максимум циклов «ответ → tool_calls → повтор» (1–32, по умолчанию 8).
- EIDOS_HTTP_FETCH — по умолчанию **вкл.**; ``0``/``false``: не добавлять ``fetch_https_url`` (GET http/https).
- EIDOS_HTTP_FETCH_TIMEOUT_SEC — таймаут запроса (сек, по умолчанию 15).
- EIDOS_HTTP_FETCH_MAX_BYTES — потолок размера тела (байт, по умолчанию 393216).
- EIDOS_PLAYWRIGHT — по умолчанию **вкл.**; ``0``/``false``: не добавлять Playwright-MVP инструменты.
- EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST — ``1``: разрешить localhost/приватные IP для browser tools.
- EIDOS_PLAYWRIGHT_PROXY_SERVER / USERNAME / PASSWORD / BYPASS — явный прокси для Chromium.
- EIDOS_PLAYWRIGHT_IGNORE_PROXY — ``1``: запустить Chromium с ``--no-proxy-server``.
- LLM_IGNORE_PROXY — как в ``cli.llm``: ``1`` отключает системный прокси для httpx.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from cli.browser_tools import (
    execute_browser_tool,
    playwright_tool_enabled,
    playwright_tool_names,
    playwright_tool_specs,
)
from kernel.config import REPO_ROOT
from kernel.instrumental import InstrumentalRegistry


MAX_READ_FILE_BYTES = 65536
_DEFAULT_FETCH_MAX_BYTES = 384 * 1024
_DEFAULT_FETCH_MAX_CHARS = 24_000
_ALLOWED_BASH_COMMAND = "python3 eidos.py sleep"


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


def http_fetch_tool_enabled() -> bool:
    """По умолчанию включено. Выключение: ``0``, ``false``, ``no``, ``off``."""
    v = os.environ.get("EIDOS_HTTP_FETCH", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _http_trust_env_for_fetch() -> bool:
    v = os.environ.get("LLM_IGNORE_PROXY", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return False
    return True


def _sanitize_fetch_url(url: str) -> str:
    """Разрешить только http(s); отсечь очевидные локальные хосты (SSRF)."""
    raw = url.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("разрешены только схемы http и https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL без хоста")
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        raise ValueError("локальные хосты по умолчанию запрещены")
    ip_like = {"0.0.0.0", "127.0.0.1"}
    short = host.split("%", 1)[0]
    if short in ip_like or short.startswith("127.") or short.startswith("169.254."):
        raise ValueError("адрес недоступен для fetch")
    return parsed.geturl()


def _fetch_https_url_execute(args: dict[str, Any]) -> str:
    if not http_fetch_tool_enabled():
        raise ValueError(
            "fetch_https_url выключен (EIDOS_HTTP_FETCH=0/false/no/off)."
        )

    url = str(args.get("url", "")).strip()
    if not url:
        raise ValueError("параметр url обязателен")

    safe_url = _sanitize_fetch_url(url)
    raw_max_ch = args.get("max_chars")
    try:
        max_chars = int(raw_max_ch) if raw_max_ch is not None else _DEFAULT_FETCH_MAX_CHARS
    except (TypeError, ValueError):
        max_chars = _DEFAULT_FETCH_MAX_CHARS
    max_chars = max(500, min(max_chars, 120_000))

    raw_timeout = os.environ.get("EIDOS_HTTP_FETCH_TIMEOUT_SEC", "").strip()
    try:
        timeout_sec = float(raw_timeout) if raw_timeout else 15.0
    except ValueError:
        timeout_sec = 15.0
    timeout_sec = max(3.0, min(timeout_sec, 120.0))

    raw_max_b = os.environ.get("EIDOS_HTTP_FETCH_MAX_BYTES", "").strip()
    try:
        max_bytes = int(raw_max_b) if raw_max_b else _DEFAULT_FETCH_MAX_BYTES
    except ValueError:
        max_bytes = _DEFAULT_FETCH_MAX_BYTES
    max_bytes = max(4096, min(max_bytes, 2 * 1024 * 1024))

    headers = {
        "User-Agent": (
            os.environ.get("EIDOS_HTTP_FETCH_USER_AGENT", "").strip()
            or "Logos-Eidos-CLI/fetch_https_url (+github.com/TurtleFlyRU/Logos)"
        )
    }
    timeout = httpx.Timeout(timeout_sec, connect=min(30.0, timeout_sec))

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        trust_env=_http_trust_env_for_fetch(),
        http2=False,
    ) as client:
        response = client.get(safe_url, headers=headers)
    response.raise_for_status()

    snippet = response.content[:max_bytes]
    text = snippet.decode("utf-8", errors="replace").strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"

    ctype = response.headers.get("content-type", "")
    lines = (
        f"url: {safe_url}",
        f"status: {response.status_code}",
        f"content-type: {ctype}",
        "---",
        text,
    )
    return "\n".join(lines)


def _normalize_bash_command(command: str) -> str:
    """Сжать пробелы в shell-команде для allowlist-сравнения."""
    return " ".join(str(command).strip().split())


def _bash_execute(args: dict[str, Any]) -> str:
    """Выполнить строго allowlisted shell-команду.

    Сейчас разрешена только каноническая ручная команда запуска sleep-машины.
    """
    raw_command = str(args.get("command", "")).strip()
    if not raw_command:
        raise ValueError("параметр command обязателен")

    command = _normalize_bash_command(raw_command)
    if command != _ALLOWED_BASH_COMMAND:
        raise ValueError(
            "bash tool сейчас разрешает только ручной запуск sleep-машины: "
            f"{_ALLOWED_BASH_COMMAND}"
        )

    proc = subprocess.run(
        ["python3", "eidos.py", "sleep"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = "\n".join(part for part in (stdout, stderr) if part).strip()
        raise RuntimeError(
            f"Команда {_ALLOWED_BASH_COMMAND!r} завершилась с кодом {proc.returncode}"
            + (f":\n{detail}" if detail else "")
        )
    return stdout or "[bash] sleep completed"


def builtin_tool_specs() -> list[dict[str, Any]]:
    """Схемы инструментов в формате OpenAI-compatible chat/completions."""
    specs: list[dict[str, Any]] = [
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
                    "(относительный путь). Не использовать для «кто я» / имени пользователя — "
                    "это не база памяти Эйдоса; см. блок памяти в system."
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
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": (
                    "Выполнить строго одну разрешённую shell-команду для ручного запуска "
                    "sleep-машины Эйдоса. Сейчас разрешено только: python3 eidos.py sleep"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "Ровно одна allowlisted команда. Сейчас только "
                                "`python3 eidos.py sleep`."
                            ),
                        },
                    },
                    "required": ["command"],
                },
            },
        },
    ]
    if http_fetch_tool_enabled():
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": "fetch_https_url",
                    "description": (
                        "Выполнить HTTP GET по публичному URL (http или https). По умолчанию доступно; "
                        "выключить: EIDOS_HTTP_FETCH=0. Нельзя использовать для файлов из "
                        "репозитория — для этого read_workspace_file. Локальные и link-local адреса "
                        "отклоняются. Ответ — усечённое тело как текст UTF-8 (best-effort)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Полный URL, например https://example.org/path",
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": (
                                    f"Максимум символов в ответе (по умолчанию {_DEFAULT_FETCH_MAX_CHARS})"
                                ),
                            },
                        },
                        "required": ["url"],
                    },
                },
            }
        )
    if playwright_tool_enabled():
        specs.extend(playwright_tool_specs())
    return specs


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

        if name in playwright_tool_names():
            out = execute_browser_tool(name, args)
        elif name == "eidos_echo":
            text = str(args.get("text", ""))
            out = text
        elif name == "fetch_https_url":
            out = _fetch_https_url_execute(args)
        elif name == "bash":
            out = _bash_execute(args)
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
