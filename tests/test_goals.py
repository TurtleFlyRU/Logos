"""Тесты GoalMemory: next_action, summary, completion, persistence."""

from __future__ import annotations

import json

import pytest

from kernel.goals import GoalMemory


@pytest.fixture
def gm(tmp_path, monkeypatch):
    import kernel.config as cfg
    import kernel.goals as goals_mod

    db_path = tmp_path / "goals.db"
    cp_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(cfg, "GOALS_DB_PATH", db_path)
    monkeypatch.setattr(cfg, "GOALS_CHECKPOINT_PATH", cp_path)
    monkeypatch.setattr(goals_mod, "GOALS_DB_PATH", db_path)
    monkeypatch.setattr(goals_mod, "GOALS_CHECKPOINT_PATH", cp_path)

    return GoalMemory(path=str(db_path))


def test_next_action_returns_none_when_no_goals(gm):
    assert gm.next_action() is None


def test_next_action_returns_highest_priority(gm):
    gm.add_goal("Низкий приоритет", priority=0.3)
    gm.add_goal("Высокий приоритет", priority=0.9)
    action = gm.next_action()
    assert action is not None
    assert action["title"] == "Высокий приоритет"
    assert action["action"] == "start"


def test_next_action_returns_in_progress_first(gm):
    low_id = gm.add_goal("Низкий", priority=0.3)
    gm.add_goal("Высокий", priority=0.9)
    gm.update_goal(low_id, status="in_progress", progress=0.5)
    action = gm.next_action()
    assert action is not None
    assert action["title"] == "Низкий"


def test_summary_returns_no_goals_message(gm):
    s = gm.summary()
    assert "Нет целей" in s


def test_summary_contains_active_and_todo(gm):
    gm.add_goal("Активная цель", priority=0.8)
    all_goals = gm.get_goals()
    gid = all_goals[0]["id"]
    gm.update_goal(gid, status="in_progress", progress=0.3)
    gm.add_goal("Ожидающая цель", priority=0.5)
    s = gm.summary()
    assert "Активная цель" in s
    assert "Ожидающая цель" in s


def test_goal_completion_tracking(gm):
    gid = gm.add_goal("Выполняемая цель")
    gm.advance_goal(gid, delta=0.4)
    goal = gm.get_goal(gid)
    assert goal["status"] == "in_progress"
    assert goal["progress"] == 0.4
    gm.advance_goal(gid, delta=0.6)
    goal = gm.get_goal(gid)
    assert goal["status"] == "done"
    assert goal["progress"] == 1.0


def test_persistence_across_reload(gm, tmp_path):
    gm.add_goal("Сохраняемая цель", priority=0.9)
    db_path = gm._path
    cp_path = gm._checkpoint_path

    import kernel.config as cfg
    import kernel.goals as goals_mod
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cfg, "GOALS_DB_PATH", db_path)
    monkeypatch.setattr(cfg, "GOALS_CHECKPOINT_PATH", cp_path)
    monkeypatch.setattr(goals_mod, "GOALS_DB_PATH", db_path)
    monkeypatch.setattr(goals_mod, "GOALS_CHECKPOINT_PATH", cp_path)

    gm2 = GoalMemory(path=str(db_path))
    goals = gm2.get_goals()
    assert len(goals) == 1
    assert goals[0]["title"] == "Сохраняемая цель"
    assert goals[0]["priority"] == 0.9


def test_subgoal_next_action(gm):
    parent_id = gm.add_goal("Родительская цель", priority=0.8)
    gm.update_goal(parent_id, status="in_progress", progress=0.3)
    gm.add_goal("Подцель", priority=0.5, parent_id=parent_id)
    action = gm.next_action()
    assert action is not None
    assert action["action"] == "start_subgoal"
    assert action["title"] == "Подцель"


def test_summary_includes_completed(gm):
    gid = gm.add_goal("Завершённая цель")
    gm.update_goal(gid, status="done", progress=1.0)
    s = gm.summary()
    assert "Завершённая цель" in s
    assert "✔" in s


def test_summary_format_returns_string(gm):
    s = gm.summary()
    assert isinstance(s, str)
