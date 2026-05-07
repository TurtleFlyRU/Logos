"""E2E-тест MissionControl: полный научный цикл от старта до интеграции."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import kernel.mission_control as mc_mod
from kernel.mission_control import (
    PHASE_ANALYZE,
    PHASE_EXECUTE,
    PHASE_INTEGRATE,
    PHASE_OBSERVE,
    PHASE_ORIENT,
    PHASE_PLAN,
    PHASE_TERMINATE,
    MissionControl,
)


@pytest.fixture
def isolated_mission_paths(tmp_path, monkeypatch):
    """Изолировать миссию и каталог экспериментов от реального Logos/data."""
    data_root = tmp_path / "data"
    repo_root = tmp_path / "repo"
    data_root.mkdir()
    repo_root.mkdir()

    monkeypatch.setattr(mc_mod, "MISSION_STATE_PATH", data_root / "mission" / "state.json")
    monkeypatch.setattr(mc_mod, "EXPERIMENTS_ROOT", repo_root / "experiments")
    monkeypatch.setattr(mc_mod, "MISSION_HYPOTHESES_PATH", data_root / "mission" / "hypotheses.json")
    monkeypatch.setattr(mc_mod, "MISSION_EXPERIMENTS_PATH", data_root / "mission" / "experiments.json")
    monkeypatch.setattr(mc_mod, "MISSION_PROTOCOL_PATH", data_root / "mission" / "protocol.log")

    return {"data_root": data_root, "repo_root": repo_root}


@pytest.fixture
def mock_memory():
    memory = MagicMock()
    memory.semantic.store_principle = MagicMock()
    return memory


def test_full_scientific_cycle(isolated_mission_paths, mock_memory):
    """Полный проход: миссия → гипотеза → эксперимент → выполнение → анализ → интеграция."""
    mc = MissionControl(memory=mock_memory)

    # 1. Start mission
    mission_id = mc.start_mission(
        goal="Убедиться, что простая операция улучшает метрику accuracy",
        success_criteria=["accuracy >= 0.85 после шага"],
    )
    assert mission_id.startswith("mission_")
    assert mc.state.current_phase == PHASE_ORIENT

    # 2. Propose hypothesis
    hid = mc.propose_hypothesis(
        title="Шаг run повышает accuracy",
        description="После выполнения шага точность должна достичь целевого порога.",
        reason="Задача воспроизводима и измерима одной метрикой.",
    )
    assert hid in mc.hypotheses
    assert mc.state.current_phase == PHASE_ORIENT

    # 3. Activate hypothesis → transition to PLAN
    mc.activate_hypothesis(hid)
    assert mc.state.active_hypothesis_id == hid
    assert mc.hypotheses[hid].status == "active"
    assert mc.state.current_phase == PHASE_PLAN

    # 4. Design experiment → transition to EXECUTE
    eid = mc.design_experiment(
        title="Базовый прогон",
        hypothesis_id=hid,
        description="Один атомарный шаг без побочных эффектов.",
        steps=[
            {
                "action": "run",
                "description": "выполнить минимальное действие",
                "expected": "шаг завершается успешно",
            }
        ],
    )
    assert eid in mc.experiments
    assert mc.state.active_experiment_id == eid
    assert mc.state.current_phase == PHASE_EXECUTE

    # 5. Execute step → transition to OBSERVE (all steps done)
    mc.execute_step(eid, 0, result="baseline → tuned model", success=True)
    exp = mc.experiments[eid]
    assert exp.steps[0].status == "done"
    assert exp.status == "done"
    assert mc.state.current_phase == PHASE_OBSERVE

    # 6. Add metrics (before & after)
    mc.add_metric(eid, "accuracy", value=0.5, after=False)
    mc.add_metric(eid, "accuracy", value=0.9, target=0.85, after=True)

    # 7. Analyze → transition to ANALYZE
    analysis = mc.analyze(eid)
    assert analysis.get("hypothesis_supported") is True
    assert analysis.get("experiment_id") == eid
    names = [e["name"] for e in analysis["metrics_summary"]]
    assert "accuracy" in names
    assert mc.state.current_phase == PHASE_ANALYZE

    # 8. Conclude hypothesis → transition to INTEGRATE
    mc.conclude_hypothesis(hid, supported=True)
    assert mc.hypotheses[hid].status == "confirmed"
    assert mc.state.current_phase == PHASE_INTEGRATE
    mock_memory.semantic.store_principle.assert_called_once()

    # 9. Finish mission → transition to TERMINATE
    mc.finish_mission()
    assert mc.state.current_phase == PHASE_TERMINATE
    assert mc.state.active_hypothesis_id is None
    assert mc.state.active_experiment_id is None

    # 10. Check phase ordering
    phases = [t.to_phase for t in mc.state.phase_history]
    assert PHASE_PLAN in phases
    assert phases.index(PHASE_EXECUTE) < phases.index(PHASE_OBSERVE)
    assert phases.index(PHASE_OBSERVE) < phases.index(PHASE_ANALYZE)
    assert phases.index(PHASE_ANALYZE) < phases.index(PHASE_INTEGRATE)
    assert phases.index(PHASE_INTEGRATE) < phases.index(PHASE_TERMINATE)

    # 11. Check persistence
    state_path = isolated_mission_paths["data_root"] / "mission" / "state.json"
    assert state_path.is_file()

    # 12. Check experiment framework files were created
    exp_dir = isolated_mission_paths["repo_root"] / "experiments" / eid
    assert (exp_dir / "HYPOTHESIS.md").is_file()
    assert (exp_dir / "protocol.log").is_file()
    assert (exp_dir / "README.md").is_file()


def test_hypothesis_rejected(isolated_mission_paths, mock_memory):
    """Проверка сценария с опровергнутой гипотезой."""
    mc = MissionControl(memory=mock_memory)
    mc.start_mission("Check if X improves Y")

    hid = mc.propose_hypothesis("X improves Y", "Test", "reason")
    mc.activate_hypothesis(hid)
    eid = mc.design_experiment("Test X", hid, "desc", [
        {"action": "run", "description": "do it", "expected": "ok"},
    ])
    mc.execute_step(eid, 0, "done", True)
    mc.add_metric(eid, "score", value=0.9, after=False)
    mc.add_metric(eid, "score", value=0.5, target=0.85, after=True)

    analysis = mc.analyze(eid)
    assert analysis.get("hypothesis_supported") is False

    mc.conclude_hypothesis(hid, supported=False)
    assert mc.hypotheses[hid].status == "rejected"
    # store_principle не вызывается для опровергнутых гипотез
    mock_memory.semantic.store_principle.assert_not_called()


def test_execute_without_steps(isolated_mission_paths, mock_memory):
    """Регрессия: execute_step без шагов не двигает фазу."""
    mc = MissionControl(memory=mock_memory)
    mc.start_mission("goal")
    hid = mc.propose_hypothesis("t", "d")
    mc.activate_hypothesis(hid)
    eid = mc.design_experiment("noop", hypothesis_id=hid, description="x", steps=None)
    assert mc.experiments[eid].steps == []

    mc.execute_step(eid, 0, "n/a", True)
    assert mc.state.current_phase == PHASE_EXECUTE


def test_human_review_flow(isolated_mission_paths, mock_memory):
    """Проверка handoff человеку."""
    mc = MissionControl(memory=mock_memory)
    mc.start_mission("goal")
    assert mc.state.human_review_needed is False

    mc.request_human_review("Need input on approach")
    assert mc.state.human_review_needed is True

    mc.resume_from_human()
    assert mc.state.human_review_needed is False


def test_mission_state_persistence(isolated_mission_paths, mock_memory):
    """Проверка, что MissionControl восстанавливает состояние после пересоздания."""
    mc1 = MissionControl(memory=mock_memory)
    mc1.start_mission("Persistent mission", ["criterion1"])
    hid = mc1.propose_hypothesis("Persistent H", "desc")
    mc1.activate_hypothesis(hid)
    eid = mc1.design_experiment("Persistent E", hid, "desc", [
        {"action": "step1", "description": "d", "expected": "ok"},
    ])
    mc1.add_metric(eid, "m1", value=0.1, after=False)

    # Новый экземпляр должен загрузить то же состояние
    mc2 = MissionControl(memory=mock_memory)
    assert mc2.state.mission_id == mc1.state.mission_id
    assert mc2.state.goal == "Persistent mission"
    assert mc2.state.current_phase == PHASE_EXECUTE
    assert hid in mc2.hypotheses
    assert eid in mc2.experiments
    assert mc2.hypotheses[hid].status == "active"
    assert len(mc2.experiments[eid].metrics) == 1


def test_get_scientific_context(isolated_mission_paths, mock_memory):
    """Проверка форматирования научного контекста для boot."""
    mc = MissionControl(memory=mock_memory)
    mc.start_mission("Test context")
    hid = mc.propose_hypothesis("Context H", "desc", "reason")
    mc.activate_hypothesis(hid)
    eid = mc.design_experiment("Context E", hid, "desc", [
        {"action": "s1", "description": "d", "expected": "ok"},
    ])

    ctx = mc.get_scientific_context()
    assert "Test context" in ctx
    assert "Context H" in ctx
    assert "Context E" in ctx
    assert "Фаза" in ctx
