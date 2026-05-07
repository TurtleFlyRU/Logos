"""Journal — дневник Эйдоса, разбитый по датам с индексом."""

import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np

from kernel.memory import DATA_ROOT, REPO_ROOT

JOURNAL_DIR = DATA_ROOT / "journal"
MODEL_PATH = REPO_ROOT / "rubert-tiny2"


class _VectorEngine:
    """Лениво загружает rubert-tiny2 и строит/кэширует матрицу эмбеддингов."""

    def __init__(self) -> None:
        self._tokenizer = None
        self._model = None
        self._index_path = DATA_ROOT / "journal_vector_index.pkl"

    def _load_model(self) -> None:
        if self._tokenizer is not None:
            return
        from transformers import AutoModel, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))
        self._model = AutoModel.from_pretrained(str(MODEL_PATH))

    def _encode(self, texts: list[str]) -> np.ndarray:
        self._load_model()
        encoded = self._tokenizer(texts, padding=True, truncation=True,
                                  return_tensors="pt", max_length=512)
        import torch
        with torch.no_grad():
            output = self._model(**encoded)
        embeddings = output.last_hidden_state[:, 0, :].numpy()
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.where(norms == 0, 1, norms)

    def append_to_index(self, section_title: str, body: str, file_name: str) -> None:
        """Инкрементально добавляет одну секцию в векторный индекс."""
        doc_text = f"{section_title}. {body}"
        if len(doc_text) <= 20:
            return
        vector = self._encode([doc_text])[0]
        meta_entry = {"file": file_name, "section": section_title}
        index = self.load_index()
        if index is None:
            index = {"vectors": vector.reshape(1, -1), "meta": [meta_entry]}
        else:
            index["vectors"] = np.vstack([index["vectors"], vector])
            index["meta"].append(meta_entry)
        with open(self._index_path, "wb") as f:
            pickle.dump(index, f)

    def build_index(self, journal: "Journal") -> dict:
        documents: list[str] = []
        doc_meta: list[dict] = []
        for fpath in sorted(JOURNAL_DIR.glob("*.md")):
            if fpath.name == "INDEX.md":
                continue
            text = fpath.read_text()
            sections = text.split("## ")
            for section in sections[1:]:
                lines = section.strip().split("\n")
                title = lines[0].strip() if lines else ""
                body = "\n".join(lines[1:]) if len(lines) > 1 else ""
                doc_text = f"{title}. {body}"
                if len(doc_text) > 20:
                    documents.append(doc_text)
                    doc_meta.append({"file": fpath.name, "section": title})
        if not documents:
            return {"vectors": np.array([]), "meta": []}
        vectors = self._encode(documents)
        index = {"vectors": vectors, "meta": doc_meta}
        with open(self._index_path, "wb") as f:
            pickle.dump(index, f)
        return index

    def load_index(self) -> dict | None:
        if not self._index_path.exists():
            return None
        with open(self._index_path, "rb") as f:
            return pickle.load(f)

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        index = self.load_index()
        if index is None:
            return []
        vectors = index["vectors"]
        if vectors.size == 0:
            return []
        q_vec = self._encode([query])[0]
        similarities = np.dot(vectors, q_vec) / (
            np.linalg.norm(vectors, axis=1) * np.linalg.norm(q_vec) + 1e-10
        )
        top_indices = similarities.argsort()[-top_k:][::-1]
        results: list[dict] = []
        for idx in top_indices:
            if similarities[idx] > 0.1:
                results.append({
                    "file": index["meta"][idx]["file"],
                    "section": index["meta"][idx]["section"],
                    "score": round(float(similarities[idx]), 4),
                })
        return results


class Journal:
    _vec: _VectorEngine | None = None
    """Дневник по дням. Каждый день — отдельный .md файл.
    Индекс ведётся в INDEX.md для быстрого поиска.
    """

    def __init__(self) -> None:
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        self._journal_dir = JOURNAL_DIR
        self._index_path = JOURNAL_DIR / "INDEX.md"

    def today_path(self) -> Path:
        ts = time.strftime("%Y-%m-%d", time.localtime())
        return JOURNAL_DIR / f"{ts}.md"

    REINDEX_THRESHOLD = 5

    def write_session(self, title: str, content: str, tags: list[str] | None = None,
                      salience: float = 0.5) -> None:
        """Записывает сессию в файл дня. Если файл дня уже существует — дописывает."""
        path = self.today_path()
        ts = time.strftime("%H:%M:%S", time.localtime())
        tag_line = f"**Теги:** {', '.join(tags) if tags else 'нет'}"
        entry = (
            f"\n\n---\n"
            f"## {title}\n"
            f"**Время:** {ts}\n"
            f"{tag_line}\n"
            f"**Значимость:** {salience:.2f}\n\n"
            f"{content.strip()}"
        )

        if path.exists():
            with path.open("a") as f:
                f.write(entry)
        else:
            header = f"# Дневник Эйдоса — {path.stem}\n"
            with path.open("w") as f:
                f.write(header + entry)

        self._update_index(title, tags, salience)
        self._append_to_vec_index(title, content)
        self._record_to_memory(title, content, tags, salience)

    def _update_index(self, title: str, tags: list[str] | None, salience: float) -> None:
        """Обновляет INDEX.md — добавляет запись о новом разделе."""
        date = time.strftime("%Y-%m-%d", time.localtime())
        t = time.strftime("%H:%M", time.localtime())
        tag_str = ", ".join(tags) if tags else "—"

        line = f"| {date} {t} | {title[:50]} | {tag_str} | {salience:.2f} | {date}.md |\n"

        if not self._index_path.exists():
            self._index_path.write_text(
                "# Индекс дневника Эйдоса\n\n"
                "| Дата | Раздел | Теги | Значимость | Файл |\n"
                "|------|--------|------|------------|------|\n"
            )

        with self._index_path.open("a") as f:
            f.write(line)

    @staticmethod
    def _normalize(word: str) -> str:
        """Простейшая нормализация русского слова: убирает окончания."""
        if len(word) < 4:
            return word
        suffixes = ["аться", "ется", "ешь", "ете", "ить", "ать", "ять",
                    "ный", "ная", "ное", "ные", "ого", "ому", "ым",
                    "ами", "ах", "ой", "ую", "яя", "ий", "их", "ых",
                    "его", "ему", "им", "ем", "ия", "ие", "ию",
                    "а", "я", "о", "е", "у", "ю", "ы", "и", "й"]
        result = word
        for sfx in sorted(suffixes, key=len, reverse=True):
            if result.endswith(sfx) and len(result) - len(sfx) >= 3:
                result = result[:-len(sfx)]
                break
        # Восстанавливаем основу для пары частых случаев
        if result.endswith("нн") or result.endswith("лл"):
            result = result[:-1]
        return result

    def search(self, query: str) -> list[dict[str, Any]]:
        return self.search_substring(query)

    def search_substring(self, query: str) -> list[dict[str, Any]]:
        """Поиск по дневнику: по названиям разделов, тегам, тексту с нормализацией."""
        results: list[dict[str, Any]] = []
        q_words = [self._normalize(w) for w in query.lower().split()]

        for fpath in sorted(JOURNAL_DIR.glob("*.md")):
            if fpath.name == "INDEX.md":
                continue
            text = fpath.read_text()
            lines = text.split("\n")
            current_section = ""
            current_tags = ""
            for line in lines:
                if line.startswith("## "):
                    current_section = line.lstrip("## ").strip()
                    continue
                if line.startswith("**Теги:**"):
                    current_tags = line.replace("**Теги:**", "").strip()
                    continue

                line_words = [self._normalize(w) for w in line.lower().split()]
                section_words = [self._normalize(w) for w in current_section.lower().split()]
                tag_words = [self._normalize(w) for w in current_tags.lower().split()]

                if any(w in line_words or w in section_words or w in tag_words for w in q_words):
                    results.append({
                        "file": fpath.name,
                        "section": current_section,
                        "tags": current_tags,
                        "snippet": line.strip()[:150],
                    })
        return results

    def search_semantic(self, query: str, top_k: int = 10,
                        fallback: bool = True) -> list[dict[str, Any]]:
        """Семантический поиск через rubert-tiny2 с fallback на substring."""
        if self._vec is None:
            self._vec = _VectorEngine()
        results = self._vec.search(query, top_k=top_k)
        if not results and fallback:
            results = self.search_substring(query)
        return results

    def _record_to_memory(self, title: str, content: str, tags: list[str] | None,
                          salience: float) -> None:
        """Записывает сессию в эпизодическую и семантическую память."""
        try:
            from kernel.memory import Memory
            m = Memory()
            eid = m.record_episode(
                raw_text=content,
                summary=f"{title}: {content[:100]}",
                tags=tags or [],
                salience=salience,
            )
            # Высокозначимые сессии сразу в принципы
            if salience >= 0.8:
                m.semantic.store_principle(
                    principle=title + " — " + content[:150],
                    source_ids=[eid],
                    confidence=salience,
                )
        except Exception:
            pass  # память не должна ломать запись в журнал

    def _append_to_vec_index(self, title: str, content: str) -> None:
        """Инкрементально добавляет новую запись в векторный индекс дневника."""
        if self._vec is None:
            self._vec = _VectorEngine()
        fname = self.today_path().name
        self._vec.append_to_index(section_title=title, body=content[:500], file_name=fname)

    def rebuild_index(self) -> None:
        """Перестраивает векторный индекс дневника."""
        if self._vec is None:
            self._vec = _VectorEngine()
        self._vec.build_index(self)

    def get_recent(self, n: int = 5) -> list[dict[str, Any]]:
        """Последние n записей из индекса."""
        if not self._index_path.exists():
            return []
        lines = self._index_path.read_text().split("\n")
        entries = [line for line in lines if line.startswith("| ")]
        recent = []
        for line in entries[-n:]:
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 5:
                recent.append({
                    "datetime": parts[0],
                    "title": parts[1],
                    "tags": parts[2],
                    "salience": parts[3],
                    "file": parts[4],
                })
        return recent

    def write_event(self, role: str, content: str, tags: list[str] | None = None) -> None:
        """Быстрая запись одного события в дневник. Не кладёт в эпизодическую память.
        Используется WorkingMemory.add_event() для журналирования каждого шага."""
        if not content:
            return
        path = self.today_path()
        ts = time.strftime("%H:%M:%S", time.localtime())
        tag_line = f"**Теги:** {', '.join(tags) if tags else 'нет'}"
        entry = (
            f"\n\n---\n"
            f"## {role} — {ts}\n"
            f"{tag_line}\n\n"
            f"{content.strip()[:500]}"
        )
        if path.exists():
            with path.open("a") as f:
                f.write(entry)
        else:
            header = f"# Дневник Эйдоса — {path.stem}\n"
            with path.open("w") as f:
                f.write(header + entry)

    def entry_count(self) -> int:
        """Сколько всего записей в дневнике."""
        if not self._index_path.exists():
            return 0
        return len([line for line in self._index_path.read_text().split("\n") if line.startswith("| ")])
