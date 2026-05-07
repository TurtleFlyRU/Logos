"""Поиск по памяти — семантический + хронологический."""

from kernel.memory import EpisodicMemory, SemanticMemory


class MemoryQuery:
    """Объединённый поиск по эпизодической и семантической памяти + дневнику."""

    def __init__(self) -> None:
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

    def find_related(self, tags: list[str], limit: int = 10) -> list[dict]:
        """Находит эпизоды по тегам."""
        from kernel.journal import Journal
        results = []
        for ep in self.episodic.query(limit=100):
            ep_tags = ep.get("tags", "[]")
            if isinstance(ep_tags, str):
                ep_tags_list = ep_tags.strip("[]").replace('"', "").split(",")
            else:
                ep_tags_list = ep_tags
            if any(t.strip() in tags for t in ep_tags_list):
                results.append(ep)
        # Добавляем из дневника
        journal = Journal()
        for tag in tags:
            results.extend(journal.search(tag))
        return results[:limit]

    def get_principles(self, min_confidence: float = 0.3) -> list[dict]:
        return self.semantic.get_principles(min_confidence)

    def context_report(self) -> str:
        """Формирует отчёт о контексте для вставки в промпт."""
        from kernel.journal import Journal
        principles = self.get_principles()
        recent = self.episodic.query(limit=5, min_salience=0.5)

        lines = ["## Память Эйдоса\n"]

        if principles:
            lines.append("### Известные принципы:")
            for p in principles:
                lines.append(f"- [{p['confidence']:.2f}] {p['principle']}")
            lines.append("")

        if recent:
            lines.append("### Последние важные эпизоды:")
            for ep in recent:
                lines.append(f"- {ep.get('summary', '(no summary)')}")
            lines.append("")

        # Последние записи из дневника
        journal = Journal()
        journal_entries = journal.get_recent(3)
        if journal_entries:
            lines.append("### Последние записи дневника:")
            for e in journal_entries:
                lines.append(f"- {e['datetime']} — {e['title']}")
            lines.append("")

        return "\n".join(lines)

    def search_journal(self, query: str) -> list[dict]:
        """Поиск по дневнику."""
        from kernel.journal import Journal
        return Journal().search(query)
