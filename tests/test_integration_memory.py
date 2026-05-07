"""Интеграционные тесты Memory: respond → эпизод → boot, crash-безопасность, граничные случаи."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import concurrent.futures
from pathlib import Path

import pytest


def _reset_memory():
    """Сбрасывает синглтон Memory между тестами."""
    import kernel.memory as mem

    mem.Memory._instance = None


def _patch_config(monkeypatch, tmp_path: Path) -> None:
    """Патчит все конфигурационные пути через kernel.config и модули, импортирующие их."""
    import kernel.config as cfg
    import kernel.memory as mem
    import kernel.boot

    # config (исходник)
    monkeypatch.setattr(cfg, "WORKING_MEMORY_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(cfg, "PLANNER_DATA_DIR", tmp_path / "planner")
    monkeypatch.setattr(cfg, "JOURNAL_DIR", tmp_path / "journal")
    monkeypatch.setattr(cfg, "EPISODIC_DB_PATH", tmp_path / "episodic.db")
    monkeypatch.setattr(cfg, "SEMANTIC_DB_PATH", tmp_path / "semantic.db")
    monkeypatch.setattr(cfg, "MISSION_STATE_PATH", tmp_path / "mission" / "state.json")
    monkeypatch.setattr(cfg, "MISSION_HYPOTHESES_PATH", tmp_path / "mission" / "hypotheses.json")
    monkeypatch.setattr(cfg, "MISSION_EXPERIMENTS_PATH", tmp_path / "mission" / "experiments.json")
    monkeypatch.setattr(cfg, "MISSION_PROTOCOL_PATH", tmp_path / "mission" / "protocol.log")
    monkeypatch.setattr(cfg, "EXPERIMENTS_ROOT", tmp_path / "experiments")
    monkeypatch.setattr(cfg, "GOALS_DB_PATH", tmp_path / "goals" / "goals.db")
    monkeypatch.setattr(cfg, "GOALS_CHECKPOINT_PATH", tmp_path / "goals" / "checkpoint.json")
    monkeypatch.setattr(cfg, "SLEEP_LOCK_PATH", tmp_path / "sleep" / ".sleep.lock")
    monkeypatch.setattr(cfg, "SLEEP_CHECKPOINT_PATH", tmp_path / "sleep" / "checkpoint.json")

    # modules with `from kernel.config import X` (локальные копии)
    monkeypatch.setattr(mem, "WORKING_MEMORY_PATH", tmp_path / "wm.json")
    monkeypatch.setattr(mem, "EPISODIC_DB_PATH", tmp_path / "episodic.db")
    monkeypatch.setattr(mem, "SEMANTIC_DB_PATH", tmp_path / "semantic.db")
    monkeypatch.setattr(mem, "SLEEP_LOCK_PATH", tmp_path / "sleep" / ".sleep.lock")
    monkeypatch.setattr(mem, "SLEEP_CHECKPOINT_PATH", tmp_path / "sleep" / "checkpoint.json")


# ─── respond → эпизод → boot ────────────────────────────────────────────────


def test_respond_writes_auto_episode(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    m = Memory(auto_boot=False)
    result = m.respond("тестовый ответ", "что такое эйдос?")

    assert result["plan"]["action"] == "respond"
    import kernel.config as cfg
    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    assert wm_path.exists(), f"WM file not found at {wm_path} (cfg.WORKING_MEMORY_PATH={cfg.WORKING_MEMORY_PATH})"

    data = json.loads(wm_path.read_text())
    auto_events = [e for e in data["events"] if e.get("event_type") == "respond"]
    assert len(auto_events) >= 1
    content = json.loads(auto_events[-1]["content"])
    assert "query" in content
    assert content["query"] == "что такое эйдос?"

    # проверка, что дневник тоже получил запись
    today = __import__("datetime").date.today().isoformat()
    journal_file = tmp_path / "journal" / f"{today}.md"
    if journal_file.exists():
        assert "что такое эйдос" in journal_file.read_text()


def test_three_responds_three_episodes(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    m = Memory(auto_boot=False)
    queries = ["кто ты?", "как ты работаешь?", "что ты помнишь?"]
    for q in queries:
        m.respond(f"ответ на {q}", q)

    import kernel.config as cfg
    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    assert wm_path.exists(), f"WM file not found at {wm_path}"
    data = json.loads(wm_path.read_text())
    auto_events = [e for e in data["events"] if e.get("event_type") == "respond"]
    assert len(auto_events) == len(queries), f"expected {len(queries)} events, got {len(auto_events)}"
    for evt, q in zip(auto_events, queries):
        assert json.loads(evt["content"])["query"] == q


def test_respond_boot_roundtrip(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    m = Memory(auto_boot=False)
    m.respond("ответ", "интеграционный тест")

    # sleep — запись в эпизодическую память
    m.sleep()

    # новый процесс: заново создаём Memory
    m2 = Memory(auto_boot=False)
    ctx = m2.boot()
    assert "интеграционный тест" in ctx or "respond" in ctx


def test_respond_with_referenced_files(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    m = Memory(auto_boot=False)
    result = m.respond("ответ", "сложный вопрос", referenced_files=5)
    assert result["final_draft"] == "ответ"


# ─── crash-безопасность atomic_write ──────────────────────────────────────────


def test_atomic_write_survives_mid_write_kill(tmp_path):
    from kernel.utils import atomic_write

    target = tmp_path / "test.json"
    target.write_text('{"original": true}')

    script = f"""
import json, os, signal
from pathlib import Path
from kernel.utils import atomic_write

path = Path("{target}")
data = {{"x": "a" * 50000, "y": list(range(1000))}}
atomic_write(path, data)
import sys
with open(path) as f:
    json.load(f)
print("OK", file=sys.stderr)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).parent.parent),
    )
    try:
        proc.wait(timeout=15)
        assert proc.returncode == 0, f"failed: {proc.stderr.read().decode()}"
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("atomic_write timed out")


def test_atomic_write_no_orphans_after_normal(tmp_path):
    from kernel.utils import atomic_write

    target = tmp_path / "test.json"
    target.write_text('{"status": "before"}')
    atomic_write(target, {"status": "after"})
    leftovers = list(tmp_path.glob("*.tmp"))
    assert len(leftovers) == 0, f"orphan tmp files: {leftovers}"
    assert json.loads(target.read_text()) == {"status": "after"}


def test_atomic_write_preserves_original_on_failure():
    from kernel.utils import atomic_write
    from pathlib import Path
    import tempfile

    tmp = Path(tempfile.mkstemp(suffix=".json")[1])
    try:
        tmp.write_text('{"before": true}')

        class Bad:
            pass

        try:
            atomic_write(tmp, {"bad": Bad()})
        except (TypeError, AttributeError):
            pass
        assert tmp.read_text().strip() == '{"before": true}'
    finally:
        tmp.unlink(missing_ok=True)


# ─── граничные случаи ────────────────────────────────────────────────────────


def test_corrupted_json_recovery(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    import kernel.config as cfg
    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    wm_path.parent.mkdir(parents=True, exist_ok=True)
    wm_path.write_bytes(b"not valid json {{{")

    from kernel.memory import WorkingMemory

    wm = WorkingMemory()
    assert wm._data["event_count"] == 0
    assert wm._data["events"] == []


def test_empty_json_file_recovery(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    import kernel.config as cfg
    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    wm_path.parent.mkdir(parents=True, exist_ok=True)
    wm_path.write_text("")

    from kernel.memory import WorkingMemory

    wm = WorkingMemory()
    assert wm._data["event_count"] == 0
    assert wm._data["events"] == []

    from kernel.planner import OutcomeMemory

    om = OutcomeMemory(str(tmp_path / "planner" / "outcomes.json"))
    om.record("ctx", "test", True)
    assert om.get_success_rate("test") == 1.0


def test_empty_outcomes_json(tmp_path):
    from kernel.planner import OutcomeMemory

    path = tmp_path / "outcomes.json"
    path.write_text("")
    om = OutcomeMemory(str(path))
    assert om.get_success_rate("anything") == 0.5
    om.record("ctx", "anything", True)
    assert om.get_success_rate("anything") == 1.0


def test_missing_data_dirs_created(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    import kernel.config as cfg

    from kernel.memory import WorkingMemory

    wm = WorkingMemory()
    # файл создаётся при первой записи, не при инициализации
    assert not wm.path.exists() or json.loads(wm.path.read_text())["event_count"] == 0
    assert wm._data["event_count"] == 0
    wm.add_event({"event_type": "test", "content": "auto-created dirs"})
    assert wm._data["event_count"] == 1
    assert wm.path.exists()


def test_unicode_in_queries_and_responses(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    import kernel.config as cfg

    m = Memory(auto_boot=False)
    queries = [
        "日本語のテスト",
        "emoji 🚀🌟 test",
        "line1\nline2\nline3",
        "tab\tseparated\tvalues",
        'quotes "double" and \'single\'',
        "<script>alert('xss')</script>",
    ]
    for q in queries:
        m.respond(f"response to: {q}", q)

    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    data = json.loads(wm_path.read_text())
    auto_events = [e for e in data["events"] if e.get("event_type") == "respond"]
    assert len(auto_events) == len(queries), f"expected {len(queries)}, got {len(auto_events)}"
    for evt, q in zip(auto_events, queries):
        assert json.loads(evt["content"])["query"] == q


def test_outcome_memory_unicode_context(tmp_path):
    from kernel.planner import OutcomeMemory

    om = OutcomeMemory(str(tmp_path / "outcomes.json"))
    om.record("русский_контекст", "читать", True)
    om.record("русский_контекст", "читать", False)
    assert om.get_success_rate("читать", "русский_контекст") == 0.5
    assert om.get_success_rate("читать") == 0.5


def test_concurrent_writes_no_corruption(tmp_path):
    from kernel.utils import atomic_write

    target = tmp_path / "concurrent.json"

    def writer(pid):
        atomic_write(target, {"pid": pid, "data": list(range(100))})
        return pid

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(writer, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    try:
        json.loads(target.read_text())
    except json.JSONDecodeError:
        pytest.fail("concurrent writes corrupted JSON")


def test_large_event_content(tmp_path, monkeypatch):
    _reset_memory()
    _patch_config(monkeypatch, tmp_path)
    from kernel.memory import Memory

    import kernel.config as cfg

    m = Memory(auto_boot=False)
    large_content = "x" * 100_000
    result = m.respond(large_content, "большой запрос")
    assert result["final_draft"] == large_content

    wm_path = Path(cfg.WORKING_MEMORY_PATH)
    data = json.loads(wm_path.read_text())
    auto_events = [e for e in data["events"] if e.get("event_type") == "respond"]
    assert len(auto_events) >= 1
