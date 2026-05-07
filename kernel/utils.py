"""Утилиты для атомарной записи данных."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)

    tmp = Path(tmp_path)
    tmp.rename(path)
