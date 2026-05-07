"""Планировщик — дискретное принятие решений с обучением на опыте.

Выбирает следующее действие на основе expected utility:
- ActionSpace: набор возможных действий с функциями полезности
- OutcomeMemory: статистика успехов/неудач для адаптации вероятностей
- Planner: argmax(expected_utility)

Планировщик учится: после каждого действия вызывается record_outcome(),
и probability_fn корректируется на основе реального опыта.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kernel.config import PLANNER_DATA_DIR


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_action": self.selected_action,
            "expected_utility": self.expected_utility,
            "candidates": self.candidates,
            "reasoning": self.reasoning,
            "decision_time_ms": self.decision_time_ms,
        }


class OutcomeMemory:
    """Хранит истории контекст → действие → успех/неудача.

    Позволяет Planner'у адаптировать probability на основе реального опыта.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else (PLANNER_DATA_DIR / "outcomes.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._outcomes: list[dict[str, Any]] = []
        if self.path.exists():
            self._outcomes = json.loads(self.path.read_text())

    def record(self, context_sig: str, action: str, success: bool) -> None:
        self._outcomes.append(
            {
                "context_sig": context_sig,
                "action": action,
                "success": success,
                "timestamp": time.time(),
            }
        )
        self.path.write_text(
            json.dumps(self._outcomes[-500:], indent=2, ensure_ascii=False)
        )

    def get_success_rate(
        self, action: str, context_sig: str | None = None, window: int = 50
    ) -> float:
        all_matching = [
            o
            for o in self._outcomes
            if o["action"] == action
            and (context_sig is None or o.get("context_sig") == context_sig)
        ]
        relevant = all_matching[-window:]
        if not relevant:
            return 0.5
        successes = sum(1 for o in relevant if o["success"])
        return successes / len(relevant)

    def total_outcomes(self, action: str) -> int:
        return sum(1 for o in self._outcomes if o["action"] == action)

    @property
    def size(self) -> int:
        return len(self._outcomes)

    @staticmethod
    def make_context_sig(context: dict[str, Any]) -> str:
        complexity = context.get("complexity", "unknown")
        needs_ver = context.get("needs_verification", False)
        has_ext = context.get("has_external_data", False)
        return f"cplx={complexity}|verify={needs_ver}|ext={has_ext}"


class ActionSpace:
    """Пространство возможных действий.

    Каждое действие — именованная функция с двумя оценками:
    - utility: насколько полезно выполнить это действие в данном контексте
    - probability: насколько вероятен успех (адаптируется через OutcomeMemory)
    """

    def __init__(self, outcome_memory: OutcomeMemory | None = None) -> None:
        self._actions: dict[str, Action] = {}
        self._outcome_memory = outcome_memory

    def register(
        self,
        name: str,
        description: str,
        utility_fn: Callable[[dict[str, Any]], float] | None = None,
        probability_fn: Callable[[dict[str, Any]], float] | None = None,
    ) -> Action:
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

    def compute_probability(self, action: Action, context: dict[str, Any]) -> float:
        prob = action.probability
        if action.probability_fn:
            prob = action.probability_fn(context)
        if self._outcome_memory:
            sig = OutcomeMemory.make_context_sig(context)
            empirical = self._outcome_memory.get_success_rate(action.name, sig)
            sig_total = sum(
                1
                for o in self._outcome_memory._outcomes[-200:]
                if o["action"] == action.name and o["context_sig"] == sig
            )
            if sig_total >= 3:
                prob = 0.3 * prob + 0.7 * empirical
        return prob


class Planner:
    """Принимает контекст, оценивает действия (с учётом опыта), выбирает лучшее."""

    def __init__(
        self,
        action_space: ActionSpace | None = None,
        outcome_memory: OutcomeMemory | None = None,
    ) -> None:
        self.space = action_space or ActionSpace()
        self._om = outcome_memory
        self._mission_control: Any = None

    def set_mission_control(self, mc: Any) -> None:
        self._mission_control = mc

    def decide(self, context: dict[str, Any]) -> Plan:
        start = time.perf_counter()
        candidates: list[dict[str, Any]] = []

        for name, action in self.space.all.items():
            utility = action.utility
            if action.utility_fn:
                utility = action.utility_fn(context)
            probability = self.space.compute_probability(action, context)
            expected = utility * probability

            candidates.append(
                {
                    "name": name,
                    "description": action.description,
                    "utility": round(utility, 3),
                    "probability": round(probability, 3),
                    "expected_utility": round(expected, 3),
                }
            )

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
        other_scores = [
            c["expected_utility"] for c in candidates if c["name"] != best["name"]
        ]
        margin = best["expected_utility"] - (max(other_scores) if other_scores else 0)
        return (
            f"selected '{best['name']}' (EU={best['expected_utility']:.3f}, "
            f"utility={best['utility']:.3f}, prob={best['probability']:.3f}, "
            f"margin={margin:.3f})"
        )

    def record_outcome(
        self, action: str, context: dict[str, Any], success: bool
    ) -> None:
        om = self._om or self.space._outcome_memory
        if om:
            sig = OutcomeMemory.make_context_sig(context)
            om.record(sig, action, success)

    def decide_with_context(
        self,
        query: str,
        complexity_level: str = "medium",
        memory_summary: str | None = None,
        recent_topics: list[str] | None = None,
    ) -> Plan:
        context = {
            "query": query,
            "complexity": complexity_level,
            "memory_summary": memory_summary or "",
            "recent_topics": recent_topics or [],
            "has_external_data": False,
            "needs_verification": complexity_level in ("high", "critical"),
        }

        # Добавляем сигнал MissionControl в контекст
        mission_signal = 0.0
        try:
            if self._mission_control and self._mission_control.state.mission_id:
                mission_signal = 0.6
                context["has_mission"] = True
                context["mission_phase"] = self._mission_control.state.current_phase
                context["mission_goal"] = self._mission_control.state.goal[:100]
        except AttributeError:
            pass

        if mission_signal > 0:
            context["mission_present"] = mission_signal

        return self.decide(context)
