"""Тесты дискретного планировщика."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from planner import ActionSpace, Planner


def make_test_space() -> ActionSpace:
    """Создаёт пространство действий для тестов."""
    space = ActionSpace()

    # Ответ — полезен всегда, вероятность высокая
    space.register(
        name="respond",
        description="Ответить на запрос напрямую",
        utility_fn=lambda ctx: 0.5 if ctx.get("complexity") == "low" else 0.3,
        probability_fn=lambda ctx: 0.95,
    )

    # Верификация — полезна для сложных запросов
    space.register(
        name="verify",
        description="Проверить черновик по памяти перед ответом",
        utility_fn=lambda ctx: 0.8 if ctx.get("needs_verification") else 0.2,
        probability_fn=lambda ctx: 0.7,
    )

    # Поиск во внешней памяти — полезен когда есть внешние данные
    space.register(
        name="search_external",
        description="Поискать во внешней памяти",
        utility_fn=lambda ctx: 0.7 if ctx.get("has_external_data") else 0.1,
        probability_fn=lambda ctx: 0.6,
    )

    # Запрос на увеличение бюджета — только для critical, приоритетнее verify
    space.register(
        name="request_expansion",
        description="Запросить больший вычислительный бюджет",
        utility_fn=lambda ctx: 0.95 if ctx.get("complexity") == "critical" else 0.0,
        probability_fn=lambda ctx: 0.6,
    )

    # Пауза/сон
    space.register(
        name="sleep",
        description="Запустить sleep-пайплайн",
        utility_fn=lambda ctx: 0.6 if ctx.get("query", "").startswith("sleep") else 0.1,
        probability_fn=lambda ctx: 0.8,
    )

    return space


def test_planner_chooses_respond_for_simple_query() -> None:
    """Простой запрос → respond."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="Как дела?",
        complexity_level="low",
    )
    assert plan.selected_action == "respond", (
        f"Expected 'respond', got '{plan.selected_action}'"
    )
    assert plan.decision_time_ms < 100  # должно быть быстро


def test_planner_chooses_verify_for_complex_query() -> None:
    """Сложный запрос → verify."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="Объясни архитектуру иерархической памяти",
        complexity_level="high",
    )
    assert plan.selected_action == "verify", (
        f"Expected 'verify', got '{plan.selected_action}'"
    )


def test_planner_chooses_expansion_for_critical() -> None:
    """Критический запрос → request_expansion."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="Проанализируй 50 эпизодов и выведи закономерности",
        complexity_level="critical",
    )
    assert plan.selected_action == "request_expansion", (
        f"Expected 'request_expansion', got '{plan.selected_action}'"
    )


def test_planner_chooses_search_for_external() -> None:
    """Запрос с внешними данными → search_external."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="Что есть в документации?",
        complexity_level="medium",
    )
    # без has_external_data — respond
    assert plan.selected_action in ("respond", "verify")

    # с has_external_data — search_external
    context = {
        "query": "Что есть в документации?",
        "complexity": "medium",
        "has_external_data": True,
        "needs_verification": False,
    }
    plan2 = planner.decide(context)
    assert plan2.selected_action == "search_external", (
        f"Expected 'search_external', got '{plan2.selected_action}'"
    )


def test_planner_provides_candidates() -> None:
    """План содержит все кандидаты с оценками."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="тест",
        complexity_level="medium",
    )
    assert len(plan.candidates) == len(make_test_space().names())
    for c in plan.candidates:
        assert c["expected_utility"] >= 0
    assert plan.reasoning


def test_planner_sleep_signal() -> None:
    """Запрос начинающийся с sleep → выбирает sleep."""
    planner = Planner(make_test_space())
    plan = planner.decide_with_context(
        query="sleep and integrate",
        complexity_level="low",
    )
    assert plan.selected_action == "sleep"


if __name__ == "__main__":
    test_planner_chooses_respond_for_simple_query()
    test_planner_chooses_verify_for_complex_query()
    test_planner_chooses_expansion_for_critical()
    test_planner_chooses_search_for_external()
    test_planner_provides_candidates()
    test_planner_sleep_signal()
    print("Все тесты пройдены.")
