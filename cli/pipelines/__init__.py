"""Именованные пайплайны CLI (фаза 9b).

Команды: ``eidos run <имя>`` и ``eidos review`` (сокращение для ``code_review``).
Пресеты сборки контекста — см. :mod:`cli.pipelines.presets`.
"""

from __future__ import annotations

from cli.pipelines.presets import pipeline_preset, preset_names
from cli.pipelines.registry import describe_pipeline, list_pipeline_names
from cli.pipelines.runner import run_pipeline, run_pipeline_in_chat_session

__all__ = [
    "describe_pipeline",
    "list_pipeline_names",
    "pipeline_preset",
    "preset_names",
    "run_pipeline",
    "run_pipeline_in_chat_session",
]
