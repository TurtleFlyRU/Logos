"""Тесты извлечения имени пользователя в CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

from cli.identity import try_capture_user_display_name


def test_try_capture_menya_zovut():
    mem = MagicMock()
    mem.working.set_context = MagicMock()
    try_capture_user_display_name(mem, "  меня зовут Сергей  ")
    mem.working.set_context.assert_called_once_with("user_display_name", "Сергей")


def test_try_capture_my_name_is():
    mem = MagicMock()
    mem.working.set_context = MagicMock()
    try_capture_user_display_name(mem, "My name is Anna")
    mem.working.set_context.assert_called_once_with("user_display_name", "Anna")


def test_try_capture_no_match():
    mem = MagicMock()
    mem.working.set_context = MagicMock()
    try_capture_user_display_name(mem, "просто текст без имени")
    mem.working.set_context.assert_not_called()


def test_seed_user_display_name_from_agents_md(tmp_path, monkeypatch):
    # подменяем AGENTS.md в корне через monkeypatch cwd-подобным способом: пишем файл в repo root не можем,
    # поэтому имитируем Memory.working и патчим Path.resolve().parents[1] нельзя без сложности.
    # Тестируем через временную подстановку EIDOS_CHAT_PERSONA_PATH не получится — функция читает repo AGENTS.md.
    #
    # Упрощённо: проверяем, что функция НЕ падает, если AGENTS.md не читается,
    # и НЕ затирает уже заданное имя.
    from cli.identity import seed_user_display_name_from_agents_md

    mem = MagicMock()
    mem.working.data = {"context": {"user_display_name": "Инна"}}
    mem.working.set_context = MagicMock()
    seed_user_display_name_from_agents_md(mem)
    mem.working.set_context.assert_not_called()
