"""Browser tool — скриншоты, console log, отладка страниц.

Использует Playwright + системный Chromium (snap).
"""

import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from kernel.config import REPO_ROOT

SCREENSHOT_DIR = REPO_ROOT / "data" / "screenshots"


def _ensure_dir() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def screenshot(url: str, timeout_ms: int = 15000, full_page: bool = True) -> dict[str, Any]:
    """Сделать скриншот страницы, вернуть console log и путь к скриншоту."""
    _ensure_dir()
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"screenshot_{ts}.png"

    console_logs: list[dict[str, str]] = []
    result: dict[str, Any] = {"url": url, "console": [], "screenshot_path": None, "error": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/snap/bin/chromium",
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 720})

            page.on("console", lambda msg: console_logs.append({
                "level": msg.type,
                "text": msg.text[:500],
                "location": str(msg.location) if hasattr(msg, "location") else "",
            }))

            page.on("pageerror", lambda err: console_logs.append({
                "level": "error",
                "text": f"PAGE ERROR: {err}"[:500],
                "location": "",
            }))

            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            page.screenshot(path=str(path), full_page=full_page)
            title = page.title()

            browser.close()

        result["console"] = console_logs
        result["screenshot_path"] = str(path)
        result["title"] = title

    except Exception as e:
        result["error"] = str(e)[:500]

    return result


def console_logs(url: str, timeout_ms: int = 15000) -> dict[str, Any]:
    """Открыть страницу и собрать console log, без скриншота."""
    console_logs: list[dict[str, str]] = []
    result: dict[str, Any] = {"url": url, "console": [], "error": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/snap/bin/chromium",
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = browser.new_page()

            page.on("console", lambda msg: console_logs.append({
                "level": msg.type,
                "text": msg.text[:500],
            }))

            page.on("pageerror", lambda err: console_logs.append({
                "level": "error",
                "text": f"PAGE ERROR: {err}"[:500],
            }))

            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            title = page.title()
            browser.close()

        result["console"] = console_logs
        result["title"] = title

    except Exception as e:
        result["error"] = str(e)[:500]

    return result


def html_source(url: str, timeout_ms: int = 15000) -> dict[str, Any]:
    """Получить HTML-код страницы."""
    result: dict[str, Any] = {"url": url, "html": "", "error": None}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/snap/bin/chromium",
                headless=True,
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            result["html"] = page.content()[:50000]
            result["title"] = page.title()
            browser.close()

    except Exception as e:
        result["error"] = str(e)[:500]

    return result
