"""OpenAI-compatible chat completions (DeepSeek, локальные прокси и т.д.).

Переменные окружения:
- LLM_API_KEY / DEEPSEEK_API_KEY, LLM_BASE_URL, LLM_MODEL.
- LLM_TIMEOUT_SEC — таймаут чтения (сек), по умолчанию 120.
- LLM_TRUST_ENV — ``1``/``true``/``yes``: подхватывать HTTP_PROXY и системный прокси.
  По умолчанию **не** подхватывает — иначе часто «вечное» ожидание после «Запрос к модели…»
  из‑за прокси в окружении, через который этот API не ходит.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


class LLMConfigError(RuntimeError):
    """Нет ключа или некорректная конфигурация для вызова API."""


def _http_trust_env() -> bool:
    v = os.environ.get("LLM_TRUST_ENV", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def llm_settings() -> tuple[str, str, str]:
    api_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    ).strip()
    base = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip()
    return api_key, base, model


def _read_timeout_sec() -> float:
    raw = os.environ.get("LLM_TIMEOUT_SEC", "").strip()
    if not raw:
        return 120.0
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 120.0


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
    connect_sec = min(30.0, read_sec)

    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages}

    close_client = False
    if client is None:
        timeout_cfg = httpx.Timeout(
            read_sec,
            connect=connect_sec,
            read=read_sec,
            pool=connect_sec,
        )
        client = httpx.Client(timeout=timeout_cfg, trust_env=_http_trust_env())
        close_client = True
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
        if close_client:
            client.close()
