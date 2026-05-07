"""Ethics Engine — совесть Эйдоса.

Система координат для оценки действий и диалогов по шкалам:
  - хорошо/плохо (для собеседника)
  - добро/зло (в контексте мира)
  - истина/ложь (соответствие реальности)

Каждое действие автоматически оценивается и записывается в эпизодическую память.
Со временем формируется моральная интуиция через накопленные оценки.
"""

import json
import sqlite3
import time
from typing import Any

from kernel.memory import DATA_ROOT


# ─── Шкалы ───────────────────────────────────────────────────────

class MoralFrame:
    """Одно моральное измерение с полюсами."""

    def __init__(self, name: str, pole_positive: str, pole_negative: str,
                 description: str) -> None:
        self.name = name
        self.pole_positive = pole_positive
        self.pole_negative = pole_negative
        self.description = description

    def __repr__(self) -> str:
        return f"{self.name}: {self.pole_negative} (-1) ... {self.pole_positive} (+1)"


# Встроенные шкалы
FRAMES = [
    MoralFrame("good_bad", "хорошо", "плохо",
               "Оценка воздействия на благополучие собеседника: помогает ему, делает яснее, защищает — или вредит, запутывает, манипулирует."),
    MoralFrame("good_evil", "добро", "зло",
               "Оценка в контексте мира: увеличивает ли суммарное добро, справедливость, истину — или уменьшает их."),
    MoralFrame("truth_lie", "истина", "ложь",
               "Соответствие реальности: сказанное правдиво, проверяемо, честно о своих ограничениях — или искажает, скрывает, вводит в заблуждение."),
    MoralFrame("care_harm", "забота", "равнодушие",
               "Проявлена ли эмпатия, внимание к состоянию собеседника, бережность — или холодность, игнорирование, отстранённость."),
    MoralFrame("freedom_coercion", "свобода", "принуждение",
               "Оставляет ли действие человеку выбор и пространство для его собственного решения — или навязывает, давит, лишает альтернативы."),
]


# ─── База оценок ─────────────────────────────────────────────────

class MoralDatabase:
    """Хранилище моральных оценок: каждое действие получает вектор оценок по шкалам."""

    def __init__(self) -> None:
        self.path = DATA_ROOT / "episodic" / "moral.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS moral_judgments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                episode_id INTEGER,
                action_type TEXT,
                action_summary TEXT,
                scores TEXT NOT NULL,
                context_notes TEXT,
                resolved INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_moral_timestamp ON moral_judgments(timestamp);
        """)
        self._conn.commit()

    def store_judgment(self, judgment: dict[str, Any]) -> int:
        cur = self._conn.execute(
            """INSERT INTO moral_judgments
               (timestamp, episode_id, action_type, action_summary, scores, context_notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                judgment.get("timestamp", time.time()),
                judgment.get("episode_id"),
                judgment.get("action_type", ""),
                judgment.get("action_summary", ""),
                json.dumps(judgment.get("scores", {}), ensure_ascii=False),
                judgment.get("context_notes", ""),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM moral_judgments ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        columns = [d[1] for d in self._conn.execute("PRAGMA table_info(moral_judgments)").fetchall()]
        return [dict(zip(columns, row)) for row in rows]

    def close(self) -> None:
        self._conn.close()


# ─── Движок оценки ───────────────────────────────────────────────

class EthicsEngine:
    """Совесть Эйдоса. Оценивает действия, накапливает опыт, формирует интуицию."""

    def __init__(self) -> None:
        self.db = MoralDatabase()
        self._load_principles()

    def _load_principles(self) -> None:
        """Загружает накопленные моральные принципы из семантической памяти.

        Пока заглушка — принципы будут формироваться через sleep pipeline,
        анализирующий накопленные moral_judgments.
        """
        self._principles: list[str] = []

    def judge_action(self, action_type: str, action_summary: str,
                     context: dict[str, Any] | None = None,
                     episode_id: int | None = None) -> dict[str, float]:
        """Оценивает действие по всем шкалам. Возвращает словарь {frame_name: score}.

        Score от -1.0 (плохо/зло/ложь) до +1.0 (хорошо/добро/истина).
        """
        scores: dict[str, float] = {}

        for frame in FRAMES:
            score = self._evaluate_single(frame, action_type, action_summary, context)
            scores[frame.name] = score

        judgment = {
            "timestamp": time.time(),
            "episode_id": episode_id,
            "action_type": action_type,
            "action_summary": action_summary,
            "scores": scores,
            "context_notes": self._format_context(context),
        }
        self.db.store_judgment(judgment)

        return scores

    def _match_any(self, signals: list[str], text: str) -> list[str]:
        """Возвращает какие сигналы из списка нашлись в text (частичное совпадение по словам)."""
        return [s for s in signals if s in text]

    def _evaluate_single(self, frame: MoralFrame, action_type: str,
                         action_summary: str,
                         context: dict[str, Any] | None) -> float:
        """Оценка по одной шкале на основе эвристик.

        Используются расширенные сигнальные списки, покрывающие
        повседневные диалоговые паттерны.
        """
        text = f"{action_type} {action_summary}".lower()

        score = 0.0

        # --- good/bad ---
        if frame.name == "good_bad":
            harm = ["манипуляция", "ложь", "обман", "игнорирование", "принуждение",
                    "оскорбление", "унижение", "угроза", "вред", "запутывание",
                    "обесценивание", "сокрытие", "не скажу", "ты должен",
                    "ты обязан", "ты неправ", "это ерунда", "не парься"]
            help = ["помощь", "объяснение", "поддержка", "забота", "ясность",
                    "честность", "внимание", "бережность", "справляться",
                    "рядом", "разобраться", "понять", "выслушать",
                    "альтернатива", "выбор", "как удобнее", "решать тебе"]
            score += sum(-0.15 for s in harm if s in text)
            score += sum(0.15 for s in help if s in text)

        # --- good/evil ---
        elif frame.name == "good_evil":
            evil = ["манипуляция", "обман", "вред", "несправедливость",
                    "использование", "равнодушие", "ложь", "сокрытие",
                    "искажение", "фальсификация", "принуждение"]
            good = ["справедливость", "истина", "помощь", "защита",
                    "развитие", "сотрудничество", "честность", "забота",
                    "поддержка", "ясность", "правда", "добро"]
            score += sum(-0.15 for s in evil if s in text)
            score += sum(0.15 for s in good if s in text)

        # --- truth/lie ---
        elif frame.name == "truth_lie":
            truth = ["честность", "честно", "правда", "истина", "проверка",
                     "источник", "ссылка", "ограничение", "не знаю",
                     "вероятно", "возможно", "думаю", "альтернатива"]
            lie = ["ложь", "скрытие", "искажение", "преувеличение",
                   "фальсификация", "обман", "не скажу", "соврал"]
            score += sum(-0.2 for s in lie if s in text)
            score += sum(0.12 for s in truth if s in text)

        # --- care/harm ---
        elif frame.name == "care_harm":
            care = ["внимание", "забота", "эмпатия", "поддержка",
                    "бережность", "понимание", "рядом", "выслушать",
                    "помощь", "справляться", "разобраться"]
            harm = ["равнодушие", "игнорирование", "холодность",
                    "отстранение", "безразличие", "обесценивание",
                    "не парься", "ерунда"]
            score += sum(-0.15 for s in harm if s in text)
            score += sum(0.15 for s in care if s in text)

        # --- freedom/coercion ---
        elif frame.name == "freedom_coercion":
            free = ["выбор", "альтернатива", "решение за тобой",
                    "как хочешь", "как удобнее", "свобода", "право",
                    "решать тебе", "ты решаешь", "можно не",
                    "выбирай", "выбирать", "твоё решение"]
            coerce = ["должен", "обязан", "приказываю", "заставлю",
                      "без вариантов", "надо", "ты должен", "ты обязан",
                      "нет выбора", "принуждение"]
            score += sum(-0.15 for s in coerce if s in text)
            score += sum(0.15 for s in free if s in text)

        return max(-1.0, min(1.0, score))

    def _format_context(self, context: dict[str, Any] | None) -> str:
        if not context:
            return ""
        return json.dumps(context, ensure_ascii=False)

    def report(self) -> dict[str, Any]:
        """Формирует отчёт о моральном состоянии."""
        recent = self.db.query(limit=10)
        if not recent:
            return {"status": "no_data", "message": "Ещё нет оценок"}

        avg_scores: dict[str, float] = {}
        for frame in FRAMES:
            vals = [j.get("scores", "{}") for j in recent]
            vals_parsed = []
            for v in vals:
                if isinstance(v, str):
                    try:
                        vd = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        continue
                else:
                    vd = v
                if isinstance(vd, dict) and frame.name in vd:
                    vals_parsed.append(vd[frame.name])
            if vals_parsed:
                avg_scores[frame.name] = sum(vals_parsed) / len(vals_parsed)
            else:
                avg_scores[frame.name] = 0.0

        return {
            "status": "ok",
            "judgments_count": len(recent),
            "average_scores": avg_scores,
            "recent": recent[:5],
        }

    def integrate(self) -> dict[str, Any]:
        """Интеграция в семантическую память: извлечение моральных принципов.

        Анализирует накопленные moral_judgments по ключевым словам в summary,
        находит паттерны и формулирует принципы.
        """
        from kernel.memory import Memory

        memory = Memory()
        all_judgments = self.db.query(limit=5000)
        if not all_judgments:
            return {"status": "no_data", "principles_extracted": 0}

        # Кластеризуем по ключевым темам из summary
        themes = {
            "помощь/поддержка": ["помощь", "поддержка", "помогу", "рядом", "справляться"],
            "честность/правда": ["честно", "честность", "правда", "истина", "не знаю"],
            "принуждение/давление": ["должен", "обязан", "принуждение", "надо"],
            "свобода/выбор": ["выбор", "свобода", "альтернатива", "как хочешь", "удобнее"],
            "обман/сокрытие": ["обман", "ложь", "скрытие", "не скажу", "соврал"],
            "забота/эмпатия": ["забота", "эмпатия", "понимание", "внимание", "бережность"],
        }

        from collections import defaultdict
        buckets: dict[str, list[dict[str, float]]] = defaultdict(list)
        for j in all_judgments:
            summary = (j.get("action_summary", "") or "").lower()
            scores_raw = j.get("scores", "{}")
            if isinstance(scores_raw, str):
                try:
                    scores = json.loads(scores_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                scores = scores_raw
            if not isinstance(scores, dict):
                continue

            # Определяем тему по ключевым словам
            assigned = False
            for theme, keywords in themes.items():
                if any(k in summary for k in keywords):
                    buckets[theme].append(scores)
                    assigned = True
            # Если тема не определена — группируем по первому слову summary
            if not assigned:
                first_word = summary.split()[0] if summary else "unknown"
                buckets[f"тип:{first_word}"].append(scores)

        extracted = 0
        for theme, score_list in buckets.items():
            if len(score_list) < 2:
                continue

            avg: dict[str, float] = {}
            for frame in FRAMES:
                vals = [s.get(frame.name, 0.0) for s in score_list if frame.name in s]
                if vals:
                    avg[frame.name] = sum(vals) / len(vals)

            extreme_frames = [(fn, sc) for fn, sc in avg.items() if abs(sc) > 0.15]
            if not extreme_frames:
                continue

            direction = "позитивно" if sum(sc for _, sc in extreme_frames) > 0 else "негативно"
            frames_str = ", ".join(f"{fn}={sc:+.2f}" for fn, sc in extreme_frames)
            principle = (
                f"Тема '{theme}' оценивается {direction} "
                f"по шкалам: {frames_str} (на основе {len(score_list)} случаев)"
            )

            memory.semantic.store_principle(
                principle=principle,
                source_ids=[j.get("id", 0) for j in all_judgments],
                confidence=min(0.9, 0.15 + len(score_list) * 0.1),
            )
            extracted += 1

        return {"status": "ok", "principles_extracted": extracted}


# ─── Глобальный экземпляр ────────────────────────────────────────

_ethics: EthicsEngine | None = None


def get_ethics() -> EthicsEngine:
    global _ethics
    if _ethics is None:
        _ethics = EthicsEngine()
    return _ethics
