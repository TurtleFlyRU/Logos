"""OpenAI-compatible chat completions (DeepSeek, локальные прокси и т.д.).

Переменные окружения:
- LLM_API_KEY / DEEPSEEK_API_KEY, LLM_BASE_URL, LLM_MODEL (режим без профилей).
- EIDOS_AGENT_PROFILE — имя профиля из YAML (``config/agents*.yaml``, см. ``cli/agent_backends.py``).
- EIDOS_AGENTS_CONFIG — явный путь к файлу профилей.
- LLM_TIMEOUT_SEC — таймаут **чтения** ответа (сек); при необходимости перекрывает ``read_timeout_sec`` профиля.
- LLM_IGNORE_PROXY — ``1``/``true``: не подхватывать HTTP(S)_PROXY (trust_env=False).
- LLM_DEBUG — если задан: перед запросом печатается URL и модель (без ключа).
- LLM_PROGRESS — ``0``/``false``: не печатать строки HTTP → / ← (по умолчанию включено).

Функции ``chat_completion_assistant_message`` / цикл инструментов — см. ``cli.tools``.
"""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

from cli.agent_backends import LLMRuntimeParams, get_llm_runtime_params

from kernel.utils import sanitize_for_json_transport

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


def llm_settings(*, runtime_params: LLMRuntimeParams | None = None) -> tuple[str, str, str]:
    cfg = runtime_params or get_llm_runtime_params()
    return cfg.api_key, cfg.base_url.rstrip("/"), cfg.model


def _progress_print_enabled() -> bool:
    v = os.environ.get("LLM_PROGRESS", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _read_timeout_sec(*, runtime_params: LLMRuntimeParams | None = None) -> float:
    cfg = runtime_params or get_llm_runtime_params()
    return float(cfg.read_timeout_sec)


def format_llm_pending_banner(*, runtime_params: LLMRuntimeParams | None = None) -> str:
    """Одна строка до HTTP: куда идём и лимит чтения (без ключа и полного URL)."""
    cfg = runtime_params or get_llm_runtime_params()
    base = cfg.base_url.rstrip("/")
    model = cfg.model
    parsed = urlparse(base)
    host = (
        parsed.netloc
        or base.replace("https://", "").replace("http://", "").split("/")[0]
    )
    rs = cfg.read_timeout_sec
    proxy_env = "да" if _http_trust_env() else "нет"
    prof = cfg.profile_name
    suffix = f" · профиль {prof}" if prof else ""
    return (
        f"[eidos] LLM {host}{suffix} · модель {model} · таймаут чтения {rs:.0f} с · "
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


def _chat_completion_raw_assistant_message(
    *,
    payload: dict[str, Any],
    read_sec: float,
    base: str,
    api_key: str,
    omit_authorization_header: bool = False,
    timeout: float | None,
    client: httpx.Client | None,
) -> dict[str, Any]:
    """Общий POST /chat/completions; возвращает сырой объект ``message`` первого choice."""
    url = f"{base.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not omit_authorization_header:
        headers["Authorization"] = f"Bearer {api_key}"

    if os.environ.get("LLM_DEBUG", "").strip():
        print(
            f"[eidos] LLM_DEBUG POST {url} model={payload.get('model')}",
            flush=True,
        )

    payload = sanitize_for_json_transport(payload)

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
        if not isinstance(msg, dict):
            detail = repr(data)[:500]
            raise LLMConfigError(f"Некорректный message в ответе: {detail}")
        from cli.llm_sanitize import normalize_assistant_message

        return normalize_assistant_message(msg)
    finally:
        stop_hb.set()
        if close_client:
            client.close()


def chat_completion_assistant_message(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = "auto",
    timeout: float | None = None,
    client: httpx.Client | None = None,
    runtime_params: LLMRuntimeParams | None = None,
) -> dict[str, Any]:
    """POST /chat/completions; возвращает ``message`` первого choice (текст и/или ``tool_calls``)."""
    cfg = runtime_params or get_llm_runtime_params()
    if not cfg.api_key and not cfg.omit_authorization_header:
        raise LLMConfigError(
            "Задайте LLM_API_KEY или DEEPSEEK_API_KEY в окружении "
            "(опционально LLM_BASE_URL, LLM_MODEL) либо укажите профиль через EIDOS_AGENT_PROFILE "
            "(с ключом в нужном из env см. YAML)."
        )

    api_key, base, model = cfg.api_key, cfg.base_url, cfg.model
    read_sec = timeout if timeout is not None else float(cfg.read_timeout_sec)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools is not None:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    msg = _chat_completion_raw_assistant_message(
        payload=payload,
        read_sec=read_sec,
        base=base,
        api_key=api_key,
        omit_authorization_header=cfg.omit_authorization_header,
        timeout=timeout,
        client=client,
    )
    if msg.get("tool_calls"):
        return msg
    if msg.get("content") is None:
        raise LLMConfigError(
            "В ответе API нет ни content, ни tool_calls — проверьте модель и параметры."
        )
    return msg


def chat_completions(
    messages: list[dict[str, Any]],
    *,
    timeout: float | None = None,
    client: httpx.Client | None = None,
    runtime_params: LLMRuntimeParams | None = None,
) -> str:
    """POST /chat/completions; возвращает текст из первого choice."""
    cfg = runtime_params or get_llm_runtime_params()
    if not cfg.api_key and not cfg.omit_authorization_header:
        raise LLMConfigError(
            "Задайте LLM_API_KEY или DEEPSEEK_API_KEY в окружении "
            "(опционально LLM_BASE_URL, LLM_MODEL) либо EIDOS_AGENT_PROFILE из YAML "
            "(с ключом или omit_authorization_header для локальных прокси)."
        )

    api_key, base, model = cfg.api_key, cfg.base_url, cfg.model
    read_sec = timeout if timeout is not None else float(cfg.read_timeout_sec)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    msg = _chat_completion_raw_assistant_message(
        payload=payload,
        read_sec=read_sec,
        base=base,
        api_key=api_key,
        omit_authorization_header=cfg.omit_authorization_header,
        timeout=timeout,
        client=client,
    )
    if msg.get("tool_calls"):
        raise LLMConfigError(
            "Модель вернула tool_calls — включите режим инструментов в chat (EIDOS_TOOLS=1) "
            "или используйте chat_completion_assistant_message."
        )
    content = msg.get("content")
    if content is None:
        raise LLMConfigError("Нет message.content в ответе API.")
    from cli.llm_sanitize import strip_model_channels

    return strip_model_channels(str(content))
