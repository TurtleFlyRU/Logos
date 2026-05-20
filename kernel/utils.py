"""Утилиты для атомарной записи данных."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sanitize_unicode_text(s: str) -> str:
    """Приводит строку к кодированию без суррогатов UTF-16 (валидная для JSON/HTTP UTF-8).

    Lone surrogates (например после внешних источников) заменяются при кодировании
    UTF-8 (часто на ``U+003F``, «?», вместо недопустимого кода позиции).

    Args:
        s: Исходный текст Python (может содержать суррогаты).

    Returns:
        Строка, которая кодируется в UTF-8 без ошибок.
    """
    if not s:
        return s
    return s.encode("utf-8", errors="replace").decode("utf-8")


def sanitize_for_json_transport(obj: Any) -> Any:
    """Рекурсивно чистит ``str`` в структуре перед ``json.dumps`` / HTTP-телом.

    Ключи dict, если это строки, тоже нормализуются.
    """
    if isinstance(obj, str):
        return sanitize_unicode_text(obj)
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            nk = sanitize_unicode_text(k) if isinstance(k, str) else k
            out[nk] = sanitize_for_json_transport(v)
        return out
    if isinstance(obj, list):
        return [sanitize_for_json_transport(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_for_json_transport(v) for v in obj)
    return obj


def atomic_write(path: Path, data: Any, **kwargs: Any) -> None:
    """Атомарная запись JSON: temp → fsync → rename.

    Предотвращает коррупцию файла при краше в середине записи.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False, **kwargs)
        # Защита от «битых» строк с lone-surrogates (например, после внешних источников).
        # Вместо падения при сохранении — заменяем некодируемые символы на U+FFFD.
        os.write(fd, content.encode("utf-8", errors="replace"))
        os.fsync(fd)
    finally:
        os.close(fd)

    tmp = Path(tmp_path)
    tmp.rename(path)
