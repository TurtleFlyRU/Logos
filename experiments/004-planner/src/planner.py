"""Дискретный планировщик поверх вероятностной генерации.

Выбирает следующее действие на основе expected utility:
- Candidates: набор возможных действий
- Scorer: оценивает utility и вероятность успеха для каждого
- Selector: выбирает argmax(expected_utility)
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np


@dataclass
class Action:
    name: str
    description: str
    utility_fn: Callable[[dict[str, Any]], float] | None = None
    probability_fn: Callable[[dict[str, Any]], float] | None = None
    utility: float = 0.0
    probability: float = 0.0
    expected_utility: float = 0.0


@dataclass
class Plan:
    selected_action: str
    expected_utility: float
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    decision_time_ms: float = 0.0


class ActionSpace:
    """Пространство возможных действий.

    Каждое действие — именованная функция с двумя оценками:
    - utility: насколько полезно выполнить это действие в данном контексте
    - probability: насколько вероятен успех
    """

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, name: str, description: str,
                 utility_fn: Callable[[dict[str, Any]], float] | None = None,
                 probability_fn: Callable[[dict[str, Any]], float] | None = None) -> Action:
        action = Action(
            name=name,
            description=description,
            utility_fn=utility_fn,
            probability_fn=probability_fn,
        )
        self._actions[name] = action
        return action

    def get(self, name: str) -> Action | None:
        return self._actions.get(name)

    @property
    def all(self) -> dict[str, Action]:
        return self._actions

    def names(self) -> list[str]:
        return list(self._actions.keys())


class Planner:
    """Принимает контекст, оценивает действия, выбирает лучшее."""

    def __init__(self, action_space: ActionSpace | None = None) -> None:
        self.space = action_space or ActionSpace()

    def decide(self, context: dict[str, Any]) -> Plan:
        """Оценивает все действия в контексте и возвращает план.

        Args:
            context: текущее состояние (запрос, память, сложность, ...)

        Returns:
            Plan с выбранным действием
        """
        start = time.perf_counter()
        candidates: list[dict[str, Any]] = []

        for name, action in self.space.all.items():
            utility = action.utility
            probability = action.probability
            if action.utility_fn:
                utility = action.utility_fn(context)
            if action.probability_fn:
                probability = action.probability_fn(context)
            expected = utility * probability

            candidates.append({
                "name": name,
                "description": action.description,
                "utility": round(utility, 3),
                "probability": round(probability, 3),
                "expected_utility": round(expected, 3),
            })

        if not candidates:
            return Plan(
                selected_action="none",
                expected_utility=0.0,
                candidates=[],
                reasoning="Нет доступных действий",
            )

        best = max(candidates, key=lambda c: c["expected_utility"])
        elapsed = (time.perf_counter() - start) * 1000

        return Plan(
            selected_action=best["name"],
            expected_utility=best["expected_utility"],
            candidates=candidates,
            reasoning=self._reason(best, candidates),
            decision_time_ms=round(elapsed, 2),
        )

    def _reason(self, best: dict, candidates: list[dict]) -> str:
        other_scores = [c["expected_utility"] for c in candidates if c["name"] != best["name"]]
        margin = best["expected_utility"] - (max(other_scores) if other_scores else 0)
        return (
            f"Выбрано '{best['name']}' (EU={best['expected_utility']:.3f}, "
            f"utility={best['utility']:.3f}, prob={best['probability']:.3f}, "
            f"margin={margin:.3f})"
        )

    def decide_with_context(self, query: str, complexity_level: str = "medium",
                            memory_summary: str | None = None,
                            recent_topics: list[str] | None = None) -> Plan:
        """Удобная обёртка: формирует контекст и вызывает decide()."""
        context = {
            "query": query,
            "complexity": complexity_level,
            "memory_summary": memory_summary or "",
            "recent_topics": recent_topics or [],
            "has_external_data": False,
            "needs_verification": complexity_level in ("high", "critical"),
        }
        return self.decide(context)
