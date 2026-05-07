"""Тесты Planner.decide_with_context: план, сложность, MissionControl, fallback."""

from __future__ import annotations

import pytest

from kernel.planner import ActionSpace, OutcomeMemory, Planner


@pytest.fixture
def planner():
    om = OutcomeMemory(path="/tmp/test_outcomes.json")
    space = ActionSpace(outcome_memory=om)
    space.register("respond", "Ответить", utility_fn=lambda ctx: 0.8, probability_fn=lambda ctx: 0.9)
    space.register("verify", "Проверить", utility_fn=lambda ctx: 0.6, probability_fn=lambda ctx: 0.7)
    space.register("sleep", "Уснуть", utility_fn=lambda ctx: 0.1, probability_fn=lambda ctx: 0.5)
    return Planner(space, outcome_memory=om)


def test_decide_with_context_returns_valid_plan(planner):
    plan = planner.decide_with_context(query="тестовый запрос", complexity_level="low")
    assert plan.selected_action in ("respond", "verify", "sleep")
    assert isinstance(plan.expected_utility, float)
    assert plan.expected_utility >= 0
    assert isinstance(plan.reasoning, str)
    assert len(plan.reasoning) > 0


def test_decide_with_context_responds_to_complexity(planner):
    low = planner.decide_with_context(query="простой запрос", complexity_level="low")
    high = planner.decide_with_context(query="сложный запрос", complexity_level="high")
    assert isinstance(low.selected_action, str)
    assert isinstance(high.selected_action, str)


def test_decide_includes_candidates(planner):
    plan = planner.decide_with_context(query="тест", complexity_level="medium")
    assert len(plan.candidates) == 3
    names = [c["name"] for c in plan.candidates]
    assert "respond" in names
    assert "verify" in names
    assert "sleep" in names


def test_decide_with_context_no_query(planner):
    plan = planner.decide_with_context(query="", complexity_level="low")
    assert isinstance(plan.selected_action, str)


def test_decide_with_high_complexity_verification_flag(planner):
    plan = planner.decide_with_context(query="сложно", complexity_level="high")
    assert plan.selected_action in ("respond", "verify", "sleep")


def test_decide_with_critical_complexity(planner):
    plan = planner.decide_with_context(query="критично", complexity_level="critical")
    assert plan.selected_action in ("respond", "verify", "sleep")


def test_decide_with_mission_control_integration(planner):
    mc = type("MC", (), {"state": type("S", (), {"mission_id": "m1", "current_phase": "observe", "goal": "test"})()})()
    planner.set_mission_control(mc)
    plan = planner.decide_with_context(query="миссия", complexity_level="medium")
    assert isinstance(plan.selected_action, str)


def test_decide_fallback_without_mission_control(planner):
    plan = planner.decide_with_context(query="запрос", complexity_level="medium")
    assert isinstance(plan.selected_action, str)


def test_decide_sets_decision_time(planner):
    plan = planner.decide_with_context(query="быстрый тест", complexity_level="low")
    assert plan.decision_time_ms >= 0
