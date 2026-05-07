#!/usr/bin/env python3
"""Индексация записей дневника в эмбеддинги через sentence-transformers."""

import json
import os
import pickle
import sys
from pathlib import Path

EXPERIMENTS_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = EXPERIMENTS_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from huggingface_hub import login
from transformers import AutoTokenizer, AutoModel
import torch

from kernel.journal import Journal

if os.environ.get("HF_TOKEN"):
    login(token=os.environ["HF_TOKEN"])


def build_index() -> dict:
    journal = Journal()
    journal_dir = journal._journal_dir

    documents = []
    doc_meta = []

    for fpath in sorted(journal_dir.glob("*.md")):
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
        print("Нет записей для индексации")
        return {"vectors": np.array([]), "meta": []}

    model_name = str(REPO_ROOT / "rubert-tiny2")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)

    def encode(texts: list[str]) -> np.ndarray:
        encoded_input = tokenizer(texts, padding=True, truncation=True, return_tensors="pt", max_length=512)
        with torch.no_grad():
            model_output = model(**encoded_input)
        embeddings = model_output.last_hidden_state[:, 0, :].numpy()
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.where(norms == 0, 1, norms)

    vectors = encode(documents)

    result = {
        "vectors": vectors,
        "meta": doc_meta,
        "model_name": model_name,
    }

    results_dir = EXPERIMENTS_ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    with open(results_dir / "vector_index.pkl", "wb") as f:
        pickle.dump(result, f)

    print(f"Проиндексировано документов: {len(documents)}")
    print(f"Размерность эмбеддингов: {vectors.shape[1]}")
    print(f"Форма матрицы: {vectors.shape}")
    print(f"Модель: {result['model_name']}")
    print(f"Результаты сохранены в {results_dir}")

    return result


if __name__ == "__main__":
    build_index()
