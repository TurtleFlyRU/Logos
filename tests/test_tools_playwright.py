"""Тесты Playwright-MVP инструментов для CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import kernel.config as kernel_config


def test_playwright_env_flag_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIDOS_PLAYWRIGHT", raising=False)
    from cli.browser_tools import playwright_tool_enabled

    assert playwright_tool_enabled() is True


def test_playwright_env_flag_explicit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "0")
    from cli.browser_tools import playwright_tool_enabled

    assert playwright_tool_enabled() is False


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    def click(self, timeout: int) -> None:
        self._page.actions.append(("click", self._selector, timeout))

    def fill(self, text: str, timeout: int) -> None:
        self._page.actions.append(("fill", self._selector, timeout))
        self._page.fields[self._selector] = text

    def press(self, key: str, timeout: int) -> None:
        self._page.actions.append(("press", self._selector, timeout))
        self._page.last_key = key

    def inner_text(self, timeout: int) -> str:
        self._page.actions.append(("inner_text", self._selector, timeout))
        if self._selector == "body":
            return self._page.body_text
        return self._page.fields.get(self._selector, "")


class _FakePage:
    def __init__(self) -> None:
        self.url = ""
        self._title = ""
        self.body_text = ""
        self.fields: dict[str, str] = {}
        self.actions: list[tuple[str, str, int]] = []
        self.last_key = ""

    def goto(self, url: str, wait_until: str, timeout: int) -> _FakeResponse:
        self.url = url
        self._title = f"title for {url}"
        self.body_text = f"body for {url} ({wait_until}, {timeout})"
        return _FakeResponse(200)

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def screenshot(self, path: str, full_page: bool, timeout: int) -> None:
        Path(path).write_bytes(f"png:{full_page}:{timeout}".encode("utf-8"))


class _FakeContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.closed = False
        self.last_new_context_kwargs: dict[str, object] = {}

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.context = _FakeContext()
        self.closed = False

    def new_context(self, **kwargs: object) -> _FakeContext:
        self.context.last_new_context_kwargs = dict(kwargs)
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.last_launch_kwargs: dict[str, object] = {}

    def launch(self, **kwargs: object) -> _FakeBrowser:
        self.last_launch_kwargs = dict(kwargs)
        return self.browser


class _BrokenChromium:
    def launch(self, **kwargs: object) -> _FakeBrowser:
        _ = kwargs
        raise RuntimeError("BrowserType.launch: Executable doesn't exist")


class _FakeDriver:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _InterruptingCloser:
    def __init__(self) -> None:
        self.called = False

    def close(self) -> None:
        self.called = True
        raise KeyboardInterrupt()


class _InterruptingStopper:
    def __init__(self) -> None:
        self.called = False

    def stop(self) -> None:
        self.called = True
        raise KeyboardInterrupt()


class _ForbiddenCloser:
    def close(self) -> None:
        raise AssertionError("browser.close should not be called when driver.stop is available")


class _FakeSyncPlaywrightFactory:
    def __init__(self) -> None:
        self.last_driver: _FakeDriver | None = None

    def __call__(self) -> "_FakeSyncPlaywrightFactory":
        return self

    def start(self) -> _FakeDriver:
        self.last_driver = _FakeDriver()
        return self.last_driver


class _BrokenSyncPlaywrightFactory:
    def __call__(self) -> "_BrokenSyncPlaywrightFactory":
        return self

    def start(self) -> _FakeDriver:
        driver = _FakeDriver()
        driver.chromium = _BrokenChromium()
        return driver


def test_builtin_tools_include_playwright_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EIDOS_PLAYWRIGHT", raising=False)
    from cli.tools import builtin_tool_specs

    names = [spec["function"]["name"] for spec in builtin_tool_specs()]
    assert "browser_open" in names
    assert "browser_snapshot" in names


def test_builtin_tools_exclude_playwright_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "0")
    from cli.tools import builtin_tool_specs

    names = [spec["function"]["name"] for spec in builtin_tool_specs()]
    assert "browser_open" not in names


def test_playwright_tool_flow_via_execute_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setattr(kernel_config, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        "cli.browser_tools._load_sync_playwright",
        lambda: _FakeSyncPlaywrightFactory(),
    )

    from cli.browser_tools import close_browser_session
    from cli.tools import execute_tool

    opened = execute_tool("browser_open", '{"headless": true}', registry=None)
    assert "opened chromium" in opened

    navigated = execute_tool(
        "browser_navigate",
        '{"url":"https://example.org/demo","wait_until":"load"}',
        registry=None,
    )
    assert "https://example.org/demo" in navigated
    assert "status: 200" in navigated

    filled = execute_tool(
        "browser_fill",
        '{"selector":"input[name=q]","text":"Logos"}',
        registry=None,
    )
    assert "text_len: 5" in filled

    pressed = execute_tool(
        "browser_press",
        '{"selector":"input[name=q]","key":"Enter"}',
        registry=None,
    )
    assert "Enter" in pressed

    snapshot = execute_tool(
        "browser_snapshot",
        '{"selector":"body","max_chars":1000}',
        registry=None,
    )
    assert "body for https://example.org/demo" in snapshot

    shot = execute_tool(
        "browser_screenshot",
        '{"filename":"demo-shot","full_page":false}',
        registry=None,
    )
    assert "demo-shot.png" in shot
    assert (tmp_path / "browser" / "screenshots" / "demo-shot.png").is_file()

    closed = close_browser_session()
    assert "closed" in closed


def test_playwright_tool_open_accepts_user_agent_and_headed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    from cli.tools import execute_tool

    body = execute_tool(
        "browser_open",
        '{"headless": false, "user_agent": "Mozilla/5.0 LogosTest"}',
        registry=None,
    )
    assert "headless=false" in body
    assert "Mozilla/5.0 LogosTest" in body
    assert factory.last_driver is not None
    launch_kwargs = factory.last_driver.chromium.last_launch_kwargs
    assert launch_kwargs["headless"] is False
    ctx_kwargs = factory.last_driver.chromium.browser.context.last_new_context_kwargs
    assert ctx_kwargs["user_agent"] == "Mozilla/5.0 LogosTest"


def test_close_browser_session_swallows_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cli.browser_tools as bt

    context = _InterruptingCloser()
    browser = _InterruptingCloser()
    driver = _InterruptingStopper()
    monkeypatch.setattr(
        bt,
        "_BROWSER_SESSION",
        bt.BrowserSession(
            driver=driver,
            browser=browser,
            context=context,
            page=None,
            headless=True,
            user_agent="",
        ),
    )

    text = bt.close_browser_session()
    assert "closed with warnings" in text
    assert "KeyboardInterrupt" in text or "context:" in text
    assert context.called is True
    assert browser.called is False
    assert driver.called is True
    assert bt._BROWSER_SESSION is None


def test_close_browser_session_prefers_driver_stop_over_browser_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cli.browser_tools as bt

    context = _FakeContext()
    browser = _ForbiddenCloser()
    driver = _FakeDriver()
    monkeypatch.setattr(
        bt,
        "_BROWSER_SESSION",
        bt.BrowserSession(
            driver=driver,
            browser=browser,
            context=context,
            page=None,
            headless=True,
            user_agent="",
        ),
    )

    text = bt.close_browser_session()
    assert text == "browser: closed"
    assert context.closed is True
    assert driver.stopped is True
    assert bt._BROWSER_SESSION is None


def test_playwright_tool_blocks_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setattr(
        "cli.browser_tools._load_sync_playwright",
        lambda: _FakeSyncPlaywrightFactory(),
    )

    from cli.tools import execute_tool

    raw = execute_tool(
        "browser_open",
        '{"url":"http://127.0.0.1:3000/"}',
        registry=None,
    )
    payload = json.loads(raw)
    assert "error" in payload
    assert "локаль" in payload["error"] or "приват" in payload["error"]


def test_playwright_tool_navigate_returns_diagnostic_on_reset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setattr(kernel_config, "DATA_ROOT", tmp_path)
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    import cli.browser_tools as bt
    from cli.tools import execute_tool

    _ = execute_tool("browser_open", "{}", registry=None)
    assert bt._BROWSER_SESSION is not None

    def boom(url: str, wait_until: str, timeout: int) -> _FakeResponse:
        _ = (url, wait_until, timeout)
        raise RuntimeError("net::ERR_CONNECTION_RESET at https://reg.ru/")

    bt._BROWSER_SESSION.page.goto = boom

    raw = execute_tool(
        "browser_navigate",
        '{"url":"https://reg.ru","error_screenshot_name":"reg-ru-error"}',
        registry=None,
    )
    payload = json.loads(raw)
    assert "error" in payload
    text = payload["error"]
    assert "browser_navigate failed" in text
    assert "ERR_CONNECTION_RESET" in text
    assert "headless=false" in text or "user_agent" in text or "hint:" in text
    assert "reg-ru-error.png" in text
    assert (tmp_path / "browser" / "screenshots" / "reg-ru-error.png").is_file()
    bt.close_browser_session()


def test_playwright_tool_reports_missing_browser_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setattr(
        "cli.browser_tools._load_sync_playwright",
        lambda: _BrokenSyncPlaywrightFactory(),
    )

    from cli.tools import execute_tool

    raw = execute_tool("browser_open", "{}", registry=None)
    payload = json.loads(raw)
    assert "error" in payload
    assert "playwright install chromium" in payload["error"]


def test_playwright_tool_passes_explicit_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_PROXY_SERVER", "http://proxy.example:8080")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_PROXY_USERNAME", "u1")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_PROXY_PASSWORD", "p1")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_PROXY_BYPASS", "localhost,127.0.0.1")
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    from cli.tools import execute_tool

    body = execute_tool("browser_open", "{}", registry=None)
    assert "proxy: http://proxy.example:8080" in body
    assert factory.last_driver is not None
    launch_kwargs = factory.last_driver.chromium.last_launch_kwargs
    assert launch_kwargs["headless"] is True
    assert launch_kwargs["proxy"] == {
        "server": "http://proxy.example:8080",
        "username": "u1",
        "password": "p1",
        "bypass": "localhost,127.0.0.1",
    }
    assert "args" not in launch_kwargs
    assert "env" in launch_kwargs
    env = launch_kwargs["env"]
    assert isinstance(env, dict)
    assert "HTTPS_PROXY" not in env
    assert "HTTP_PROXY" not in env


def test_playwright_tool_uses_https_proxy_env_when_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,.corp")
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    from cli.tools import execute_tool

    body = execute_tool("browser_open", "{}", registry=None)
    assert "proxy: http://corp-proxy:3128" in body
    assert factory.last_driver is not None
    assert factory.last_driver.chromium.last_launch_kwargs["proxy"] == {
        "server": "http://corp-proxy:3128",
        "bypass": "localhost,.corp",
    }
    env = factory.last_driver.chromium.last_launch_kwargs["env"]
    assert isinstance(env, dict)
    assert "HTTPS_PROXY" not in env


def test_playwright_tool_ignores_env_proxy_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    monkeypatch.setenv("LLM_IGNORE_PROXY", "1")
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    from cli.tools import execute_tool

    body = execute_tool("browser_open", "{}", registry=None)
    assert "proxy: off" in body
    assert factory.last_driver is not None
    launch_kwargs = factory.last_driver.chromium.last_launch_kwargs
    assert "proxy" not in launch_kwargs
    assert launch_kwargs["args"] == ["--no-proxy-server"]
    env = launch_kwargs["env"]
    assert isinstance(env, dict)
    assert "HTTPS_PROXY" not in env
    assert "HTTP_PROXY" not in env


def test_playwright_tool_explicit_ignore_proxy_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EIDOS_PLAYWRIGHT", "1")
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:3128")
    monkeypatch.setenv("EIDOS_PLAYWRIGHT_IGNORE_PROXY", "1")
    factory = _FakeSyncPlaywrightFactory()
    monkeypatch.setattr("cli.browser_tools._load_sync_playwright", lambda: factory)

    from cli.tools import execute_tool

    body = execute_tool("browser_open", "{}", registry=None)
    assert "proxy: off" in body
    assert factory.last_driver is not None
    launch_kwargs = factory.last_driver.chromium.last_launch_kwargs
    assert "proxy" not in launch_kwargs
    assert launch_kwargs["args"] == ["--no-proxy-server"]
