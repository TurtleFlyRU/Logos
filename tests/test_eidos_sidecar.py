"""Smoke-тесты JSON-lines sidecar для Rust ``eidos chat``."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "kernel" / "eidos_sidecar.py"


def _call(
    req: dict,
    *,
    env_extra: dict[str, str] | None = None,
    env_unset: tuple[str, ...] = (),
) -> dict:
    proc_env = {**dict(**__import__("os").environ), "PYTHONPATH": str(REPO)}
    for key in env_unset:
        proc_env.pop(key, None)
    if env_extra:
        proc_env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(req, ensure_ascii=False) + "\n",
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=proc_env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    line = proc.stdout.strip().splitlines()[-1]
    out = json.loads(line)
    assert out.get("ok") is True, out.get("error")
    return out["result"]


def test_sidecar_ping() -> None:
    assert _call({"op": "ping"}) == {}


def test_sidecar_startup_reports() -> None:
    r = _call({"op": "startup_reports", "mode": "full"})
    assert "env" in r
    assert "budget" in r
    assert "EIDOS_" in r["env"] or "LLM_" in r["env"]


def test_sidecar_tools_allowed_identity() -> None:
    r = _call({"op": "tools_allowed", "line": "как меня зовут?"})
    assert r.get("allowed") is False


def test_sidecar_pipeline_help() -> None:
    r = _call({"op": "pipeline_line", "session_id": "00000000-0000-0000-0000-000000000001", "line": "/pipeline help", "stub": True})
    assert r.get("action") == "help"
    assert "research" in r.get("text", "")


def test_sidecar_context_metrics() -> None:
    sid = "00000000-0000-0000-0000-000000000099"
    r = _call({"op": "context_metrics", "session_id": sid})
    metrics = r.get("metrics") or {}
    assert "total_chars" in metrics
    assert int(metrics.get("approx_prompt_tokens", 0)) >= 0
    assert "layers" in metrics
    assert "[budget]" in (r.get("budget_report") or "")


def test_sidecar_active_memory_block() -> None:
    r = _call(
        {
            "op": "active_memory_block",
            "session_id": "00000000-0000-0000-0000-000000000099",
            "max_chars": 800,
        }
    )
    assert "text" in r
    assert isinstance(r["text"], str)


def test_sidecar_semantic_principles_block() -> None:
    r = _call(
        {
            "op": "semantic_principles_block",
            "limit": 3,
            "min_confidence": 0.5,
        }
    )
    assert "text" in r
    assert isinstance(r["text"], str)


def test_sidecar_playwright_tool_specs_disabled() -> None:
    r = _call({"op": "playwright_tool_specs"}, env_extra={"EIDOS_PLAYWRIGHT": "0"})
    assert r.get("specs") == []


def test_sidecar_playwright_tool_specs_on_by_default() -> None:
    r = _call({"op": "playwright_tool_specs"}, env_unset=("EIDOS_PLAYWRIGHT",))
    specs = r.get("specs") or []
    assert isinstance(specs, list)
    assert len(specs) >= 1
    first = specs[0]
    assert first.get("type") == "function"
    assert first.get("function", {}).get("name", "").startswith("browser_")
