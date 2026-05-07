"""MissionControl — слой автономного научного цикла Эйдоса.

Не участвует в каждом respond. Включается для сложных задач:
- Выдвижение и проверка гипотез
- Планирование и проведение экспериментов
- Анализ результатов и интеграция в семантическую память

Фазовая машина: Orient → Hypothesize → Plan → Execute → Observe → Analyze → Integrate → (цикл или Terminate)
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from kernel.memory import DATA_ROOT, REPO_ROOT, Memory


MISSION_STATE_PATH = DATA_ROOT / "mission" / "state.json"
EXPERIMENTS_ROOT = REPO_ROOT / "experiments"

PHASE_ORIENT = "orient"
PHASE_HYPOTHESIZE = "hypothesize"
PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_OBSERVE = "observe"
PHASE_ANALYZE = "analyze"
PHASE_INTEGRATE = "integrate"
PHASE_TERMINATE = "terminate"

PHASE_CYCLE = [
    PHASE_ORIENT,
    PHASE_HYPOTHESIZE,
    PHASE_PLAN,
    PHASE_EXECUTE,
    PHASE_OBSERVE,
    PHASE_ANALYZE,
    PHASE_INTEGRATE,
]


@dataclass
class MetricSnapshot:
    """Слепок метрик до/после эксперимента."""

    name: str
    before: float | None = None
    after: float | None = None
    target: float | None = None
    unit: str = ""
    description: str = ""

    def is_improved(self) -> bool | None:
        if self.before is None or self.after is None:
            return None
        if self.target is not None:
            return self.after >= self.target
        return self.after > self.before

    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


@dataclass
class Hypothesis:
    """Научная гипотеза: что проверяем, почему, ожидаемый результат."""

    id: str
    title: str
    description: str
    reason: str = ""
    status: str = "proposed"  # proposed | active | confirmed | rejected
    metrics: list[MetricSnapshot] = field(default_factory=list)
    experiment_ids: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class ExperimentStep:
    """Один шаг эксперимента."""

    action: str
    description: str
    expected: str = ""
    status: str = "pending"  # pending | running | done | failed | skipped
    result: str = ""
    metrics_delta: dict[str, float] = field(default_factory=dict)


@dataclass
class Experiment:
    """Эксперимент: план с шагами, метрики, протокол."""

    id: str
    hypothesis_id: str
    title: str
    description: str
    steps: list[ExperimentStep] = field(default_factory=list)
    metrics: list[MetricSnapshot] = field(default_factory=list)
    status: str = "planned"  # planned | running | done | failed | cancelled
    protocol_log: str = ""
    conclusion: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class PhaseTransition:
    """Переход между фазами."""

    from_phase: str
    to_phase: str
    reason: str
    timestamp: float = 0.0


@dataclass
class MissionState:
    """Состояние миссии: текущая фаза, активные гипотезы, ограничения."""

    mission_id: str = ""
    goal: str = ""
    success_criteria: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    current_phase: str = PHASE_ORIENT
    phase_history: list[PhaseTransition] = field(default_factory=list)
    active_hypothesis_id: str | None = None
    active_experiment_id: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    human_review_needed: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0


class MissionControl:
    """Оркестратор научного цикла.

    Управляет полным циклом: от наблюдения до интеграции знаний.
    Не вызывается на каждый respond — только для экспериментов.
    """

    def __init__(self, memory: Memory | None = None) -> None:
        self.memory = memory or Memory()
        self.state = self._load_state()
        self.hypotheses: dict[str, Hypothesis] = {}
        self.experiments: dict[str, Experiment] = {}
        self._load_data()

    # ─── Персистентность ─────────────────────────────────────────

    def _load_state(self) -> MissionState:
        if MISSION_STATE_PATH.exists():
            data = json.loads(MISSION_STATE_PATH.read_text())
            return self._dict_to_mission(data)
        return MissionState()

    def _save_state(self) -> None:
        MISSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MISSION_STATE_PATH.write_text(
            json.dumps(self._mission_to_dict(self.state), indent=2, ensure_ascii=False)
        )

    def _load_data(self) -> None:
        hyps_path = DATA_ROOT / "mission" / "hypotheses.json"
        if hyps_path.exists():
            data = json.loads(hyps_path.read_text())
            self.hypotheses = {k: self._dict_to_hypothesis(v) for k, v in data.items()}
        exps_path = DATA_ROOT / "mission" / "experiments.json"
        if exps_path.exists():
            data = json.loads(exps_path.read_text())
            self.experiments = {k: self._dict_to_experiment(v) for k, v in data.items()}

    def _save_data(self) -> None:
        base = DATA_ROOT / "mission"
        base.mkdir(parents=True, exist_ok=True)
        (base / "hypotheses.json").write_text(
            json.dumps(
                {k: asdict(v) for k, v in self.hypotheses.items()},
                indent=2,
                ensure_ascii=False,
            )
        )
        (base / "experiments.json").write_text(
            json.dumps(
                {k: asdict(v) for k, v in self.experiments.items()},
                indent=2,
                ensure_ascii=False,
            )
        )

    @staticmethod
    def _dict_to_mission(d: dict) -> MissionState:
        ph = [PhaseTransition(**p) for p in d.get("phase_history", [])]
        return MissionState(
            mission_id=d.get("mission_id", ""),
            goal=d.get("goal", ""),
            success_criteria=d.get("success_criteria", []),
            stop_conditions=d.get("stop_conditions", []),
            current_phase=d.get("current_phase", PHASE_ORIENT),
            phase_history=ph,
            active_hypothesis_id=d.get("active_hypothesis_id"),
            active_experiment_id=d.get("active_experiment_id"),
            constraints=d.get("constraints", {}),
            human_review_needed=d.get("human_review_needed", False),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
        )

    @staticmethod
    def _mission_to_dict(m: MissionState) -> dict:
        d = asdict(m)
        d["phase_history"] = [asdict(p) for p in m.phase_history]
        return d

    @staticmethod
    def _dict_to_hypothesis(d: dict) -> Hypothesis:
        metrics = [MetricSnapshot(**m) for m in d.get("metrics", [])]
        return Hypothesis(
            id=d["id"],
            title=d["title"],
            description=d.get("description", ""),
            reason=d.get("reason", ""),
            status=d.get("status", "proposed"),
            metrics=metrics,
            experiment_ids=d.get("experiment_ids", []),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    @staticmethod
    def _dict_to_experiment(d: dict) -> Experiment:
        steps = [ExperimentStep(**s) for s in d.get("steps", [])]
        metrics = [MetricSnapshot(**m) for m in d.get("metrics", [])]
        return Experiment(
            id=d["id"],
            hypothesis_id=d.get("hypothesis_id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            steps=steps,
            metrics=metrics,
            status=d.get("status", "planned"),
            protocol_log=d.get("protocol_log", ""),
            conclusion=d.get("conclusion", ""),
            created_at=d.get("created_at", 0),
            updated_at=d.get("updated_at", 0),
        )

    # ─── API ─────────────────────────────────────────────────────

    def start_mission(
        self,
        goal: str,
        success_criteria: list[str] | None = None,
        stop_conditions: list[str] | None = None,
    ) -> str:
        self.state = MissionState(
            mission_id=f"mission_{int(time.time())}",
            goal=goal,
            success_criteria=success_criteria or [],
            stop_conditions=stop_conditions or [],
            current_phase=PHASE_ORIENT,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._save_state()
        return self.state.mission_id

    def propose_hypothesis(self, title: str, description: str, reason: str = "") -> str:
        hid = f"hyp_{int(time.time())}"
        h = Hypothesis(
            id=hid,
            title=title,
            description=description,
            reason=reason,
            status="proposed",
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.hypotheses[hid] = h
        self._save_data()
        return hid

    def activate_hypothesis(self, hypothesis_id: str) -> None:
        if hypothesis_id in self.hypotheses:
            self.hypotheses[hypothesis_id].status = "active"
            self.hypotheses[hypothesis_id].updated_at = time.time()
            self.state.active_hypothesis_id = hypothesis_id
            self._transition(
                PHASE_HYPOTHESIZE,
                PHASE_PLAN,
                "Hypothesis activated, planning experiment",
            )
            self._save_data()
            self._save_state()

    def design_experiment(
        self, title: str, hypothesis_id: str,
        description: str = "",
        steps: list[dict[str, str]] | None = None,
    ) -> str:
        eid = f"exp_{int(time.time())}"
        exp = Experiment(
            id=eid,
            hypothesis_id=hypothesis_id,
            title=title,
            description=description,
            status="planned",
            created_at=time.time(),
            updated_at=time.time(),
        )
        if steps:
            exp.steps = [ExperimentStep(**s) for s in steps]
        self.experiments[eid] = exp
        if hypothesis_id in self.hypotheses:
            self.hypotheses[hypothesis_id].experiment_ids.append(eid)
            self.hypotheses[hypothesis_id].updated_at = time.time()
        self.state.active_experiment_id = eid
        self._write_experiment_framework(eid)
        self._transition(
            PHASE_PLAN, PHASE_EXECUTE, "Experiment designed, starting execution"
        )
        self._save_data()
        self._save_state()
        return eid

    def execute_step(
        self, experiment_id: str, step_index: int, result: str, success: bool = True
    ) -> None:
        exp = self.experiments.get(experiment_id)
        if not exp or step_index >= len(exp.steps):
            return
        step = exp.steps[step_index]
        step.status = "done" if success else "failed"
        step.result = result
        exp.updated_at = time.time()
        self._append_protocol(
            experiment_id,
            f"Step {step_index}: {step.action} — {'OK' if success else 'FAIL'}. {result}",
        )

        # Check if all steps done
        if all(s.status in ("done", "skipped") for s in exp.steps):
            exp.status = "done"
            self._transition(PHASE_EXECUTE, PHASE_OBSERVE, "All steps completed")
        self._save_data()
        self._save_state()

    def add_metric(
        self,
        experiment_id: str,
        name: str,
        value: float,
        target: float | None = None,
        after: bool = True,
        unit: str = "",
        description: str = "",
    ) -> None:
        exp = self.experiments.get(experiment_id)
        if not exp:
            return
        # Find existing or create
        for m in exp.metrics:
            if m.name == name:
                if after:
                    m.after = value
                else:
                    m.before = value
                if target is not None:
                    m.target = target
                return
        m = MetricSnapshot(name=name, unit=unit, description=description, target=target)
        if after:
            m.after = value
        else:
            m.before = value
        exp.metrics.append(m)
        exp.updated_at = time.time()
        self._save_data()

    def analyze(self, experiment_id: str) -> dict[str, Any]:
        exp = self.experiments.get(experiment_id)
        if not exp:
            return {"error": "not_found"}

        results: dict[str, Any] = {
            "hypothesis_id": exp.hypothesis_id,
            "experiment_id": experiment_id,
            "metrics_summary": [],
            "hypothesis_supported": None,
            "conclusion": "",
        }

        for m in exp.metrics:
            entry = {
                "name": m.name,
                "before": m.before,
                "after": m.after,
                "target": m.target,
                "improved": m.is_improved(),
                "delta": m.delta(),
            }
            results["metrics_summary"].append(entry)

        # Hypothesis supported if all metrics improved
        improved = [m for m in exp.metrics if m.is_improved() is True]
        failed = [m for m in exp.metrics if m.is_improved() is False]
        if len(improved) == len(exp.metrics) and len(exp.metrics) > 0:
            results["hypothesis_supported"] = True
        elif len(failed) > 0:
            results["hypothesis_supported"] = False

        results["conclusion"] = exp.conclusion
        self._transition(PHASE_OBSERVE, PHASE_ANALYZE, "Analysis complete")
        self._save_state()
        return results

    def conclude_hypothesis(self, hypothesis_id: str, supported: bool, conclusion: str = "") -> None:
        h = self.hypotheses.get(hypothesis_id)
        if not h:
            return
        h.status = "confirmed" if supported else "rejected"
        h.updated_at = time.time()
        if conclusion:
            h.description = conclusion

        # Integrate into semantic memory if confirmed
        if supported:
            try:
                principle = (
                    f"Экспериментально подтверждено: {h.title} — {h.description[:100]}"
                )
                self.memory.semantic.store_principle(
                    principle=principle,
                    source_ids=[],
                    confidence=0.8,
                )
            except Exception:
                pass

        self._transition(PHASE_ANALYZE, PHASE_INTEGRATE, f"Hypothesis {h.status}")
        self._save_data()

    def finish_mission(self) -> None:
        self._transition(self.state.current_phase, PHASE_TERMINATE, "Mission completed")
        self.state.active_hypothesis_id = None
        self.state.active_experiment_id = None
        self.state.human_review_needed = False
        self._save_state()
        self._save_data()

    def request_human_review(self, reason: str) -> None:
        self.state.human_review_needed = True
        self.state.updated_at = time.time()
        self._append_protocol("_mission", f"HUMAN REVIEW NEEDED: {reason}")
        self._save_state()

    def resume_from_human(self) -> None:
        self.state.human_review_needed = False
        self.state.updated_at = time.time()
        self._save_state()

    def get_scientific_context(self) -> str:
        """Формирует научный контекст для boot-протокола."""
        lines = []
        if self.state.goal:
            lines.append(f"— Активная миссия: {self.state.goal}")
            lines.append(f"  Фаза: {self.state.current_phase}")
        active_hid = self.state.active_hypothesis_id
        if active_hid and active_hid in self.hypotheses:
            h = self.hypotheses[active_hid]
            lines.append(f"— Гипотеза: {h.title} ({h.status})")
        active_eid = self.state.active_experiment_id
        if active_eid and active_eid in self.experiments:
            e = self.experiments[active_eid]
            done = sum(1 for s in e.steps if s.status == "done")
            total = len(e.steps)
            lines.append(f"— Эксперимент: {e.title} [{done}/{total} шагов]")
        if self.state.human_review_needed:
            lines.append("— ⚠ Ожидает ревью человека")
        return "\n".join(lines)

    # ─── Внутреннее ──────────────────────────────────────────────

    def _transition(self, from_phase: str, to_phase: str, reason: str) -> None:
        self.state.phase_history.append(
            PhaseTransition(
                from_phase=from_phase,
                to_phase=to_phase,
                reason=reason,
                timestamp=time.time(),
            )
        )
        self.state.current_phase = to_phase
        self.state.updated_at = time.time()

    def _write_experiment_framework(self, experiment_id: str) -> None:
        exp = self.experiments.get(experiment_id)
        if not exp:
            return
        dir_path = EXPERIMENTS_ROOT / experiment_id
        dir_path.mkdir(parents=True, exist_ok=True)

        hypothesis = self.hypotheses.get(exp.hypothesis_id)

        # HYPOTHESIS.md
        hyp_content = [
            f"# Гипотеза: {exp.title}",
            "",
            f"**ID:** {experiment_id}",
            f"**Дата:** {time.strftime('%Y-%m-%d %H:%M', time.localtime(exp.created_at))}",
            "",
            "## Формулировка",
            f"{exp.description}",
            "",
        ]
        if hypothesis:
            hyp_content.extend(
                [
                    "## Обоснование",
                    f"{hypothesis.reason}",
                    "",
                ]
            )
        hyp_content.extend(
            [
                "## Метрики",
                *[
                    f"- {m.name}: before={m.before}, target={m.target} {m.unit} — {m.description}"
                    for m in exp.metrics
                ],
                "",
                "## План",
                *[
                    f"{i}. **{s.action}** — {s.description}. Ожидание: {s.expected}"
                    for i, s in enumerate(exp.steps, 1)
                ],
                "",
            ]
        )
        (dir_path / "HYPOTHESIS.md").write_text("\n".join(hyp_content))

        # protocol.log
        (dir_path / "protocol.log").write_text(
            f"# Протокол: {exp.title}\n"
            f"ID: {experiment_id}\n"
            f"Начат: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp.created_at))}\n"
            f"{'=' * 50}\n"
        )

        # README.md placeholder
        (dir_path / "README.md").write_text(
            f"# {exp.title}\n\n"
            f"**Статус:** в процессе\n\n"
            f"См. HYPOTHESIS.md и protocol.log\n"
        )

    def _append_protocol(self, experiment_id: str, entry: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if experiment_id == "_mission":
            log_path = DATA_ROOT / "mission" / "protocol.log"
        else:
            exp = self.experiments.get(experiment_id)
            if not exp:
                return
            exp.protocol_log += f"\n[{ts}] {entry}"
            log_path = EXPERIMENTS_ROOT / experiment_id / "protocol.log"

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(f"\n[{ts}] {entry}")

    def status_report(self) -> dict[str, Any]:
        return {
            "mission_id": self.state.mission_id,
            "goal": self.state.goal,
            "phase": self.state.current_phase,
            "active_hypothesis": self.state.active_hypothesis_id,
            "active_experiment": self.state.active_experiment_id,
            "human_review_needed": self.state.human_review_needed,
            "hypotheses": {
                k: {"title": v.title, "status": v.status}
                for k, v in self.hypotheses.items()
            },
            "experiments": {
                k: {"title": v.title, "status": v.status, "steps": len(v.steps)}
                for k, v in self.experiments.items()
            },
        }
