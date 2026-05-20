"""Суррогаты в тексте не должны ломать JSON/HTTP транспорт CLI → LLM."""

from __future__ import annotations

import json

import pytest

from kernel.utils import sanitize_for_json_transport, sanitize_unicode_text


def test_sanitize_unicode_text_replaces_surrogate() -> None:
    bad = "pre\udcd1post"
    out = sanitize_unicode_text(bad)
    # CPython может подставить ``?`` (U+003F), не U+FFFD; главное — валидный UTF-8.
    assert "\udcd1" not in out
    out.encode("utf-8")
    assert out.startswith("pre") and out.endswith("post") and len(out) >= len(bad) - 1


def test_sanitize_for_json_transport_roundtrip() -> None:
    payload = {
        "model": "x",
        "messages": [
            {"role": "user", "content": "a\udcd1b"},
            {"role": "assistant", "content": "ok"},
        ],
        "nested": [{"k": "\udc00"}],
    }
    clean = sanitize_for_json_transport(payload)
    json.dumps(clean, ensure_ascii=False).encode("utf-8")

@pytest.mark.parametrize("obj", [None, 1, 1.5, True])
def test_sanitize_passthroughScalars(obj: object) -> None:
    assert sanitize_for_json_transport(obj) is obj


def test_sanitize_dict_str_keys() -> None:
    inner = {"norm": 1}
    # редкий случай ключа-строки с суррогатом
    key = "k\udcd1"
    data = {key: inner}
    clean = sanitize_for_json_transport(data)
    assert list(clean.keys())[0] == sanitize_unicode_text(key)
