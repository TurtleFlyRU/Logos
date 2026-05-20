"""Синхронный рантайм диалога CLI."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

import httpx

from cli.context import build_chat_messages_for_llm, tools_allowed_for_chat_line
from cli.identity import try_capture_user_display_name
from cli.llm import LLMConfigError, chat_completions, format_llm_pending_banner

if TYPE_CHECKING:
    from kernel.memory import Memory
    from cli.tool_routing import ToolRoundRoute


def _tool_names_from_specs(tool_specs: list[dict[str, Any]]) -> list[str]:
    """Извлечь имена tool specs в формате chat/completions."""
    names: list[str] = []
    for spec in tool_specs:
        fn = spec.get("function") or {}
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _cli_chat_llm_reply(
    memory: Any,
    session_id: str,
    tags: list[str],
    messages: list[dict[str, Any]],
    *,
    allow_tools: bool = True,
    tool_round_route: ToolRoundRoute | None = None,
) -> str | None:
    """Один пользовательский ход: опционально цикл tool_calls и финальный текст."""
    from cli.llm import chat_completion_assistant_message
    from cli.tools import (
        assistant_message_for_api,
        builtin_tool_specs,
        execute_tool,
        max_tool_rounds,
        progress_echo_enabled,
        tools_enabled,
    )

    if not tools_enabled():
        text = chat_completions(messages)
        return text if (text or "").strip() else None

    if not allow_tools:
        amsg = chat_completion_assistant_message(messages, tools=None)
        return ((amsg.get("content") or "").strip() or None)

    from kernel.instrumental import InstrumentalRegistry

    instrumental = InstrumentalRegistry()
    tool_specs = builtin_tool_specs()
    max_r = max_tool_rounds()
    rounds = 0
    reply_text = ""
    runtime_params = tool_round_route.runtime_params if tool_round_route is not None else None
    while rounds < max_r:
        rounds += 1
        amsg = chat_completion_assistant_message(
            messages,
            tools=tool_specs,
            runtime_params=runtime_params,
        )
        tcalls = amsg.get("tool_calls")
        if tcalls:
            memory.working.add_event(
                {
                    "role": "assistant",
                    "content": amsg.get("content"),
                    "tool_calls": tcalls,
                    "cli_session_id": session_id,
                    "tags": tags,
                    "event_type": "cli_chat",
                }
            )
            messages.append(assistant_message_for_api(amsg))
            for tc in tcalls:
                fn = tc.get("function") or {}
                name = str(fn.get("name") or "")
                args = str(fn.get("arguments") or "{}")
                tcid = str(tc.get("id") or "")
                if progress_echo_enabled():
                    print(f"[eidos] tool {name}", flush=True)
                result = execute_tool(name, args, registry=instrumental)
                memory.working.add_event(
                    {
                        "role": "tool",
                        "tool_call_id": tcid,
                        "content": result,
                        "cli_session_id": session_id,
                        "tags": tags,
                        "event_type": "cli_chat",
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tcid, "content": result}
                )
            continue
        reply_text = (amsg.get("content") or "").strip()
        break
    else:
        reply_text = (
            "[eidos] Лимит раундов инструментов (EIDOS_TOOL_ROUNDS или EIDOS_TOOLS=0)."
        )

    return reply_text if reply_text else None


def _friendly_http_status_line(code: int) -> str | None:
    """Краткое пояснение по распространённым кодам ответа LLM API."""
    return {
        503: (
            "Сервис API временно недоступен (503): перегрузка или работы на стороне "
            "провайдера. Повторите позже или задайте другой LLM_BASE_URL."
        ),
        502: (
            "Шлюз вернул 502: сбой или таймаут у провайдера или прокси; повторите или "
            "проверьте LLM_IGNORE_PROXY."
        ),
        429: "Слишком много запросов (429): подождите или проверьте лимиты ключа.",
        401: "Не авторизован (401): проверьте LLM_API_KEY / DEEPSEEK_API_KEY.",
        403: "Доступ запрещён (403): ключ или модель недоступны для этого аккаунта.",
    }.get(code)


def _http_error_body_snippet(
    response: httpx.Response, max_len: int = 900
) -> str | None:
    """Обрезка тела ответа для терминала (ошибки API часто приходят как JSON/HTML)."""
    try:
        raw = response.content[: max_len + 120]
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed


def _print_http_status_error(exc: httpx.HTTPStatusError) -> None:
    """Краткая подсказка + исходное сообщение httpx + фрагмент тела ответа провайдера."""
    code = exc.response.status_code
    hint = _friendly_http_status_line(code)
    if hint:
        print(f"[eidos] {hint}", flush=True)
    print(f"[eidos] {exc}", flush=True)
    snippet = _http_error_body_snippet(exc.response)
    if snippet:
        print(f"[eidos] Тело ответа API: {snippet}", flush=True)


def run_chat_interactive(
    memory: Memory,
    session_id: str,
    *,
    use_llm: bool = True,
    stub: bool = False,
    show_metrics: bool = False,
) -> None:
    """Интерактивный цикл: WM + LLM, события помечены cli_session_id."""
    from cli.budget_view import format_chat_budget_report
    from cli import session as sess
    from cli.env_view import format_cli_env_report
    from cli.pipelines.chat_commands import (
        format_chat_pipeline_help,
        parse_chat_pipeline_line,
    )
    from cli.pipelines.runner import run_pipeline_in_chat_session

    tags = ["cli", "eidos"]
    short = session_id[:8] + "…"
    print(
        f"Сессия CLI {short} ({session_id}). Команды: /exit, /quit "
        "| /env | /budget | /pipeline, /run, /review (см. /pipeline help)",
        flush=True,
    )
    print(format_cli_env_report(show_unset=True), flush=True)
    print(format_chat_budget_report(memory, session_id), flush=True)
    if stub or not use_llm:
        print("[stub] Режим без вызова LLM (--stub).", flush=True)

    prompt_interrupt_times: list[float] = []
    _prompt_ki_window_sec = 1.6

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            now = time.monotonic()
            prompt_interrupt_times[:] = [
                t for t in prompt_interrupt_times if now - t < _prompt_ki_window_sec
            ]
            prompt_interrupt_times.append(now)
            if len(prompt_interrupt_times) >= 2:
                print("\n[eidos] Выход по двойному Ctrl+C.", flush=True)
                break
            print(
                "\n[eidos] Прервано на приглашении. Выход: /exit или /quit "
                f"(или второй Ctrl+C в течение {_prompt_ki_window_sec:.1f} с).",
                flush=True,
            )
            continue
        if not line:
            continue
        low = line.lower()
        if low in ("/exit", "/quit"):
            break
        if low in ("/env", "/env all"):
            print(format_cli_env_report(show_unset=True), flush=True)
            continue
        if low == "/env active":
            print(format_cli_env_report(show_unset=False), flush=True)
            continue
        if low in ("/budget", "/budget now", "/budget all"):
            print(format_chat_budget_report(memory, session_id), flush=True)
            continue

        pipe_parsed = parse_chat_pipeline_line(line)
        if pipe_parsed == "help":
            print(format_chat_pipeline_help(), flush=True)
            continue
        if isinstance(pipe_parsed, str):
            print(pipe_parsed, flush=True)
            continue
        if pipe_parsed is not None:
            try:
                p_code, _assistant_blob = run_pipeline_in_chat_session(
                    memory,
                    session_id,
                    pipe_parsed.name,
                    pipe_parsed.topic,
                    paths=tuple(pipe_parsed.paths),
                    stub=stub or not use_llm,
                )
                sess.touch_session(session_id, last_turn_at=time.time())
                if p_code != 0:
                    print(
                        f"[eidos] пайплайн завершился с кодом {p_code} (см. вывод выше).",
                        flush=True,
                    )
            except KeyboardInterrupt:
                print(
                    "\n[eidos] Ctrl+C — пайплайн прерван (этап смотрите по строкам "
                    "HTTP → / ← и сообщениям [pipeline:*] выше).",
                    flush=True,
                )
            except LLMConfigError as exc:
                print(f"[eidos] {exc}", flush=True)
            except httpx.TimeoutException as exc:
                print(
                    f"[eidos] Таймаут запроса к API ({exc!s}) во время пайплайна. "
                    "Проверьте сеть и LLM_BASE_URL.",
                    flush=True,
                )
            except httpx.HTTPStatusError as exc:
                _print_http_status_error(exc)
            except httpx.HTTPError as exc:
                print(f"[eidos] Ошибка HTTP в пайплайне: {exc}", flush=True)
            except OSError as exc:
                print(f"[eidos] Сеть/ОС в пайплайне: {exc}", flush=True)
            except Exception as exc:
                print(f"[eidos] Ошибка пайплайна: {exc}", flush=True)
            continue

        try_capture_user_display_name(memory, line)

        memory.working.add_event(
            {
                "role": "user",
                "content": line,
                "cli_session_id": session_id,
                "tags": tags,
                "event_type": "cli_chat",
            }
        )

        reply: str | None = None

        if stub or not use_llm:
            reply = f"[stub] {line[:2000]}"
        else:
            messages = build_chat_messages_for_llm(
                memory,
                session_id,
                user_message=line,
            )
            if show_metrics:
                from cli.context import chat_context_metrics, format_context_metrics_sizes
                import os

                raw = os.environ.get("EIDOS_CHAT_TOTAL_CHARS", "").strip()
                total_budget = int(raw) if raw.isdigit() else 0

                m = chat_context_metrics(messages, total_budget=total_budget)
                ctx = memory.working.data.get("context") or {}
                user_name = (
                    str(ctx.get("user_display_name")).strip()
                    if isinstance(ctx.get("user_display_name"), str)
                    else ""
                )
                layers = m["layers"]
                layers_short = ",".join(
                    k
                    for k, v in layers.items()
                    if v
                    and k
                    in (
                        "identity",
                        "wm_plan_focus",
                        "attention",
                        "active_memory",
                        "boot_snippet",
                        "principles",
                        "wm_summary_block",
                    )
                )
                sizes = format_context_metrics_sizes(m)
                print(
                    "[metrics] "
                    f"budget={m['budget_total_chars']} chars; "
                    f"payload={m['total_chars']} chars; "
                    f"tok≈{m['approx_prompt_tokens']}; "
                    f"sizes={sizes or '-'}; "
                    f"system={m['system_messages']}; hist={m['history_messages']} (tool={m['tool_messages']}); "
                    f"user={user_name or '-'}; "
                    f"layers={layers_short or '-'}",
                    flush=True,
                )
            try:
                tool_round_route = None
                allow_tools = tools_allowed_for_chat_line(line)
                if allow_tools:
                    from cli.tool_routing import resolve_tool_round_route
                    from cli.tools import builtin_tool_specs, progress_echo_enabled, tools_enabled

                    if tools_enabled():
                        tool_specs = builtin_tool_specs()
                        tool_round_route = resolve_tool_round_route(
                            _tool_names_from_specs(tool_specs)
                        )
                        if tool_round_route is not None and progress_echo_enabled():
                            print(
                                f"[eidos] route {tool_round_route.diagnostics}",
                                flush=True,
                            )

                pending_runtime = (
                    tool_round_route.runtime_params
                    if tool_round_route is not None
                    else None
                )
                print(
                    format_llm_pending_banner(runtime_params=pending_runtime),
                    flush=True,
                )
                reply = _cli_chat_llm_reply(
                    memory,
                    session_id,
                    tags,
                    messages,
                    allow_tools=allow_tools,
                    tool_round_route=tool_round_route,
                )
                if not (reply or "").strip():
                    print(
                        "[eidos] Модель вернула пустой ответ. Проверьте LLM_MODEL "
                        "и ответ API.",
                        flush=True,
                    )
                    reply = None
            except KeyboardInterrupt:
                print(
                    "\n[eidos] Ctrl+C — запрос прерван (этап смотрите по последним строкам "
                    "«HTTP → / ←» и «Ожидание: …» выше).",
                    flush=True,
                )
                reply = None
            except LLMConfigError as exc:
                print(f"[eidos] {exc}", flush=True)
                reply = None
            except httpx.TimeoutException as exc:
                print(
                    f"[eidos] Таймаут запроса к API ({exc!s}). "
                    "Проверьте сеть и LLM_BASE_URL (LLM_TIMEOUT_SEC — лимит в секундах). "
                    "Если подозреваете лишний прокси в окружении — export LLM_IGNORE_PROXY=1.",
                    flush=True,
                )
                reply = None
            except httpx.HTTPStatusError as exc:
                _print_http_status_error(exc)
                reply = None
            except httpx.HTTPError as exc:
                print(f"[eidos] Ошибка HTTP: {exc}", flush=True)
                reply = None
            except OSError as exc:
                print(f"[eidos] Сеть/ОС: {exc}", flush=True)
                reply = None
            except Exception as exc:
                print(f"[eidos] Неожиданная ошибка: {exc}", flush=True)
                reply = None

        if show_metrics and (stub or not use_llm):
            # В stub-режиме тоже полезно видеть «что бы пошло в LLM».
            from cli.context import chat_context_metrics, format_context_metrics_sizes
            import os

            messages = build_chat_messages_for_llm(memory, session_id, user_message=line)
            raw = os.environ.get("EIDOS_CHAT_TOTAL_CHARS", "").strip()
            total_budget = int(raw) if raw.isdigit() else 0

            m = chat_context_metrics(messages, total_budget=total_budget)
            ctx = memory.working.data.get("context") or {}
            user_name = (
                str(ctx.get("user_display_name")).strip()
                if isinstance(ctx.get("user_display_name"), str)
                else ""
            )
            layers = m["layers"]
            layers_short = ",".join(k for k, v in layers.items() if v)
            sizes = format_context_metrics_sizes(m)
            print(
                "[metrics] "
                f"budget={m['budget_total_chars']} chars; "
                f"payload={m['total_chars']} chars; "
                f"tok≈{m['approx_prompt_tokens']}; "
                f"sizes={sizes or '-'}; "
                f"system={m['system_messages']}; hist={m['history_messages']} (tool={m['tool_messages']}); "
                f"user={user_name or '-'}; "
                f"layers={layers_short or '-'}",
                flush=True,
            )

        if reply:
            print(reply, flush=True)
            memory.working.add_event(
                {
                    "role": "assistant",
                    "content": reply,
                    "cli_session_id": session_id,
                    "tags": tags,
                    "event_type": "cli_chat",
                }
            )
            sess.touch_session(session_id, last_turn_at=time.time())


def run_ask(question: str, *, use_llm: bool = True) -> int:
    """Один запрос: LLM при наличии ключей, иначе заглушка. Возвращает код выхода."""
    if use_llm:
        try:
            print(format_llm_pending_banner(), flush=True)
            text = chat_completions([{"role": "user", "content": question}])
            print(text)
            return 0
        except LLMConfigError as exc:
            print(f"[stub] {exc}", file=sys.stderr)
            print(f"[stub] Вопрос был: {question[:500]}")
            return 2
        except httpx.TimeoutException as exc:
            print(f"[eidos] Таймаут: {exc}", flush=True)
            return 3
        except httpx.HTTPStatusError as exc:
            _print_http_status_error(exc)
            return 3
        except httpx.HTTPError as exc:
            print(f"[eidos] Ошибка HTTP: {exc}", flush=True)
            return 3
        except KeyboardInterrupt:
            print(
                "\n[eidos] Ctrl+C — прервано (этап: строки HTTP → / ← и «Ожидание» выше).",
                flush=True,
            )
            return 130

    print(f"[stub] {question}")
    return 0
