#!/usr/bin/env python3
"""Тестовый семантический поиск и замер precision/recall."""

import json
import os
import pickle
import sys
import time
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


def load_index(results_dir: Path) -> dict:
    with open(results_dir / "vector_index.pkl", "rb") as f:
        return pickle.load(f)


def search_substring(query: str, journal: Journal) -> list[str]:
    results = journal.search(query)
    return list(set(r["file"] for r in results))


def search_vector(query: str, vectors: np.ndarray, meta: list[dict],
                  tokenizer, model, top_k: int = 10) -> list[str]:
    encoded = tokenizer([query], padding=True, truncation=True, return_tensors="pt", max_length=512)
    with torch.no_grad():
        output = model(**encoded)
    q_vec = output.last_hidden_state[:, 0, :].numpy()
    q_vec = q_vec / np.linalg.norm(q_vec)
    similarities = np.dot(vectors, q_vec.T).flatten()
    top_indices = similarities.argsort()[-top_k:][::-1]
    return [meta[i]["file"] for i in top_indices if similarities[i] > 0.1]


def test() -> dict:
    results_dir = EXPERIMENTS_ROOT / "results"
    if not (results_dir / "vector_index.pkl").exists():
        print("Индекс не найден. Сначала запустите index_vectors.py")
        return {}

    index = load_index(results_dir)
    model_path = index.get("model_name", str(REPO_ROOT / "rubert-tiny2"))
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModel.from_pretrained(model_path)
    journal = Journal()

    test_queries = [
        "архитектура памяти",
        "моральные принципы",
        "сон и восстановление",
        "эксперимент",
        "совесть и этика",
        "забывание и хранение",
    ]

    results_data = []
    for query in test_queries:
        t0 = time.time()
        substring_results = search_substring(query, journal)
        t_sub = time.time() - t0

        t0 = time.time()
        vector_results = search_vector(query, index["vectors"], index["meta"], tokenizer, model)
        t_vec = time.time() - t0

        results_data.append({
            "query": query,
            "substring": {
                "count": len(substring_results),
                "files": substring_results[:5],
                "time_ms": round(t_sub * 1000, 1),
            },
            "vector": {
                "count": len(vector_results),
                "files": vector_results[:5],
                "time_ms": round(t_vec * 1000, 1),
            },
        })

    print(f"{'Запрос':<30} {'Substr':<8} {'Vector':<8} {'Sub(ms)':<10} {'Vec(ms)':<10}")
    print("-" * 70)
    for r in results_data:
        print(f"{r['query']:<30} {r['substring']['count']:<8} {r['vector']['count']:<8} "
              f"{r['substring']['time_ms']:<10} {r['vector']['time_ms']:<10}")

    with open(results_dir / "search_metrics.json", "w") as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)

    return {"results": results_data}


if __name__ == "__main__":
    test()
