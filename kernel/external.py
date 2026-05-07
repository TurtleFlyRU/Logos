"""External Memory — слой внешней памяти с адресацией по содержанию.

Подцель 9. Векторная БД с content-addressable retrieval
и асинхронным пополнением из внешних источников.
"""

import pickle
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from kernel.memory import DATA_ROOT, REPO_ROOT

MODEL_PATH = REPO_ROOT / "rubert-tiny2"


class _Embedder:
    """Лениво загружает rubert-tiny2 и эмбеддит тексты."""

    def __init__(self) -> None:
        self._tokenizer = None
        self._model = None

    def _load(self) -> None:
        if self._tokenizer is not None:
            return
        from transformers import AutoModel, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))
        self._model = AutoModel.from_pretrained(str(MODEL_PATH))

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        encoded = self._tokenizer(texts, padding=True, truncation=True,
                                  return_tensors="pt", max_length=512)
        import torch
        with torch.no_grad():
            output = self._model(**encoded)
        embeddings = output.last_hidden_state[:, 0, :].numpy()
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.where(norms == 0, 1, norms)


class ExternalMemory:
    """Внешняя память: документы с эмбеддингами, поиск по содержанию.

    Хранит:
    - SQLite: метаданные документов (id, source, url, title, timestamp, text)
    - .pkl: кэш эмбеддингов для быстрого поиска
    """

    def __init__(self) -> None:
        self._db_path = DATA_ROOT / "external" / "documents.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path = DATA_ROOT / "external" / "vector_index.pkl"
        self._embedder = _Embedder()
        self._conn = sqlite3.connect(str(self._db_path))
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                url TEXT,
                title TEXT,
                timestamp REAL NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_docs_source ON documents(source);
            CREATE INDEX IF NOT EXISTS idx_docs_timestamp ON documents(timestamp);
        """)
        self._conn.commit()

    def ingest(self, source: str, content: str, title: str = "",
               url: str | None = None) -> int:
        """Добавляет документ во внешнюю память с инкрементальной индексацией."""
        content_hash = str(hash(content))
        now = time.time()
        try:
            cur = self._conn.execute(
                """INSERT INTO documents (source, url, title, timestamp, content, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (source, url, title, now, content, content_hash),
            )
            self._conn.commit()
            doc_id = cur.lastrowid
        except sqlite3.IntegrityError:
            return -1  # уже есть

        self._append_to_index(doc_id, source, url, title, content)
        return doc_id  # type: ignore[return-value]

    def ingest_many(self, docs: list[dict[str, Any]]) -> int:
        """Пакетное добавление документов."""
        added = 0
        for doc in docs:
            doc_id = self.ingest(
                source=doc.get("source", "unknown"),
                content=doc.get("content", ""),
                title=doc.get("title", ""),
                url=doc.get("url"),
            )
            if doc_id > 0:
                added += 1
        return added

    def search(self, query: str, top_k: int = 10,
               min_score: float = 0.15) -> list[dict[str, Any]]:
        """Content-addressable retrieval: поиск по эмбеддингу запроса."""
        index = self._load_index()
        if index is None or len(index["vectors"]) == 0:
            return []

        q_vec = self._embedder.encode([query])[0]
        vectors = index["vectors"]
        scores = np.dot(vectors, q_vec) / (
            np.linalg.norm(vectors, axis=1) * np.linalg.norm(q_vec) + 1e-10
        )
        top_indices = scores.argsort()[-top_k:][::-1]

        results: list[dict[str, Any]] = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < min_score:
                break
            meta = index["meta"][idx]
            results.append({
                "id": meta["id"],
                "source": meta["source"],
                "title": meta["title"],
                "url": meta.get("url"),
                "score": round(score, 4),
                "snippet": meta.get("snippet", ""),
            })
        return results

    def get_stats(self) -> dict[str, Any]:
        count = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        unique_sources = self._conn.execute(
            "SELECT COUNT(DISTINCT source) FROM documents"
        ).fetchone()[0]
        size = self._db_path.stat().st_size
        return {
            "documents": count,
            "unique_sources": unique_sources,
            "size_bytes": size,
        }

    def _append_to_index(self, doc_id: int, source: str, url: str | None,
                          title: str, content: str) -> None:
        """Инкрементально добавляет один документ в векторный индекс."""
        text = f"{title}. {content[:512]}"
        vector = self._embedder.encode([text])[0]
        meta_entry = {
            "id": doc_id,
            "source": source,
            "title": title,
            "url": url,
            "snippet": content[:200],
        }
        index = self._load_index()
        if index is None:
            index = {"vectors": vector.reshape(1, -1), "meta": [meta_entry]}
        else:
            index["vectors"] = np.vstack([index["vectors"], vector])
            index["meta"].append(meta_entry)
        with open(self._index_path, "wb") as f:
            pickle.dump(index, f)

    def rebuild_index(self) -> None:
        """Полная перестройка векторного индекса (для консистентности)."""
        rows = self._conn.execute(
            "SELECT id, source, url, title, content FROM documents ORDER BY id"
        ).fetchall()
        if not rows:
            return

        texts: list[str] = []
        meta: list[dict] = []
        for row in rows:
            doc_id, source, url, title, content = row
            texts.append(f"{title}. {content[:512]}")
            meta.append({
                "id": doc_id,
                "source": source,
                "title": title,
                "url": url,
                "snippet": content[:200],
            })

        vectors = self._embedder.encode(texts)
        index = {"vectors": vectors, "meta": meta}
        with open(self._index_path, "wb") as f:
            pickle.dump(index, f)

    def _load_index(self) -> dict | None:
        if not self._index_path.exists():
            return None
        with open(self._index_path, "rb") as f:
            return pickle.load(f)

    def close(self) -> None:
        self._conn.close()


class FileCollector:
    """Собирает документы из файловой системы."""

    SUPPORTED_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".rst", ".csv"}

    def __init__(self, external_memory: ExternalMemory) -> None:
        self.extmem = external_memory

    def collect(self, paths: list[Path], recursive: bool = True) -> int:
        """Сканирует пути и добавляет файлы во внешнюю память."""
        files: list[Path] = []
        for p in paths:
            if p.is_file() and p.suffix in self.SUPPORTED_EXTENSIONS:
                files.append(p)
            elif p.is_dir() and recursive:
                for f in p.rglob("*"):
                    if f.is_file() and f.suffix in self.SUPPORTED_EXTENSIONS:
                        files.append(f)

        docs: list[dict[str, Any]] = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            docs.append({
                "source": "file",
                "content": content,
                "title": f.name,
                "url": str(f.resolve()),
            })

        return self.extmem.ingest_many(docs)


class WebCollector:
    """Собирает документы из веба (заглушка — требует fetch-инфраструктуры)."""

    def __init__(self, external_memory: ExternalMemory) -> None:
        self.extmem = external_memory

    def collect(self, urls: list[str]) -> int:
        """Заглушка: сохраняет URL как задание на будущее."""
        docs: list[dict[str, Any]] = []
        for url in urls:
            docs.append({
                "source": "web_pending",
                "content": f"[pending fetch] {url}",
                "title": url,
                "url": url,
            })
        return self.extmem.ingest_many(docs)
