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
    # Проверяем два сценария:
    # - не затирает уже заданное имя
    # - может засидить имя из persona файла через EIDOS_CHAT_PERSONA_PATH
    from cli.identity import seed_user_display_name_from_agents_md

    mem = MagicMock()
    mem.working.data = {"context": {"user_display_name": "Инна"}}
    mem.working.set_context = MagicMock()
    seed_user_display_name_from_agents_md(mem)
    mem.working.set_context.assert_not_called()

    mem2 = MagicMock()
    mem2.working.data = {"context": {}}
    mem2.working.set_context = MagicMock()
    persona = tmp_path / "AGENTS.md"
    persona.write_text(
        "Работаю в паре с человеком (TurtleFlyRU, Александр).",
        encoding="utf-8",
    )
    monkeypatch.setenv("EIDOS_CHAT_PERSONA_PATH", str(persona))
    seed_user_display_name_from_agents_md(mem2)
    mem2.working.set_context.assert_called_once_with("user_display_name", "Александр")
