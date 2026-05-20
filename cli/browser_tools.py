"""Playwright-инструменты для CLI-агента.

По умолчанию **включены**; отключить: ``EIDOS_PLAYWRIGHT=0`` (или ``false`` /
``no`` / ``off``). Живут в памяти текущего процесса CLI / sidecar, чтобы модель
могла выполнять несколько browser-шагов
подряд в одной сессии.

Прокси для Chromium можно задать через:
- ``EIDOS_PLAYWRIGHT_PROXY_SERVER``
- ``EIDOS_PLAYWRIGHT_PROXY_USERNAME``
- ``EIDOS_PLAYWRIGHT_PROXY_PASSWORD``
- ``EIDOS_PLAYWRIGHT_PROXY_BYPASS``
- ``EIDOS_PLAYWRIGHT_IGNORE_PROXY=1`` для принудительного direct-режима.

Если явный ``EIDOS_PLAYWRIGHT_PROXY_SERVER`` не задан и ``LLM_IGNORE_PROXY``
не включён, модуль попробует использовать ``HTTPS_PROXY`` / ``HTTP_PROXY``
и ``NO_PROXY``.
"""

from __future__ import annotations

import atexit
import ipaddress
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import kernel.config as kernel_config

_DEFAULT_BROWSER_TIMEOUT_MS = 10_000
_DEFAULT_SNAPSHOT_CHARS = 24_000
_DEFAULT_VIEWPORT_WIDTH = 1280
_DEFAULT_VIEWPORT_HEIGHT = 900
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_PLAYWRIGHT_TOOL_NAMES = (
    "browser_open",
    "browser_close",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_fill",
    "browser_press",
    "browser_screenshot",
)


@dataclass
class BrowserSession:
    """Живая Playwright-сессия для текущего процесса CLI.

    Attributes:
        driver: Объект, возвращённый ``sync_playwright().start()``.
        browser: Инстанс браузера Chromium.
        context: BrowserContext текущей сессии.
        page: Единственная активная вкладка MVP.
        headless: Была ли сессия запущена в headless-режиме.
        user_agent: Явный UA, если был передан при открытии.
    """

    driver: Any
    browser: Any
    context: Any
    page: Any
    headless: bool
    user_agent: str


_BROWSER_SESSION: BrowserSession | None = None


def playwright_tool_enabled() -> bool:
    """Проверить, включены ли Playwright-инструменты через env.

    По умолчанию включено (как ``EIDOS_TOOLS``). Выключение: ``0``, ``false``,
    ``no``, ``off``.
    """
    raw = os.environ.get("EIDOS_PLAYWRIGHT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def playwright_tool_names() -> tuple[str, ...]:
    """Имена Playwright-инструментов для диспетчеризации."""
    return _PLAYWRIGHT_TOOL_NAMES


def _load_sync_playwright() -> Any:
    """Загрузить фабрику ``sync_playwright`` с понятной ошибкой.

    Raises:
        RuntimeError: Если пакет Playwright не установлен.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Playwright не установлен. Установите зависимости CLI и затем "
            "выполните `python3 -m playwright install chromium`."
        ) from exc
    return sync_playwright


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "on")


def _bool_arg(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "on")


def _int_arg(
    value: Any,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def _browser_timeout_ms(args: dict[str, Any] | None = None) -> int:
    raw = ""
    if args is not None and args.get("timeout_ms") is not None:
        raw = str(args.get("timeout_ms")).strip()
    if not raw:
        raw = os.environ.get("EIDOS_PLAYWRIGHT_TIMEOUT_MS", "").strip()
    return _int_arg(raw or None, default=_DEFAULT_BROWSER_TIMEOUT_MS, min_value=500, max_value=120_000)


def _browser_screenshots_dir() -> Path:
    path = kernel_config.DATA_ROOT / "browser" / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _playwright_user_agent(args: dict[str, Any]) -> str:
    raw = str(args.get("user_agent", "") or "").strip()
    if raw:
        return raw
    return os.environ.get("EIDOS_PLAYWRIGHT_USER_AGENT", "").strip()


def _sanitize_url(url: str) -> str:
    """Разрешить только безопасные ``http(s)`` URL.

    По умолчанию блокирует loopback и явные приватные IP. Для локальной
    отладки можно задать ``EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST=1``.

    Args:
        url: Исходная строка URL.

    Returns:
        Нормализованный URL.

    Raises:
        ValueError: Если URL недопустим.
    """
    raw = url.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("разрешены только URL со схемой http или https")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("URL без хоста")

    if not _env_flag("EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST", default=False):
        if host in ("localhost", "::1") or host.endswith(".local"):
            raise ValueError(
                "локальные хосты запрещены; задайте EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST=1 "
                "для локальной отладки"
            )
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                "приватные/локальные IP запрещены; задайте "
                "EIDOS_PLAYWRIGHT_ALLOW_LOCALHOST=1 для локальной отладки"
            )

    return parsed.geturl()


def _page_title(page: Any) -> str:
    try:
        return str(page.title() or "").strip()
    except Exception:
        return ""


def _page_url(page: Any) -> str:
    try:
        return str(getattr(page, "url", "") or "").strip()
    except Exception:
        return ""


def _session_summary(prefix: str, page: Any, *, extra: str | None = None) -> str:
    lines = [prefix, f"url: {_page_url(page) or '-'}", f"title: {_page_title(page) or '-'}"]
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def _normalize_playwright_error(exc: Exception) -> RuntimeError:
    text = str(exc).strip()
    if "Executable doesn't exist" in text or "playwright install" in text:
        return RuntimeError(
            "Playwright установлен, но браузер Chromium ещё не скачан. "
            "Выполните `python3 -m playwright install chromium`."
        )
    return RuntimeError(text or "неизвестная ошибка Playwright")


def _first_env(*names: str) -> str:
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return raw
    return ""


def _playwright_ignore_proxy() -> bool:
    """Нужно ли принудительно выключить proxy на уровне Chromium process."""
    if _env_flag("EIDOS_PLAYWRIGHT_IGNORE_PROXY", default=False):
        return True
    return _env_flag("LLM_IGNORE_PROXY", default=False)


def _playwright_proxy_config() -> dict[str, str] | None:
    """Собрать proxy-конфиг для Chromium из env.

    Приоритет:
    1. Явные ``EIDOS_PLAYWRIGHT_PROXY_*``
    2. ``HTTPS_PROXY`` / ``HTTP_PROXY`` и ``NO_PROXY`` если direct-режим не включён.
    """
    server = _first_env("EIDOS_PLAYWRIGHT_PROXY_SERVER")
    bypass = _first_env("EIDOS_PLAYWRIGHT_PROXY_BYPASS")
    username = _first_env("EIDOS_PLAYWRIGHT_PROXY_USERNAME")
    password = _first_env("EIDOS_PLAYWRIGHT_PROXY_PASSWORD")

    if not server and not _playwright_ignore_proxy():
        server = _first_env("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
        if not bypass:
            bypass = _first_env("NO_PROXY", "no_proxy")

    if not server:
        return None

    proxy: dict[str, str] = {"server": server}
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    if bypass:
        proxy["bypass"] = bypass
    return proxy


def _proxy_status_text(proxy: dict[str, str] | None) -> str:
    if proxy is None:
        return "proxy: off"
    server = str(proxy.get("server", "")).strip()
    if not server:
        return "proxy: on"
    parsed = urlparse(server)
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return f"proxy: {parsed.scheme}://{host}"
    return "proxy: on"


def _browser_process_env(*, strip_proxy: bool) -> dict[str, str] | None:
    """Подготовить env для Chromium process.

    При ``strip_proxy=True`` удаляем proxy-переменные, чтобы Chromium не
    наследовал прокси обходным путём через среду запуска.
    """
    if not strip_proxy:
        return None
    env = dict(os.environ)
    for key in _PROXY_ENV_KEYS:
        env.pop(key, None)
    return env


def _require_enabled() -> None:
    if not playwright_tool_enabled():
        raise RuntimeError(
            "Playwright-инструменты выключены (EIDOS_PLAYWRIGHT=0/false/no/off)."
        )


def _require_session() -> BrowserSession:
    if _BROWSER_SESSION is None:
        raise RuntimeError("Браузер не открыт: сначала вызовите browser_open")
    return _BROWSER_SESSION


def close_browser_session() -> str:
    """Закрыть текущую Playwright-сессию, если она есть."""
    global _BROWSER_SESSION
    session = _BROWSER_SESSION
    _BROWSER_SESSION = None
    if session is None:
        return "browser: already closed"

    errors: list[str] = []
    context = getattr(session, "context", None)
    driver = getattr(session, "driver", None)
    browser = getattr(session, "browser", None)

    # Playwright sync API сам корректно гасит browser-процессы через driver.stop().
    # При shutdown/atexit прямой browser.close() иногда успевает породить async-task,
    # которая затем шумит "Task exception was never retrieved" после разрыва driver.
    if context is not None:
        try:
            close = getattr(context, "close", None)
            if callable(close):
                close()
        except BaseException as exc:
            errors.append(f"context: {exc}")

    if driver is not None:
        try:
            stop = getattr(driver, "stop", None)
            if callable(stop):
                stop()
        except BaseException as exc:
            errors.append(f"driver: {exc}")
    elif browser is not None:
        try:
            close = getattr(browser, "close", None)
            if callable(close):
                close()
        except BaseException as exc:
            errors.append(f"browser: {exc}")
    if errors:
        return "browser: closed with warnings (" + "; ".join(errors) + ")"
    return "browser: closed"


atexit.register(close_browser_session)


def browser_open(args: dict[str, Any]) -> str:
    """Открыть новый Chromium context/page.

    Args:
        args: Словарь аргументов инструмента.

    Returns:
        Краткое описание сессии.
    """
    global _BROWSER_SESSION
    _require_enabled()
    if _BROWSER_SESSION is not None:
        close_browser_session()

    sync_playwright = _load_sync_playwright()
    width = _int_arg(
        args.get("viewport_width"),
        default=_DEFAULT_VIEWPORT_WIDTH,
        min_value=320,
        max_value=3840,
    )
    height = _int_arg(
        args.get("viewport_height"),
        default=_DEFAULT_VIEWPORT_HEIGHT,
        min_value=240,
        max_value=2160,
    )
    headless = _bool_arg(args.get("headless"), default=True)
    ignore_https_errors = _bool_arg(args.get("ignore_https_errors"), default=False)
    user_agent = _playwright_user_agent(args)
    proxy = _playwright_proxy_config()
    ignore_proxy = proxy is None and _playwright_ignore_proxy()

    driver = sync_playwright().start()
    try:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        launch_args: list[str] = []
        if proxy is not None:
            launch_kwargs["proxy"] = proxy
        if ignore_proxy:
            launch_args.append("--no-proxy-server")
        if launch_args:
            launch_kwargs["args"] = launch_args
        browser_env = _browser_process_env(strip_proxy=(proxy is not None or ignore_proxy))
        if browser_env is not None:
            launch_kwargs["env"] = browser_env
        browser = driver.chromium.launch(**launch_kwargs)
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": width, "height": height},
            "ignore_https_errors": ignore_https_errors,
        }
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        context = browser.new_context(
            **context_kwargs,
        )
        page = context.new_page()
    except Exception as exc:
        try:
            driver.stop()
        except Exception:
            pass
        raise _normalize_playwright_error(exc) from exc
    _BROWSER_SESSION = BrowserSession(
        driver=driver,
        browser=browser,
        context=context,
        page=page,
        headless=headless,
        user_agent=user_agent,
    )

    url = str(args.get("url", "") or "").strip()
    if url:
        try:
            browser_navigate({"url": url, "timeout_ms": args.get("timeout_ms")})
        except Exception:
            close_browser_session()
            raise

    return _session_summary(
        f"browser: opened chromium (headless={str(headless).lower()})",
        page,
        extra="\n".join(
            part
            for part in (
                _proxy_status_text(proxy if not ignore_proxy else None),
                f"user_agent: {user_agent}" if user_agent else "",
            )
            if part
        ),
    )


def browser_navigate(args: dict[str, Any]) -> str:
    """Открыть URL в текущей вкладке."""
    session = _require_session()
    safe_url = _sanitize_url(str(args.get("url", "") or ""))
    wait_until = str(args.get("wait_until", "domcontentloaded") or "domcontentloaded")
    if wait_until not in ("load", "domcontentloaded", "commit", "networkidle"):
        wait_until = "domcontentloaded"
    try:
        response = session.page.goto(
            safe_url,
            wait_until=wait_until,
            timeout=_browser_timeout_ms(args),
        )
    except Exception as exc:
        shot = _save_navigation_error_screenshot(session.page, args)
        raise RuntimeError(
            _navigation_error_message(exc, session.page, safe_url, shot)
        ) from exc
    status = getattr(response, "status", None)
    extra = f"status: {status}" if status is not None else "status: -"
    return _session_summary("browser: navigated", session.page, extra=extra)


def browser_snapshot(args: dict[str, Any]) -> str:
    """Снять текстовый snapshot страницы или выбранного элемента."""
    session = _require_session()
    max_chars = _int_arg(
        args.get("max_chars"),
        default=_DEFAULT_SNAPSHOT_CHARS,
        min_value=200,
        max_value=120_000,
    )
    selector = str(args.get("selector", "") or "").strip()
    timeout_ms = _browser_timeout_ms(args)
    if selector:
        text = str(session.page.locator(selector).first.inner_text(timeout=timeout_ms)).strip()
    else:
        text = str(session.page.locator("body").first.inner_text(timeout=timeout_ms)).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    header = _session_summary("browser: snapshot", session.page)
    if selector:
        header += f"\nselector: {selector}"
    return f"{header}\n---\n{text}"


def browser_click(args: dict[str, Any]) -> str:
    """Кликнуть по элементу по CSS-селектору."""
    session = _require_session()
    selector = str(args.get("selector", "") or "").strip()
    if not selector:
        raise ValueError("параметр selector обязателен")
    session.page.locator(selector).first.click(timeout=_browser_timeout_ms(args))
    return _session_summary("browser: clicked", session.page, extra=f"selector: {selector}")


def browser_fill(args: dict[str, Any]) -> str:
    """Заполнить input/textarea по CSS-селектору."""
    session = _require_session()
    selector = str(args.get("selector", "") or "").strip()
    if not selector:
        raise ValueError("параметр selector обязателен")
    text = str(args.get("text", "") or "")
    session.page.locator(selector).first.fill(text, timeout=_browser_timeout_ms(args))
    return _session_summary(
        "browser: filled",
        session.page,
        extra=f"selector: {selector}\ntext_len: {len(text)}",
    )


def browser_press(args: dict[str, Any]) -> str:
    """Послать клавишу элементу по CSS-селектору."""
    session = _require_session()
    selector = str(args.get("selector", "") or "").strip()
    key = str(args.get("key", "") or "").strip()
    if not selector:
        raise ValueError("параметр selector обязателен")
    if not key:
        raise ValueError("параметр key обязателен")
    session.page.locator(selector).first.press(key, timeout=_browser_timeout_ms(args))
    return _session_summary(
        "browser: pressed",
        session.page,
        extra=f"selector: {selector}\nkey: {key}",
    )


def _sanitize_screenshot_filename(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.strip())[:120].strip("._")
    if not safe:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = f"browser-{stamp}.png"
    if not safe.lower().endswith(".png"):
        safe += ".png"
    return safe


def _error_screenshot_enabled(args: dict[str, Any]) -> bool:
    value = args.get("save_error_screenshot")
    if value is None:
        return _env_flag("EIDOS_PLAYWRIGHT_ERROR_SCREENSHOT", default=True)
    return _bool_arg(value, default=True)


def _save_navigation_error_screenshot(page: Any, args: dict[str, Any]) -> Path | None:
    if not _error_screenshot_enabled(args):
        return None
    name = str(args.get("error_screenshot_name", "") or "").strip()
    if not name:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"browser-nav-error-{stamp}.png"
    filename = _sanitize_screenshot_filename(name)
    path = _browser_screenshots_dir() / filename
    try:
        page.screenshot(
            path=str(path),
            full_page=True,
            timeout=_browser_timeout_ms(args),
        )
    except Exception:
        return None
    return path


def _navigation_error_message(
    exc: Exception,
    page: Any,
    target_url: str,
    screenshot_path: Path | None,
) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lines = [
        "browser_navigate failed",
        f"target_url: {target_url}",
        f"current_url: {_page_url(page) or '-'}",
        f"title: {_page_title(page) or '-'}",
        f"error: {text}",
    ]
    if screenshot_path is not None:
        lines.append(f"screenshot: {screenshot_path}")
    if "ERR_CONNECTION_RESET" in text:
        lines.append(
            "hint: сайт сбрасывает соединение; попробуйте другой user_agent и/или "
            "headless=false."
        )
    return "\n".join(lines)


def browser_screenshot(args: dict[str, Any]) -> str:
    """Сохранить PNG-скриншот текущей страницы."""
    session = _require_session()
    filename = _sanitize_screenshot_filename(str(args.get("filename", "") or ""))
    path = _browser_screenshots_dir() / filename
    full_page = _bool_arg(args.get("full_page"), default=True)
    session.page.screenshot(path=str(path), full_page=full_page, timeout=_browser_timeout_ms(args))
    return _session_summary(
        "browser: screenshot saved",
        session.page,
        extra=f"path: {path}",
    )


def execute_browser_tool(name: str, args: dict[str, Any]) -> str:
    """Выполнить один Playwright-инструмент по имени.

    Args:
        name: Имя инструмента.
        args: JSON-аргументы, уже распарсенные в словарь.

    Returns:
        Текстовый результат, пригодный для role=tool.

    Raises:
        ValueError: Если имя инструмента неизвестно.
    """
    if name == "browser_open":
        return browser_open(args)
    if name == "browser_close":
        return close_browser_session()
    if name == "browser_navigate":
        return browser_navigate(args)
    if name == "browser_snapshot":
        return browser_snapshot(args)
    if name == "browser_click":
        return browser_click(args)
    if name == "browser_fill":
        return browser_fill(args)
    if name == "browser_press":
        return browser_press(args)
    if name == "browser_screenshot":
        return browser_screenshot(args)
    raise ValueError(f"Неизвестный Playwright-инструмент: {name}")


def playwright_tool_specs() -> list[dict[str, Any]]:
    """OpenAI-compatible схемы инструментов для Playwright-MVP."""
    return [
        {
            "type": "function",
            "function": {
                "name": "browser_open",
                "description": (
                    "Открыть новый Chromium browser context для агентных действий. "
                    "Вызывать один раз перед navigate/click/fill/snapshot. "
                    "Прокси задаётся через EIDOS_PLAYWRIGHT_PROXY_* или HTTPS_PROXY. "
                    "Для прямого выхода без proxy используйте EIDOS_PLAYWRIGHT_IGNORE_PROXY=1. "
                    "Можно задать user_agent и headless=false для сложных сайтов."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Опциональный начальный URL."},
                        "headless": {
                            "type": "boolean",
                            "description": "По умолчанию true; false полезно для антибот-сайтов.",
                        },
                        "viewport_width": {"type": "integer"},
                        "viewport_height": {"type": "integer"},
                        "user_agent": {
                            "type": "string",
                            "description": "Опциональный UA для browser context.",
                        },
                        "ignore_https_errors": {"type": "boolean"},
                        "timeout_ms": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_close",
                "description": "Закрыть активную Playwright-сессию и освободить ресурсы.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "description": (
                    "Перейти по URL в текущей вкладке. При ошибке может сохранить "
                    "автоматический screenshot и вернуть расширенную диагностику."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Полный http/https URL."},
                        "wait_until": {
                            "type": "string",
                            "description": "load | domcontentloaded | commit | networkidle",
                        },
                        "timeout_ms": {"type": "integer"},
                        "save_error_screenshot": {
                            "type": "boolean",
                            "description": "По умолчанию true.",
                        },
                        "error_screenshot_name": {
                            "type": "string",
                            "description": "Опциональное имя PNG при ошибке.",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_snapshot",
                "description": (
                    "Вернуть текстовый snapshot страницы или элемента по CSS-селектору. "
                    "Полезно после navigate/click/fill."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string", "description": "Опциональный CSS-селектор."},
                        "max_chars": {"type": "integer"},
                        "timeout_ms": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_click",
                "description": "Кликнуть по элементу по CSS-селектору.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "timeout_ms": {"type": "integer"},
                    },
                    "required": ["selector"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_fill",
                "description": "Заполнить поле по CSS-селектору.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "text": {"type": "string"},
                        "timeout_ms": {"type": "integer"},
                    },
                    "required": ["selector", "text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_press",
                "description": "Послать клавишу элементу по CSS-селектору.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "key": {"type": "string"},
                        "timeout_ms": {"type": "integer"},
                    },
                    "required": ["selector", "key"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "browser_screenshot",
                "description": "Сделать PNG-скриншот текущей страницы и вернуть путь к файлу.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string"},
                        "full_page": {"type": "boolean"},
                        "timeout_ms": {"type": "integer"},
                    },
                },
            },
        },
    ]
