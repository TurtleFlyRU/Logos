#!/usr/bin/env python3
"""Точка входа Эйдос CLI (из корня репозитория)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main() -> int:
    from kernel.config import load_repo_dotenv

    load_repo_dotenv()
    from cli.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
