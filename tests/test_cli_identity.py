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
