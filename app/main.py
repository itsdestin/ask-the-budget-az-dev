"""Single-process app server (spec S1).

Serves the built SPA (webapp/dist) plus the JSON API. Distinct from
retrieval/api.py (the legacy Phase-1c sidecar on 9200): this is the
consolidated app's front door, default port 9300. Static serving uses
an SPA fallback: any unmatched path that is not under /api/ returns
index.html so client-side routing works on refresh/deep links, while
unmatched /api/ paths get a JSON 404 instead.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.routes.books import router as books_router
from app.routes.conversations import (
    ConversationRegistry,
    default_session_factory,
    router as conversations_router,
)
from app.routes.documents import router as documents_router
from app.routes.fiscal_notes import router as fiscal_notes_router
from app.routes.jobs import router as jobs_router
from app.routes.pdf import router as pdf_router
from app.routes.search import router as search_router
from app.routes.upload import router as upload_router
from app.search_provider import LanceSearchProvider, SearchProvider, StubSearchProvider


def _default_provider() -> SearchProvider:
    """Real corpus present -> real provider; else the fixture stub.

    The probe asks LanceDB (store/config.py's data dir — JLBC_DATA_DIR, or the
    repo's data/insight-data) whether budget_chunks has rows. Fresh checkouts,
    CI, and dev machines that haven't run the Plan 1 migration have none, and
    get the stub plus an honest stderr note saying WHY — a silent fallback
    would leave "why is my search returning fake rows" undiagnosable.

    Deliberate tradeoff: corpus availability is checked ONCE, at app startup.
    A corpus migrated while the server runs is not picked up (restart to use
    it), and a share that goes offline mid-session surfaces per-request as the
    search route's 503, not as a fallback to stub — swapping in fake rows
    mid-session because the share hiccuped would be far worse than an honest
    error. Plan 5's launcher owns any fancier health ladder."""
    try:
        from store.chunk_store import ChunkStore

        if ChunkStore().count("budget_chunks") > 0:
            return LanceSearchProvider()
        reason = "budget_chunks table is empty"
    except Exception as e:  # missing table, missing deps, unreadable data dir…
        reason = f"{type(e).__name__}: {e}"
    print(
        f"jlbc-insight: no usable corpus ({reason}) — serving stub search fixtures. "
        "Set JLBC_DATA_DIR to a migrated data dir for real retrieval.",
        file=sys.stderr,
    )
    return StubSearchProvider()

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp" / "dist"
# Sentinel: distinguishes "caller passed nothing" (use the real webapp/dist)
# from "caller explicitly passed None" (simulate an unbuilt UI). A plain None
# default would conflate the two.
_MISSING = object()


def create_app(
    *, provider: SearchProvider | None = None,
    static_dir: Path | None | object = _MISSING,
    session_factory: Callable[..., object] | None = None,
    ingest_worker: object | None = _MISSING,
) -> FastAPI:
    app = FastAPI(title="JLBC Insight")
    # Explicit None check, not `provider or ...`: an injected provider object
    # could be falsy (e.g. a fake defining __len__/__bool__) and get silently
    # swapped for the default, which would be a baffling test failure.
    app.state.provider = _default_provider() if provider is None else provider
    # The AI-Mode seam: tests inject a fake tool loop here so a conversation
    # test never reaches OpenRouter, LanceDB or the ONNX models. Unlike
    # static_dir there is no _MISSING sentinel — "no session factory" has no
    # useful meaning (the routes would have nothing to run), so None simply
    # means "use the real one". Same explicit `is None` check as provider:
    # a callable object can be falsy.
    app.state.session_factory = (
        default_session_factory if session_factory is None else session_factory
    )
    # One conversation table per app instance, not a module global: two apps
    # in one test process (there are several) must not share conversations.
    app.state.conversations = ConversationRegistry()

    # Route-registration order is load-bearing: FastAPI matches in registration
    # order, so the `/{path:path}` catch-all below MUST be registered after
    # every real router or it swallows /api/* and /health.
    app.include_router(search_router)
    app.include_router(fiscal_notes_router)
    app.include_router(documents_router)
    app.include_router(conversations_router)
    app.include_router(pdf_router)
    app.include_router(upload_router)
    app.include_router(jobs_router)
    app.include_router(books_router)

    # The ingest worker is created but NOT started here — starting it builds
    # the embedding model, and a machine that only searches should never pay
    # that cost. The upload route starts it on the first upload. Tests inject
    # a no-op so a route test never spawns a thread.
    if ingest_worker is _MISSING:
        from ingest.worker import IngestWorker

        app.state.ingest_worker = IngestWorker()
    else:
        app.state.ingest_worker = ingest_worker

    @app.get("/health")
    def health():
        return {"ok": True, "provider": app.state.provider.name}

    resolved = DEFAULT_STATIC_DIR if static_dir is _MISSING else static_dir

    @app.get("/{path:path}")
    def spa(path: str):
        # Unmatched /api/ paths must fail as a JSON 404. Falling through to
        # index.html would hand fetch() callers HTML, and JSON.parse would
        # report the useless "Unexpected token '<'" instead of a clear 404.
        # Bare "api" is checked too, so /api itself 404s instead of serving HTML.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Unknown API route")
        if resolved and (resolved / "index.html").is_file():
            candidate = (resolved / path).resolve()
            # Serve real static files; anything else falls back to the SPA.
            if path and candidate.is_file() and resolved.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(resolved / "index.html")
        return HTMLResponse(
            "<h1>JLBC Insight</h1><p>UI not built yet — run: "
            "cd webapp && npm run build</p>"
        )

    return app
