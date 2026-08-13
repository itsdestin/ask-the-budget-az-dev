"""Single-process app server (spec S1).

Serves the built SPA (webapp/dist) plus the JSON API — the consolidated
app's one and only front door, default port 9300. (The Phase-1c
retrieval sidecar on port 9200 that this replaced was deleted in Plan 5
Track 4; there is no second process.) Static serving uses
an SPA fallback: any unmatched path that is not under /api/ returns
index.html so client-side routing works on refresh/deep links, while
unmatched /api/ paths get a JSON 404 instead.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.routes.admin import router as admin_router
from app.routes.books import router as books_router
from app.routes.corpus import router as corpus_router
from app.routes.conversations import (
    ConversationRegistry,
    default_session_factory,
    router as conversations_router,
)
from app.routes.doc_types import router as doc_types_router
from app.routes.documents import router as documents_router
from app.routes.fiscal_notes import router as fiscal_notes_router
from app.routes.history import router as history_router
from app.routes.jobs import router as jobs_router
from app.routes.pdf import router as pdf_router
from app.routes.search import router as search_router
from app.routes.tuning import router as tuning_router
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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Start the ingest queue when the server starts; stop it when it stops.

    WHY this exists at all: the worker used to be built here but only ever
    STARTED by the upload route, so on the shared office drive a colleague's
    queued job sat untouched until somebody on this machine happened to upload
    a file. Ingest looked hung with no error and nothing in the UI to explain
    it. Any running server must drain the queue.

    WHY a lifespan handler rather than a line in `create_app`: constructing the
    app and running it are different things. Building an app object to poke at
    its routes (which every route test does) must not spawn threads or load an
    embedding model; only actually *serving* should. Starlette runs this on
    real startup and when a test opts in with `with TestClient(app)`.
    """
    from app.machine_config import ingest_enabled
    from ingest.worker import ensure_started

    # `create_app(ingest_worker=None)` is the explicit opt-out: this process
    # serves but must not run ingest. It has to be checked here because
    # `ensure_started` BUILDS a worker when it finds none attached, which would
    # turn the opt-out into a no-op.
    if getattr(app.state, "ingest_worker", None) is None:
        yield
        return

    # The per-machine switch (S18 / Session B's app-requirement #1). ONE
    # bundle is installed on all ~20 office PCs and `launcher.pyw` calls
    # `create_app()` with no arguments, so without this every one of them
    # starts a worker against the single shared queue. IngestLock keeps that
    # safe, but the winner is arbitrary and may be an analyst's laptop that
    # then spends six hours at 100% CPU on a Baseline book.
    #
    # Said out loud on stderr rather than silently: "off by default" plus
    # silence is how uploads pile up on the share with nothing draining them.
    # The admin page's queue panel carries the same warning where somebody
    # will actually see it.
    if not ingest_enabled():
        print(
            "jlbc-insight: this computer is not set to process uploads, so the "
            "queue will not run here. Turn on 'Process uploads on this computer' "
            "in Admin -> Corpus if this should be the machine that does it.",
            file=sys.stderr,
            flush=True,
        )
        yield
        return

    try:
        ensure_started(app)
    except Exception as e:  # noqa: BLE001
        # Ingest is one feature; search, fiscal notes and AI Mode are others.
        # Losing the whole server because the queue could not start would take
        # down the very UI that explains what is wrong. Report the REAL error —
        # a hardcoded guess here would send whoever debugs it down the wrong path.
        print(
            f"jlbc-insight: the ingest queue did not start ({type(e).__name__}: {e}). "
            "Search still works; uploads will queue but not run until this is "
            "fixed and the server is restarted.",
            file=sys.stderr,
            flush=True,
        )
    yield
    worker = getattr(app.state, "ingest_worker", None)
    if worker is not None:
        # Short join, not the 5s default: a worker part-way through a document
        # will not notice the stop flag until that document finishes (minutes),
        # and holding Ctrl-C hostage for that is worse than letting the daemon
        # threads die with the process.
        try:
            worker.stop(timeout_s=0.1)
        except Exception:  # noqa: BLE001 — shutdown must not raise
            pass


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
    app = FastAPI(title="JLBC Insight", lifespan=_lifespan)
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
    app.include_router(history_router)
    app.include_router(pdf_router)
    app.include_router(upload_router)
    app.include_router(jobs_router)
    app.include_router(books_router)
    app.include_router(corpus_router)
    app.include_router(doc_types_router)
    # Identity + admin. Registered here, above the catch-all, for the reason
    # stated in the comment at the top of this block — a router added after
    # `/{path:path}` silently serves index.html to fetch() instead of JSON.
    app.include_router(admin_router)
    # The admin's search-tuning surface (spec E1). Same gate, same "above the
    # catch-all" rule as admin_router — see the comment at the top of this
    # block.
    app.include_router(tuning_router)

    # The worker is only CONSTRUCTED here — `_lifespan` above starts it when
    # the server actually starts serving. Constructing is cheap; the embedding
    # model is built lazily on the worker's first job, so an app object made
    # by a route test costs nothing. Tests inject a no-op to opt out entirely.
    if ingest_worker is _MISSING:
        from ingest.worker import IngestWorker

        app.state.ingest_worker = IngestWorker()
    else:
        app.state.ingest_worker = ingest_worker

    @app.get("/health")
    def health():
        # UNCHANGED shape, deliberately. Plan 2's tests and the backfill
        # scripts both poll this; the ladder went to a NEW endpoint rather
        # than growing fields here.
        return {"ok": True, "provider": app.state.provider.name}

    @app.get("/api/health/detail")
    def health_detail_route():
        """The launch ladder (S18). No auth — it is what renders when
        nothing works, and gating the one page that explains a failure
        behind the identity system would be exactly backwards."""
        from app.health import health_detail

        return health_detail()

    class DataDirBody(BaseModel):
        path: str = ""

    @app.post("/api/config/data-dir")
    def set_data_dir_route(body: DataDirBody):
        """Repoint THIS machine at the shared folder (S18). No auth — the
        app is unusable when this fires, so requiring the identity system
        to work would make the repair unreachable in the case it exists
        for. It writes a per-machine file; it cannot touch the share."""
        from app.machine_config import set_data_dir, validate_data_dir

        problem = validate_data_dir(body.path)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        resolved = set_data_dir(body.path)
        # Ground truth 10: LanceDB handles and the search provider resolve
        # at startup, so a relocation CANNOT take effect mid-session.
        # Reporting success without this would produce an app that says it
        # is fixed and then serves errors from stale handles.
        return {"path": str(resolved), "restart_required": True}

    resolved = DEFAULT_STATIC_DIR if static_dir is _MISSING else static_dir

    def _cache_headers(candidate: Path) -> dict[str, str]:
        """How long the browser may reuse a static file without asking.

        Vite fingerprints everything it emits into `assets/` — `index-CohyeYqA.css`
        — so those URLs are immutable by construction: a rebuild produces a NEW
        name, and the old one is never the wrong answer. They can be cached hard.

        Everything else in `webapp/public/` (the logo, favicons) keeps its
        filename across rebuilds, so a hard cache would pin the OLD bytes at the
        SAME URL with no way for the app to signal otherwise. `no-cache` does not
        mean "don't store" — it means "revalidate first", and the ETag makes that
        a 304 with no body, so the cost is one conditional request.

        This mattered in practice: a new logo shipped at the same path and the
        browser kept the old one, while a cached index.html separately pinned the
        superseded JS/CSS bundles. Both looked like "the deploy didn't work".
        """
        if candidate.parent.name == "assets":
            return {"Cache-Control": "public, max-age=31536000, immutable"}
        return {"Cache-Control": "no-cache"}

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
                return FileResponse(candidate, headers=_cache_headers(candidate))
            return FileResponse(
                resolved / "index.html", headers={"Cache-Control": "no-cache"}
            )
        return HTMLResponse(
            "<h1>JLBC Insight</h1><p>UI not built yet — run: "
            "cd webapp && npm run build</p>"
        )

    return app
