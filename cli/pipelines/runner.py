"""Исполнение именованных пайплайнов (фаза 9b).

Переменные окружения:
- ``EIDOS_CODE_REVIEW_PROFILES`` — через запятую два имени профиля из YAML агентов
  для этапов ``code_review`` (опционально).
"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence

from cli.identity import seed_user_display_name_from_agents_md
from cli.pipelines.presets import pipeline_preset

_LLM_STUB_PREFIX = "[pipeline stub]"
_CODE_REVIEW_PROFILES_ENV = "EIDOS_CODE_REVIEW_PROFILES"


def _make_emitter(collect: list[str] | None) -> Callable[[str], None]:
    """Печать в терминал; опционально накопить строки для WM (ответ ассистента в чате)."""

    def _emit(message: str) -> None:
        if collect is not None:
            collect.append(message)
        print(message, flush=True)

    return _emit


@contextmanager
def _temporary_agent_profile(profile: str | None) -> Iterator[None]:
    """Если профиль задан — временно установить ``EIDOS_AGENT_PROFILE``."""
    if not (profile and str(profile).strip()):
        yield
        return
    name = str(profile).strip()
    previous = os.environ.get("EIDOS_AGENT_PROFILE")
    os.environ["EIDOS_AGENT_PROFILE"] = name
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("EIDOS_AGENT_PROFILE", None)
        else:
            os.environ["EIDOS_AGENT_PROFILE"] = previous


def _parse_code_review_profiles() -> tuple[str | None, str | None]:
    raw = os.environ.get(_CODE_REVIEW_PROFILES_ENV, "").strip()
    if not raw:
        return (None, None)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) >= 2:
        return (parts[0], parts[1])
    if len(parts) == 1:
        return (parts[0], parts[0])
    return (None, None)


def _gather_paths_block(paths: Sequence[str]) -> str:
    """Прочитать относительные пути в корне репозитория (как инструмент read_workspace_file)."""
    from cli.tools import execute_tool
    from kernel.instrumental import InstrumentalRegistry

    registry = InstrumentalRegistry()
    blocks: list[str] = []
    for rel in paths:
        rel = rel.strip()
        if not rel:
            continue
        result = execute_tool(
            "read_workspace_file",
            json.dumps({"path": rel}, ensure_ascii=False),
            registry=registry,
        )
        if result.lstrip().startswith("{") and '"error"' in result[:200]:
            raise ValueError(f"Не удалось прочитать {rel}: {result}")
        blocks.append(f"### {rel}\n{result}")
    if not blocks:
        return ""
    return "\n\n".join(blocks)


def _llm_text(
    messages: list[dict[str, str]],
    *,
    stub: bool,
    chat_completions: Callable[..., str],
) -> str:
    if stub:
        last = messages[-1].get("content", "") if messages else ""
        snippet = (last[:400] + "…") if len(last) > 400 else last
        return f"{_LLM_STUB_PREFIX} {snippet}"
    return chat_completions(messages)


def _run_single_turn_pipeline(
    memory: Any,
    session_id: str,
    topic: str,
    pipeline_slug: str,
    *,
    stub: bool,
    chat_completions: Callable[..., str],
    emit: Callable[[str], None],
) -> int:
    from cli.context import build_chat_messages_for_llm

    tags = ["cli", "eidos", "pipeline", pipeline_slug]
    memory.working.add_event(
        {
            "role": "user",
            "content": topic,
            "cli_session_id": session_id,
            "tags": tags,
            "event_type": "cli_pipeline",
        }
    )
    messages = build_chat_messages_for_llm(
        memory,
        session_id,
        user_message=topic,
    )
    text = _llm_text(messages, stub=stub, chat_completions=chat_completions)
    emit(text)
    memory.working.add_event(
        {
            "role": "assistant",
            "content": text,
            "cli_session_id": session_id,
            "tags": tags,
            "event_type": "cli_pipeline",
        }
    )
    return 0


def _run_code_review(
    memory: Any,
    session_id: str,
    topic: str,
    paths: Sequence[str],
    *,
    stub: bool,
    chat_completions: Callable[..., str],
    emit: Callable[[str], None],
) -> int:
    from cli.context import build_chat_messages_for_llm

    tags = ["cli", "eidos", "pipeline", "code_review"]
    file_block = _gather_paths_block(paths) if paths else ""
    base = topic.strip()
    if file_block and base:
        user_intro = f"{base}\n\n{file_block}"
    elif file_block:
        user_intro = f"Проведи ревью следующих файлов:\n\n{file_block}"
    else:
        user_intro = base
    if not user_intro.strip():
        emit("Укажите текст запроса и/или --paths к файлам.")
        return 2

    p1, p2 = _parse_code_review_profiles()

    def stage(user_content: str, label: str, profile: str | None) -> str:
        emit(f"[pipeline:code_review] {label}")
        memory.working.add_event(
            {
                "role": "user",
                "content": user_content,
                "cli_session_id": session_id,
                "tags": tags,
                "event_type": "cli_pipeline",
            }
        )
        messages = build_chat_messages_for_llm(
            memory,
            session_id,
            user_message=user_content,
        )
        with _temporary_agent_profile(profile):
            out = _llm_text(messages, stub=stub, chat_completions=chat_completions)
        memory.working.add_event(
            {
                "role": "assistant",
                "content": out,
                "cli_session_id": session_id,
                "tags": tags,
                "event_type": "cli_pipeline",
            }
        )
        emit(out)
        return out

    first_user = (
        "Этап 1 из 2 — кратко перечисли потенциальные проблемы, риски и вопросы "
        f"(bullet list).\n\n{user_intro}"
    )
    draft = stage(first_user, "этап 1/2 (черновик)", p1)

    second_user = (
        "Этап 2 из 2 — на основе черновика выдай сжатое итоговое ревью в Markdown "
        "(что исправить в первую очередь).\n\n"
        f"Черновик предыдущего этапа:\n\n{draft}\n\n---\n\nИсходный запрос и код:\n\n"
        f"{user_intro}"
    )
    stage(second_user, "этап 2/2 (итог)", p2)

    return 0


def _dispatch_pipeline(
    memory: Any,
    session_id: str,
    name: str,
    topic: str,
    path_list: list[str],
    *,
    stub: bool,
    chat_completions: Callable[..., str],
    emit: Callable[[str], None],
) -> int:
    """Выполнить пайплайн на уже открытой памяти и session_id."""
    topic = topic.strip()
    cc = chat_completions
    if name in ("research", "experiment"):
        if not topic.strip():
            emit(
                "Пайплайны research/experiment ожидают текст темы после имени пайплайна.",
            )
            return 2
        with pipeline_preset(name):
            return _run_single_turn_pipeline(
                memory,
                session_id,
                topic,
                name,
                stub=stub,
                chat_completions=cc,
                emit=emit,
            )

    if name == "code_review":
        if not topic.strip() and not path_list:
            emit(
                "Пайплайн code_review: задайте тему или один и более ключей `--paths`.",
            )
            return 2
        try:
            with pipeline_preset("code_review"):
                return _run_code_review(
                    memory,
                    session_id,
                    topic,
                    path_list,
                    stub=stub,
                    chat_completions=cc,
                    emit=emit,
                )
        except (OSError, ValueError) as exc:
            emit(f"[eidos] {exc}")
            return 2

    emit(f"Неизвестный пайплайн: {name}")
    return 2


def run_pipeline_in_chat_session(
    memory: Any,
    chat_session_id: str,
    name: str,
    topic: str,
    *,
    paths: Sequence[str] = (),
    stub: bool = False,
    chat_completions: Callable[..., str] | None = None,
) -> tuple[int, str]:
    """Запуск пайплайна внутри активной CLI-сессии (та же WM, тот же session_id).

    Returns:
        (код выхода, полный текст, выведенный в чат/WMSummary для события ассистента).
    """
    from cli.llm import chat_completions as default_cc

    cc = chat_completions if chat_completions is not None else default_cc
    lines_acc: list[str] = []
    emit = _make_emitter(lines_acc)
    sid_short = chat_session_id[:8] + "…"
    emit(f"[pipeline:{name}] режим чата · сессия {sid_short}")
    code = _dispatch_pipeline(
        memory,
        chat_session_id,
        name,
        topic,
        [p for p in paths if str(p).strip()],
        stub=stub,
        chat_completions=cc,
        emit=emit,
    )
    return code, "\n".join(lines_acc)


def run_pipeline(
    name: str,
    topic: str,
    *,
    paths: Sequence[str],
    stub: bool = False,
    no_boot: bool = False,
    chat_completions: Callable[..., str] | None = None,
) -> int:
    """Создаёт новую CLI-сессию, опционально boot, выполняет пайплайн.

    Args:
        name: ``research``, ``experiment`` (один проход) или ``code_review`` (два этапа).
        topic: Текст задачи (флаг ``-m`` или позиционные слова в CLI).
        paths: Относительные пути файлов для вставки в промпт ``code_review``.
        stub: Не дергать API (локальная заглушка для вывода).
        no_boot: Не выполнять ``run_cli_chat_boot``.
        chat_completions: Инъекция для тестов; по умолчанию ``cli.llm.chat_completions``.

    Returns:
        Код выхода процесса (0 или 2 при ошибке валидации).
    """
    from cli import session as sess
    from kernel.memory import Memory

    from cli.llm import chat_completions as default_cc

    cc = chat_completions if chat_completions is not None else default_cc
    topic = topic.strip()

    memory = Memory(auto_boot=False)

    sid = sess.new_session_id()
    memory.working.clear()
    memory.working.set_context("cli_session_id", sid)
    memory.working.set_context("cli_transport", "eidos")
    memory.working.set_context("pipeline", name)
    sess.touch_session(sid)
    sess.write_latest(sid)
    seed_user_display_name_from_agents_md(memory)

    if not no_boot:
        try:
            from kernel.boot import run_cli_chat_boot

            run_cli_chat_boot(memory)
        except Exception as exc:
            print(f"[eidos] Boot не выполнен: {exc}", flush=True)

    iso_emit = _make_emitter(None)
    iso_emit(f"[pipeline:{name}] отдельная сессия WM · {sid[:8]}…")

    path_list = [p for p in paths if str(p).strip()]
    if name in ("research", "experiment") and not topic.strip():
        iso_emit(
            "Пайплайны research/experiment ожидают текст темы позиционно или через -m/--prompt.",
        )
        return 2
    return _dispatch_pipeline(
        memory,
        sid,
        name,
        topic,
        path_list,
        stub=stub,
        chat_completions=cc,
        emit=iso_emit,
    )


def run_pipeline_cli(args: argparse.Namespace) -> int:
    """Точка входа из cli.app после установки переменных окружения профиля (если была)."""
    paths = getattr(args, "paths", None) or []
    path_seq = [str(p).strip() for p in paths if str(p).strip()]
    tail = getattr(args, "topic", None) or []
    tail_parts = tail if isinstance(tail, (list, tuple)) else [tail]
    topic_tail = " ".join(str(t) for t in tail_parts).strip()
    prompt = str(getattr(args, "prompt", "") or "").strip()
    topic_merged = prompt or topic_tail
    return run_pipeline(
        str(args.pipeline),
        topic_merged,
        paths=path_seq,
        stub=bool(getattr(args, "stub", False)),
        no_boot=bool(getattr(args, "no_boot", False)),
    )
