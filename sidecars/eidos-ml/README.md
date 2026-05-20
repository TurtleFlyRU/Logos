# eidos-ml — HTTP sidecar для векторного поиска

Rust (`eidos-core`) и desktop вызывают этот сервис, когда задан:

```bash
export EIDOS_ML_SIDECAR_URL=http://127.0.0.1:8765
```

## Запуск

```bash
cd /path/to/Logos
python3 sidecars/eidos-ml/server.py
```

Порт: `EIDOS_ML_PORT` (по умолчанию **8765**), хост: `EIDOS_ML_HOST` (127.0.0.1).

## API

| Метод | Путь | Тело |
|-------|------|------|
| GET | `/health` | — |
| POST | `/search/journal` | `{"query": "…", "top_k": 10}` |
| POST | `/search/external` | `{"query": "…", "top_k": 8, "min_score": 0.12}` |

Ответ: `{"count": N, "hits": [...], "backend": "python_vectors"}`.

## Fallback без sidecar

- **Active memory** — Rust `active_memory.rs` (лексика + episodic/semantic SQLite).
- **Tools** `memory_search_external` — лексика по `documents.db`; вектора — через этот sidecar.
- **Journal** — лексика в Rust; семантика — через sidecar или Python `Journal.search_semantic`.

Проверка: `eidos ml health` (Rust CLI).
