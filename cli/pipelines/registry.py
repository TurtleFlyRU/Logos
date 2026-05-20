"""Именованные пайплайны CLI: реестр и короткие описания."""

from __future__ import annotations

_PIPELINE_META: dict[str, str] = {
    "research": (
        "Один проход LLM с расширенным хвостом WM и активной памятью (пресет research)."
    ),
    "experiment": (
        "Один проход LLM без инструментов: упор на boot-фрагмент и память "
        "(пресет experiment; для набросков гипотез и чеклистов)."
    ),
    "code_review": (
        "Два последовательных вызова LLM: черновой разбор затем финальное резюме. "
        "Профили этапов: переменная EIDOS_CODE_REVIEW_PROFILES=name1,name2 "
        "(иначе дважды текущая конфигурация LLM без смены EIDOS_AGENT_PROFILE)."
    ),
}


def list_pipeline_names() -> tuple[str, ...]:
    """Допустимые значения первого аргумента команды ``run``."""
    return tuple(sorted(_PIPELINE_META.keys()))


def describe_pipeline(name: str) -> str | None:
    """Однострочное описание или None если имя неизвестно."""
    return _PIPELINE_META.get(name)
