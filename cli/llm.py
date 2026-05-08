"""OpenAI-compatible chat completions (DeepSeek, локальные прокси и т.д.).

Переменные окружения:
- LLM_API_KEY / DEEPSEEK_API_KEY, LLM_BASE_URL, LLM_MODEL.
- LLM_TIMEOUT_SEC — таймаут **чтения** ответа (сек), по умолчанию 120.
- LLM_IGNORE_PROXY — ``1``/``true``: не подхватывать HTTP(S)_PROXY (trust_env=False).
- LLM_DEBUG — если задан: перед запросом печатается URL и модель (без ключа).
- LLM_PROGRESS — ``0``/``false``: не печатать строки HTTP → / ← (по умолчанию включено).
"""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

_CONNECT_SEC = 30.0
_POOL_WRITE_SEC = 30.0

# Этапы для heartbeat (факт «на какой стадии обмена мы зависли»).
_PHASE_PRE = "pre_request"
_PHASE_AWAIT_HEAD = "await_response_head"
_PHASE_READ_BODY = "read_body"
_WAIT_HINT = {
    _PHASE_PRE: "до отправки запроса (соединение, TLS)",
    _PHASE_AWAIT_HEAD: "после отправки: статус и заголовки ответа",
    _PHASE_READ_BODY: "после статуса: тело ответа",
}


class LLMConfigError(RuntimeError):
    """Нет ключа или некорректная конфигурация для вызова API."""


def _http_trust_env() -> bool:
    """По умолчанию True (как httpx); отключить прокси из env — LLM_IGNORE_PROXY."""
    v = os.environ.get("LLM_IGNORE_PROXY", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return False
    return True


def llm_settings() -> tuple[str, str, str]:
    api_key = (
        os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    ).strip()
    base = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip()
    return api_key, base, model


def _progress_print_enabled() -> bool:
    v = os.environ.get("LLM_PROGRESS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _read_timeout_sec() -> float:
    raw = os.environ.get("LLM_TIMEOUT_SEC", "").strip()
    if not raw:
        return 120.0
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


def format_llm_pending_banner() -> str:
    """Одна строка до HTTP: куда идём и лимит чтения (без ключа и полного URL)."""
    _, base, model = llm_settings()
    parsed = urlparse(base)
    host = (
        parsed.netloc
        or base.replace("https://", "").replace("http://", "").split("/")[0]
    )
    rs = _read_timeout_sec()
    proxy_env = "да" if _http_trust_env() else "нет"
    return (
        f"[eidos] LLM {host} · модель {model} · таймаут чтения {rs:.0f} с · "
        f"прокси из env: {proxy_env}"
    )


def _phase_hooks(phase: dict[str, str]) -> dict[str, list]:
    show = _progress_print_enabled()

    def on_request(request: httpx.Request) -> None:
        phase["stage"] = _PHASE_AWAIT_HEAD
        if show:
            path = request.url.path or "/"
            print(f"[eidos] HTTP → {request.method} {path}", flush=True)

    def on_response(response: httpx.Response) -> None:
        phase["stage"] = _PHASE_READ_BODY
        if show:
            print(
                f"[eidos] HTTP ← {response.status_code} {response.reason_phrase}",
                flush=True,
            )

    return {"request": [on_request], "response": [on_response]}


def chat_completions(
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
) -> str:
    """POST /chat/completions; возвращает текст из первого choice."""
    api_key, base, model = llm_settings()
    if not api_key:
        raise LLMConfigError(
            "Задайте LLM_API_KEY или DEEPSEEK_API_KEY в окружении "
            "(опционально LLM_BASE_URL, LLM_MODEL)."
        )

    read_sec = timeout if timeout is not None else _read_timeout_sec()

    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    if os.environ.get("LLM_DEBUG", "").strip():
        print(f"[eidos] LLM_DEBUG POST {url} model={model}", flush=True)

    stop_hb = threading.Event()
    close_client = False

    if client is None:
        phase: dict[str, str] = {"stage": _PHASE_PRE}
        timeout_cfg = httpx.Timeout(
            read_sec,
            connect=_CONNECT_SEC,
            read=read_sec,
            write=_POOL_WRITE_SEC,
            pool=_POOL_WRITE_SEC,
        )
        client = httpx.Client(
            timeout=timeout_cfg,
            trust_env=_http_trust_env(),
            http2=False,
            event_hooks=_phase_hooks(phase),
        )
        close_client = True

        def _heartbeat() -> None:
            delays = [5.0] + [12.0] * 500
            for wait_sec in delays:
                if stop_hb.wait(wait_sec):
                    return
                stage = phase.get("stage", _PHASE_PRE)
                hint = _WAIT_HINT.get(stage, "сеть")
                print(f"[eidos] Ожидание: {hint}.", flush=True)

        threading.Thread(target=_heartbeat, daemon=True).start()

    try:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            detail = repr(data)[:500]
            raise LLMConfigError(f"Пустой choices в ответе API: {detail}")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            detail = repr(data)[:500]
            raise LLMConfigError(f"Нет message.content в ответе: {detail}")
        return str(content).strip()
    finally:
        stop_hb.set()
        if close_client:
            client.close()
