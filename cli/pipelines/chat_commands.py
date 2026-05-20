"""Разбор slash-команд пайплайна в интерактивном ``eidos chat``."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Literal

from cli.pipelines.registry import list_pipeline_names


@dataclass(frozen=True)
class ChatPipelineArgs:
    """Аргументы для :func:`cli.pipelines.runner.run_pipeline_in_chat_session`."""

    name: str
    topic: str
    paths: tuple[str, ...]


ParseChatPipelineResult = ChatPipelineArgs | Literal["help"] | str | None


def _known_pipelines() -> frozenset[str]:
    return frozenset(list_pipeline_names())


def format_chat_pipeline_help() -> str:
    """Краткая справка для ``/pipeline`` и ``/run``."""
    names = ", ".join(sorted(_known_pipelines()))
    return (
        "Пайплайны в чате (текущая сессия WM, без отдельного ``eidos run``):\n"
        f"  Доступные имена: {names}\n"
        "  /pipeline research <тема…>\n"
        "  /pipeline experiment <тема…>\n"
        "  /pipeline code_review [--paths ОТНОСИТЕЛЬНЫЙ_ПУТЬ]… <тема…>\n"
        "  /run — то же, что /pipeline\n"
        "  /review — сокращение для code_review (первый токен после команды — не имя пайплайна)\n"
        "Пути к файлам: повторяйте --paths для каждого файла; тема с пробелами — в кавычках (shlex).\n"
        "Сама строка-команда /pipeline не дублируется в истории как «user»: в WM пишется только результат."
    )


def parse_chat_pipeline_line(line: str) -> ParseChatPipelineResult:
    """Распознать ``/pipeline`` / ``/run`` / ``/review`` или вернуть None.

    Args:
        line: Сырая строка с приглашения ``>``.

    Returns:
        ``ChatPipelineArgs``, ``\"help\"``, строка с ошибкой для показа пользователю, либо None.
    """
    raw = line.strip()
    if not raw.startswith("/"):
        return None

    if raw.startswith("/pipeline"):
        rest = raw[len("/pipeline") :].strip()
    elif raw.startswith("/run"):
        rest = raw[len("/run") :].strip()
    elif raw.startswith("/review"):
        review_rest = raw[len("/review") :].strip()
        if not review_rest or review_rest.lower() in ("help", "-h", "--help"):
            return "help"
        rest = "code_review " + review_rest
    else:
        return None

    if not rest or rest.lower() in ("help", "-h", "--help"):
        return "help"

    try:
        tokens = shlex.split(rest)
    except ValueError as exc:
        return f"Не разобрать аргументы (кавычки?): {exc}"

    if not tokens:
        return "help"

    name = tokens[0]
    known = _known_pipelines()
    if name not in known:
        return f"Неизвестный пайплайн {name!r}. Допустимо: {', '.join(sorted(known))}."

    if name in ("research", "experiment"):
        topic = " ".join(tokens[1:]).strip()
        return ChatPipelineArgs(name=name, topic=topic, paths=())

    if name == "code_review":
        paths: list[str] = []
        i = 1
        while i < len(tokens):
            if tokens[i] == "--paths" and i + 1 < len(tokens):
                paths.append(tokens[i + 1])
                i += 2
                continue
            break
        topic = " ".join(tokens[i:]).strip()
        return ChatPipelineArgs(name=name, topic=topic, paths=tuple(paths))

    return f"Внутренняя ошибка: неожиданное имя {name!r}."
