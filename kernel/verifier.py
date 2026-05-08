"""Verifier — проверяет черновик ответа по памяти Эйдоса.

Ранее модуль жил в experiments/003-verification/src/verifier.py и тянул sys.path.
Ядро не должно зависеть от experiments через sys.path.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.memory import Memory


def _extract_key_claims(text: str) -> list[str]:
    claims: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for s in sentences:
        s = s.strip()
        if len(s) > 20:
            claims.append(s)
    return claims


class Verifier:
    """Проверяет черновик по эпизодической и семантической памяти."""

    def __init__(self, memory: Memory | None = None) -> None:
        # Для верификации не нужен boot: работаем по тем же БД/артефактам.
        self.memory = memory or Memory(auto_boot=False)

    def verify(self, draft: str, query: str) -> dict[str, Any]:
        claims = _extract_key_claims(draft)
        issues: list[dict[str, Any]] = []
        corrections: list[str] = []
        supporting: list[str] = []
        contradictions: list[str] = []

        # Проверка по семантической памяти (принципы)
        principles = self.memory.semantic.get_principles(min_confidence=0.3)
        principle_texts = [p["principle"].lower() for p in principles]

        for claim in claims:
            claim_lower = claim.lower()
            supported = False

            for pt in principle_texts:
                # Ищем пересечение значимых слов
                claim_words = set(re.findall(r"\b[a-zа-я]{4,}\b", claim_lower))
                pt_words = set(re.findall(r"\b[a-zа-я]{4,}\b", pt))
                overlap = claim_words & pt_words
                if len(overlap) >= 2:
                    supported = True
                    supporting.append(f"принцип: {pt[:100]}")
                    break

            if not supported:
                issues.append({"claim": claim[:120], "type": "unsupported"})

        # Проверка по эпизодической памяти (похожие эпизоды)
        episodes = self.memory.episodic.query(limit=20, min_salience=0.3)
        for claim in claims:
            claim_lower = claim.lower()
            claim_words = set(re.findall(r"\b[a-zа-я]{4,}\b", claim_lower))
            for ep in episodes:
                ep_text = (ep.get("summary", "") + " " + ep.get("raw_text", "")).lower()
                ep_words = set(re.findall(r"\b[a-zа-я]{4,}\b", ep_text))
                overlap = claim_words & ep_words
                if len(overlap) >= 3:
                    if not any(claim[:40] in c for c in contradictions):
                        contradictions.append(
                            f"эпизод [{ep.get('id','?')}]: {ep.get('summary','')[:80]}"
                        )

        # Формируем вердикт
        needs_correction = len(issues) > 0
        if needs_correction:
            for iss in issues:
                corrections.append(
                    f"Утверждение не подтверждено принципами: «{iss['claim']}»"
                )

        return {
            "claims_checked": len(claims),
            "issues": issues,
            "supporting": supporting,
            "contradictions": contradictions,
            "needs_correction": needs_correction,
            "corrections": corrections,
        }

    def verify_and_format(self, draft: str, query: str) -> dict[str, Any]:
        result = self.verify(draft, query)
        if result["needs_correction"]:
            result["corrected_draft"] = self._correct(draft, result)
        else:
            result["corrected_draft"] = draft
        return result

    @staticmethod
    def _correct(draft: str, result: dict[str, Any]) -> str:
        if not result.get("corrections"):
            return draft + "\n\n*[верификация: расхождений не найдено]*"
        correction_note = "\n".join(f"- {c}" for c in result["corrections"])
        return (
            draft
            + "\n\n---\n*Верификация выявила расхождения:*\n"
            + correction_note
            + "\n*Рекомендуется перепроверить указанные факты.*"
        )

