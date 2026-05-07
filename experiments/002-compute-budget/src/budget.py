"""Оценка сложности запроса и сигнал «нужен больший бюджет»."""

import re
import math
from typing import Any

# Слова-маркеры высокого уровня сложности
_DEEP_VERBS = {
    "сравни", "сравнить", "проанализируй", "проанализировать",
    "спланируй", "спланировать", "синтезируй", "синтезировать",
    "обобщи", "обобщить", "выведи", "вывести",
    "рекурсивно", "итеративно",
    "оптимизируй", "оптимизировать", "рефактори", "рефакторинг",
    "спроектируй", "проектировать", "архитектура",
    "сравнение", "анализ", "план", "синтез",
    "compare", "analyze", "plan", "synthesize",
    "generalize", "derive", "recursively", "iteratively",
    "optimize", "refactor", "design", "architecture",
    "analysis", "planning",
}

# Слова-маркеры ссылок на артефакты
_REF_MARKERS = {
    "файл", "файлы", "class", "function", "метод", "модуль",
    "эксперимент", "эксперимента", "память", "памяти",
    "принцип", "принципа", "дневник", "журнал",
    "записи", "запись", "раздел",
    "найди", "найти", "поиск",
    "file", "files", "module", "memory", "principle", "journal",
    "record", "records", "search", "find",
}

# Пороги бюджета (доля от доступного контекста)
THRESHOLDS = {
    "low": 0.17,
    "medium": 0.4,
    "high": 0.65,
}


class ComplexityScorer:
    """Оценивает сложность запроса."""

    def estimate(self, query: str, referenced_files: int = 0) -> dict[str, Any]:
        score = 0.0
        reasons: list[str] = []
        q_lower = query.lower()
        words = q_lower.split()

        # 1. Длина запроса (0–0.3)
        length = len(words)
        length_score = min(0.3, length / 200)
        if length_score > 0.15:
            reasons.append(f"длина ({length} слов)")
        score += length_score

        # 2. Глубокие глаголы (0–0.35)
        deep_count = sum(1 for w in words if w in _DEEP_VERBS)
        deep_score = min(0.35, deep_count * 0.12)
        if deep_count > 0:
            reasons.append(f"глубокие глаголы ({deep_count})")
        score += deep_score

        # 3. Ссылки на артефакты (0–0.2)
        ref_count = sum(1 for w in words if w in _REF_MARKERS)
        ref_score = min(0.2, ref_count * 0.05)
        if ref_count > 0:
            reasons.append(f"ссылки на артефакты ({ref_count})")
        score += ref_score

        # 4. Количество файлов (0–0.2)
        file_score = min(0.2, referenced_files * 0.04)
        if referenced_files > 0:
            reasons.append(f"файлы ({referenced_files})")
        score += file_score

        # 5. Наличие чисел/идентификаторов экспериментов (0–0.15)
        exp_pattern = r'\b\d{3}\b'
        if re.search(exp_pattern, query):
            reasons.append("номер эксперимента")
            score = min(1.0, score + 0.1)

        # 6. Вопросительные конструкции (0–0.1)
        question_patterns = [
            r'\b(?:почему|зачем|как|каким\s+образом|what|why|how)\b',
            r'\b(?:в\s+чём\s+разница|сравни|различие)\b',
            r'\b(?:explain|compare|contrast|difference)\b',
        ]
        for pat in question_patterns:
            if re.search(pat, q_lower):
                reasons.append("вопрос")
                score = min(1.0, score + 0.05)
                break

        score = min(1.0, score)

        return {
            "score": round(score, 3),
            "level": self._level(score),
            "reasons": reasons,
            "details": {
                "length": round(length_score, 3),
                "deep_verbs": round(deep_score, 3),
                "references": round(ref_score, 3),
                "files": round(file_score, 3),
            },
        }

    @staticmethod
    def _level(score: float) -> str:
        if score < THRESHOLDS["low"]:
            return "low"
        elif score < THRESHOLDS["medium"]:
            return "medium"
        elif score < THRESHOLDS["high"]:
            return "high"
        return "critical"

    @staticmethod
    def needs_expansion(score: float, available_budget: float = 1.0) -> bool:
        """Нужно ли запросить расширение бюджета."""
        return score > THRESHOLDS["medium"] and score > available_budget


class BudgetSignal:
    """Сигнал «нужен больший бюджет»."""

    def __init__(self, scorer: ComplexityScorer | None = None) -> None:
        self.scorer = scorer or ComplexityScorer()

    def evaluate(self, query: str, referenced_files: int = 0,
                 available_budget: float = 1.0) -> dict[str, Any]:
        complexity = self.scorer.estimate(query, referenced_files)
        needs_more = self.scorer.needs_expansion(complexity["score"], available_budget)

        signal = {
            "complexity": complexity,
            "needs_expansion": needs_more,
            "recommendation": self._recommendation(complexity, needs_more),
        }
        return signal

    @staticmethod
    def _recommendation(complexity: dict, needs_more: bool) -> str:
        level = complexity["level"]
        if needs_more:
            return (
                f"Запрос высокой сложности ({complexity['score']:.1f}). "
                f"Рекомендуется увеличить бюджет: причина — {', '.join(complexity['reasons'][:2])}."
            )
        if level == "high":
            return f"Запрос повышенной сложности ({complexity['score']:.1f}). Бюджет достаточен."
        return "Бюджет достаточен."
