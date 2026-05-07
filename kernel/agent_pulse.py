"""AgentPulse — минимальный триггер самоинициации.

Правила (проверяются по порядку, первое сработавшее возвращается):
1. Научный контекст → предложить шаг по миссии или стартовать новый цикл
2. Новая информация в ExternalMemory → предложить исследовать
3. Повторяющийся тег без эксперимента → предложить эксперимент
4. Переполненная рабочая память → предложить sleep
5. Активный план → предложить следующий шаг
"""

import json
import time
from typing import Any

from kernel.memory import Memory


class AgentPulse:
    """Тихий наблюдатель. Проверяет условия и возвращает suggestion."""

    def __init__(self, memory: Memory | None = None) -> None:
        self.memory = memory or Memory()
        self._last_sleep_suggestion = 0.0

    def check(self, query: str = "", force: bool = False) -> dict[str, Any] | None:
        """Проверяет условия и возвращает suggestion, если есть.

        Returns:
            dict с suggestion или None
        """
        # Правило 1: научный контекст — MissionControl (самый высокий приоритет)
        mc_suggestion = self._check_mission_control()
        if mc_suggestion:
            return mc_suggestion

        # Правило 2: новая информация во внешней памяти
        try:
            stats = self.memory.external.get_stats()
            if stats["documents"] > 0:
                ext_themes = [
                    e
                    for e in self.memory.episodic.query(limit=20, min_salience=0.0)
                    if "внешн" in (e.get("summary") or "").lower()
                ]
                if len(ext_themes) < 2 and stats["documents"] >= 3 and not force:
                    return {
                        "type": "explore_external",
                        "priority": 0.5,
                        "message": f"Во внешней памяти {stats['documents']} документов. "
                        "Провести анализ?",
                        "reason": "new_external_data",
                    }
        except Exception:
            pass

        # Правило 3: повторяющийся тег без эксперимента
        episodes = self.memory.episodic.query(limit=100, min_salience=0.0)
        tag_counts: dict[str, int] = {}
        for ep in episodes:
            tags = json.loads(ep.get("tags", "[]"))
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        experiment_tags = {
            "эксперимент",
            "эксперимент_001",
            "эксперимент_002",
            "эксперимент_003",
            "эксперимент_004",
            "подцель_9",
            "подцель_10",
            "подцель_11",
            "векторы",
            "поиск",
            "бюджет",
            "верификация",
            "планировщик",
            "внешняя_память",
        }
        for tag, count in tag_counts.items():
            if count >= 5 and tag not in experiment_tags:
                return {
                    "type": "suggest_experiment",
                    "priority": 0.5,
                    "message": f"Тема '{tag}' встречается {count} раз в эпизодах. "
                    "Сформулировать гипотезу?",
                    "reason": "frequent_topic",
                    "tag": tag,
                    "count": count,
                }

        # Правило 4: рабочая память переполнена
        event_count = self.memory.working.data.get("event_count", 0)
        if event_count >= 30 and (time.time() - self._last_sleep_suggestion) > 300:
            self._last_sleep_suggestion = time.time()
            return {
                "type": "sleep",
                "priority": 0.6,
                "message": f"В рабочей памяти {event_count} событий. Запустить sleep для интеграции?",
                "reason": "working_memory_overfill",
            }

        # Правило 5: активный план — предложить следующий шаг
        try:
            active = self.memory.goals.get_goals(status="in_progress", limit=3)
            if active:
                g = active[0]
                subgoals = self.memory.goals.get_goals(parent_id=g["id"])
                next_steps = [sg for sg in subgoals if sg["status"] != "done"]
                if next_steps:
                    ns = next_steps[0]
                    return {
                        "type": "next_goal_step",
                        "priority": 0.65,
                        "message": f"Цель «{g['title']}» ({g['progress']:.0%}). "
                        f"Следующий шаг: «{ns['title']}». "
                        "Продолжить?",
                        "reason": "active_plan_step",
                        "goal_id": g["id"],
                        "next_step": ns["title"],
                    }
                if g["progress"] < 1.0:
                    return {
                        "type": "continue_goal",
                        "priority": 0.55,
                        "message": f"Цель «{g['title']}» на {g['progress']:.0%}. "
                        "Продолжить работу?",
                        "reason": "active_plan_unfinished",
                        "goal_id": g["id"],
                    }
            todo = self.memory.goals.get_goals(status="todo", limit=3)
            if todo:
                g = todo[0]
                return {
                    "type": "start_goal",
                    "priority": 0.5,
                    "message": f"Цель в очереди: «{g['title']}». Начать?",
                    "reason": "next_goal_pending",
                    "goal_id": g["id"],
                }
        except Exception:
            pass

        return None

    # ─── Правило 1: MissionControl ───────────────────────────────

    def _check_mission_control(self) -> dict[str, Any] | None:
        try:
            from kernel.mission_control import MissionControl

            mc = MissionControl(self.memory)
            if mc.state.mission_id and mc.state.current_phase != "terminate":
                hid = mc.state.active_hypothesis_id
                eid = mc.state.active_experiment_id
                phase = mc.state.current_phase

                if mc.state.human_review_needed:
                    return {
                        "type": "mission_human_review",
                        "priority": 0.75,
                        "message": f"Миссия «{mc.state.goal[:60]}» ожидает ревью.",
                        "reason": "human_review_needed",
                    }

                if phase == "integrate":
                    return {
                        "type": "mission_finish",
                        "priority": 0.65,
                        "message": f"Миссия «{mc.state.goal[:60]}» в фазе Integrate. Завершить?",
                        "reason": "mission_ready_to_finish",
                    }

                if eid and eid in mc.experiments:
                    exp = mc.experiments[eid]
                    pending = [s for s in exp.steps if s.status == "pending"]
                    if pending:
                        return {
                            "type": "mission_execute_step",
                            "priority": 0.6,
                            "message": f"Эксперимент «{exp.title}»: шаг «{pending[0].action}» готов к выполнению.",
                            "reason": "mission_step_pending",
                            "experiment_id": eid,
                            "step": pending[0].action,
                        }

                if hid and hid in mc.hypotheses and not eid:
                    return {
                        "type": "mission_design_experiment",
                        "priority": 0.55,
                        "message": f"Гипотеза «{mc.hypotheses[hid].title}» — нужен эксперимент.",
                        "reason": "hypothesis_needs_experiment",
                        "hypothesis_id": hid,
                    }

                if not hid:
                    return {
                        "type": "mission_hypothesize",
                        "priority": 0.5,
                        "message": f"Миссия «{mc.state.goal[:60]}». Сформулировать гипотезу?",
                        "reason": "mission_needs_hypothesis",
                    }
            else:
                tag_suggestions = [
                    v for v in mc.hypotheses.values() if v.status == "proposed"
                ]
                if tag_suggestions:
                    h = tag_suggestions[0]
                    return {
                        "type": "mission_activate_hypothesis",
                        "priority": 0.5,
                        "message": f"Есть неактивированная гипотеза: «{h.title}». Запустить научный цикл?",
                        "reason": "unactivated_hypothesis",
                        "hypothesis_id": h.id,
                    }
        except Exception:
            pass
        return None
