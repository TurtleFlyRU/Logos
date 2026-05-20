#!/usr/bin/env python3
"""HTTP ML sidecar: векторный поиск journal/external без torch в Rust.

Запуск из корня репозитория::

    export EIDOS_ML_SIDECAR_URL=http://127.0.0.1:8765
    python3 sidecars/eidos-ml/server.py

Эндпоинты:
  GET  /health
  POST /search/journal   {"query": "...", "top_k": 10}
  POST /search/external  {"query": "...", "top_k": 8, "min_score": 0.12}
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[eidos-ml] {self.address_string()} - {fmt % args}\n")

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "eidos-ml",
                    "repo": _REPO,
                },
            )
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            _json_response(self, 400, {"error": f"invalid JSON: {exc}"})
            return
        if not isinstance(req, dict):
            _json_response(self, 400, {"error": "body must be object"})
            return

        path = self.path.rstrip("/")
        if path == "/search/journal":
            self._search_journal(req)
            return
        if path == "/search/external":
            self._search_external(req)
            return
        _json_response(self, 404, {"error": f"unknown path: {path}"})

    def _search_journal(self, req: dict[str, Any]) -> None:
        query = str(req.get("query") or "").strip()
        if not query:
            _json_response(self, 400, {"error": "query required"})
            return
        top_k = int(req.get("top_k") or 10)
        top_k = max(1, min(top_k, 30))
        try:
            from kernel.journal import Journal

            hits = Journal(memory=None).search_semantic(query, top_k=top_k, fallback=True)
        except Exception as exc:
            _json_response(self, 500, {"error": str(exc), "hits": []})
            return
        _json_response(self, 200, {"count": len(hits), "hits": hits, "backend": "python_vectors"})

    def _search_external(self, req: dict[str, Any]) -> None:
        query = str(req.get("query") or "").strip()
        if not query:
            _json_response(self, 400, {"error": "query required"})
            return
        top_k = int(req.get("top_k") or 8)
        top_k = max(1, min(top_k, 20))
        min_score = float(req.get("min_score") or 0.12)
        try:
            from kernel.memory import Memory

            mem = Memory(auto_boot=False)
            hits = mem.external.search(query, top_k=top_k, min_score=min_score)
        except Exception as exc:
            _json_response(self, 500, {"error": str(exc), "hits": []})
            return
        _json_response(
            self,
            200,
            {"count": len(hits), "hits": hits, "backend": "python_vectors"},
        )


def main() -> int:
    host = os.environ.get("EIDOS_ML_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("EIDOS_ML_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[eidos-ml] http://{host}:{port}  repo={_REPO}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[eidos-ml] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
