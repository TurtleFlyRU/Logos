#!/usr/bin/env python3
"""JSON-lines RPC для Rust ``eidos chat`` (фаза 2 parity).

Запуск: ``python3 kernel/eidos_sidecar.py`` из корня репозитория (``PYTHONPATH=.<repo>``).
На stdin — одна JSON-строка на запрос; на stdout — одна JSON-строка ответа.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# До тяжёлых импортов — не засорять stdout (Rust парсит только JSON).
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from kernel.config import load_repo_dotenv

load_repo_dotenv()


def _memory() -> Any:
    from kernel.memory import Memory

    return Memory(auto_boot=False)


def _ok(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": result}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _dispatch(req: dict[str, Any]) -> dict[str, Any]:
    op = str(req.get("op") or "").strip()
    if op == "ping":
        return _ok({})

    if op == "seed_identity":
        from cli.identity import seed_user_display_name_from_agents_md

        seed_user_display_name_from_agents_md(_memory())
        return _ok({})

    if op == "boot":
        from kernel.boot import run_cli_chat_boot

        text = run_cli_chat_boot(_memory())
        return _ok({"boot_text": text})

    if op == "startup_reports":
        from cli.budget_view import format_chat_budget_report
        from cli.env_view import format_cli_env_report

        m = _memory()
        ctx = m.working.data.get("context") or {}
        sid = str(ctx.get("cli_session_id") or "")
        mode = str(req.get("mode") or "full")
        env = format_cli_env_report(
            show_unset=mode in ("full", "env_all"),
        )
        budget = format_chat_budget_report(m, sid) if mode in ("full", "budget") else ""
        if mode == "env_active":
            env = format_cli_env_report(show_unset=False)
            budget = ""
        return _ok({"env": env, "budget": budget})

    if op == "build_messages":
        from cli.context import build_chat_messages_for_llm

        sid = str(req.get("session_id") or "")
        user = str(req.get("user_message") or "")
        msgs = build_chat_messages_for_llm(
            _memory(),
            sid,
            user_message=(user if user else None),
        )
        return _ok({"messages": msgs})

    if op == "capture_identity":
        from cli.identity import try_capture_user_display_name

        line = str(req.get("line") or "")
        try_capture_user_display_name(_memory(), line)
        return _ok({})

    if op == "tools_allowed":
        from cli.context import tools_allowed_for_chat_line

        line = str(req.get("line") or "")
        return _ok({"allowed": tools_allowed_for_chat_line(line)})

    if op == "context_metrics":
        from cli.budget_view import format_chat_budget_report
        from cli.context import (
            _total_chat_char_budget,
            build_chat_messages_for_llm,
            chat_context_metrics,
        )

        m = _memory()
        ctx = m.working.data.get("context") or {}
        sid = str(req.get("session_id") or ctx.get("cli_session_id") or "")
        user_raw = str(req.get("user_message") or "").strip()
        user_message = user_raw if user_raw else None
        total_budget = _total_chat_char_budget()
        messages = build_chat_messages_for_llm(
            m,
            sid,
            user_message=user_message,
        )
        metrics = chat_context_metrics(messages, total_budget=total_budget)
        budget_report = format_chat_budget_report(
            m,
            sid,
            user_message=user_message,
        )
        return _ok({"metrics": metrics, "budget_report": budget_report})

    if op == "active_memory_block":
        from cli.context import format_active_memory_retrieval_block

        m = _memory()
        ctx = m.working.data.get("context") or {}
        sid = str(req.get("session_id") or ctx.get("cli_session_id") or "")
        user_raw = str(req.get("user_message") or "").strip()
        user_message = user_raw if user_raw else None
        max_raw = req.get("max_chars")
        max_chars = None
        if max_raw is not None:
            try:
                mc = int(max_raw)
                if mc > 0:
                    max_chars = min(mc, 50_000)
            except (TypeError, ValueError):
                max_chars = None
        text = format_active_memory_retrieval_block(
            m,
            user_message,
            cli_session_id=sid,
            max_chars=max_chars,
        )
        return _ok({"text": text})

    if op == "semantic_principles_block":
        from cli.context import format_semantic_principles_block

        m = _memory()
        limit_raw = req.get("limit", 5)
        conf_raw = req.get("min_confidence", 0.7)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 5
        try:
            min_conf = float(conf_raw)
        except (TypeError, ValueError):
            min_conf = 0.7
        limit = max(1, min(100, limit))
        min_conf = max(0.0, min(1.0, min_conf))
        text = format_semantic_principles_block(
            m,
            limit=limit,
            min_confidence=min_conf,
        )
        return _ok({"text": text})

    if op == "post_public_log":
        from kernel.repo_public_log import maybe_append_cli_public_log

        m = _memory()
        event = req.get("event")
        if not isinstance(event, dict):
            return _ok({})
        ctx = m.working.data.get("context") or {}
        maybe_append_cli_public_log(event=event, context=ctx)
        return _ok({})

    if op == "pipeline_line":
        from cli.pipelines.chat_commands import (
            format_chat_pipeline_help,
            parse_chat_pipeline_line,
        )
        from cli.pipelines.runner import run_pipeline_in_chat_session

        line = str(req.get("line") or "")
        session_id = str(req.get("session_id") or "")
        stub = bool(req.get("stub"))
        parsed = parse_chat_pipeline_line(line)
        if parsed is None:
            return _ok({"action": "none"})
        if parsed == "help":
            return _ok({"action": "help", "text": format_chat_pipeline_help()})
        if isinstance(parsed, str):
            return _ok({"action": "error", "text": parsed})
        code, blob = run_pipeline_in_chat_session(
            _memory(),
            session_id,
            parsed.name,
            parsed.topic,
            paths=tuple(parsed.paths),
            stub=stub,
        )
        return _ok({"action": "run", "code": code, "text": blob})

    if op == "playwright_tool_specs":
        from cli.browser_tools import playwright_tool_enabled, playwright_tool_specs

        if not playwright_tool_enabled():
            return _ok({"specs": []})
        return _ok({"specs": playwright_tool_specs()})

    if op == "playwright_execute":
        from cli.browser_tools import execute_browser_tool, playwright_tool_enabled

        if not playwright_tool_enabled():
            return _err("Playwright выключен (EIDOS_PLAYWRIGHT=0/false/no/off)")
        name = str(req.get("name") or "").strip()
        raw = req.get("arguments_json")
        if raw is None:
            raw = req.get("arguments")
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(str(raw or "{}"))
            except json.JSONDecodeError as exc:
                return _err(f"arguments JSON: {exc}")
        try:
            text = execute_browser_tool(name, args)
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:
            tb = traceback.format_exc(limit=6)
            return _err(f"{exc!s}\n{tb}")
        return _ok({"text": text})

    if op == "memory_tool_specs":
        from cli.memory_tools import memory_tool_specs, memory_tools_enabled

        if not memory_tools_enabled():
            return _ok({"specs": []})
        return _ok({"specs": memory_tool_specs()})

    if op == "memory_execute":
        from cli.memory_tools import execute_memory_tool, is_memory_tool_name

        name = str(req.get("name") or "").strip()
        if not is_memory_tool_name(name):
            return _err(f"not a memory tool: {name!r}")
        raw = req.get("arguments_json")
        if raw is None:
            raw = req.get("arguments")
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(str(raw or "{}"))
            except json.JSONDecodeError as exc:
                return _err(f"arguments JSON: {exc}")
        try:
            text = execute_memory_tool(_memory(), name, args)
        except Exception as exc:
            tb = traceback.format_exc(limit=6)
            return _err(f"{exc!s}\n{tb}")
        return _ok({"text": text})

    if op == "memory_help":
        from cli.memory_tools import format_memory_help

        return _ok({"text": format_memory_help()})

    if op == "tools_help":
        from cli.tool_catalog import format_tools_help

        return _ok({"text": format_tools_help()})

    if op == "tools_catalog_block":
        from cli.tool_catalog import format_tools_catalog_block

        line = str(req.get("line") or "")
        text = format_tools_catalog_block(
            user_line=(line if line else None),
            max_chars=int(req.get("max_chars") or 4000),
        )
        return _ok({"text": text})

    if op == "tool_search_build_specs":
        from cli.tool_search import ToolSearchSession, tool_search_enabled
        from cli.tools import builtin_tool_specs

        if not tool_search_enabled():
            return _ok({"specs": builtin_tool_specs()})
        loaded_raw = req.get("loaded")
        session = ToolSearchSession.start()
        if isinstance(loaded_raw, list):
            for item in loaded_raw:
                name = str(item).strip()
                if name:
                    session.loaded.add(name)
        return _ok({"specs": session.build_api_tool_specs()})

    if op == "tool_search_execute":
        from cli.tool_search import ToolSearchSession, execute_tool_search

        session = ToolSearchSession.start()
        loaded_raw = req.get("loaded")
        if isinstance(loaded_raw, list):
            for item in loaded_raw:
                name = str(item).strip()
                if name:
                    session.loaded.add(name)
        raw = req.get("arguments_json")
        if raw is None:
            raw = req.get("arguments")
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(str(raw or "{}"))
            except json.JSONDecodeError as exc:
                return _err(f"arguments JSON: {exc}")
        if not isinstance(args, dict):
            args = {}
        text, newly = execute_tool_search(session, args)
        return _ok({"text": text, "loaded": sorted(session.loaded), "newly_loaded": newly})

    return _err(f"unknown op: {op!r}")


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                out = _err("request must be a JSON object")
            else:
                out = _dispatch(req)
        except Exception as exc:
            tb = traceback.format_exc(limit=8)
            out = _err(f"{exc!s}\n{tb}")
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
