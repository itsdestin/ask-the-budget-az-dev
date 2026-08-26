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
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app import folder_picker
from app.routes.admin import router as admin_router
from app.routes.books import router as books_router
from app.routes.agencies import router as agencies_router
from app.routes.book_formats import router as book_formats_router
from app.routes.books_missing import router as books_missing_router
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
from app.routes.issues import router as issues_router
from app.routes.jobs import router as jobs_router
from app.routes.pdf import router as pdf_router
from app.routes.search import router as search_router
from app.routes.tuning import router as tuning_router
from app.routes.upload import router as upload_router
from app.search_provider import LanceSearchProvider, SearchProvider, StubSearchProvider


REPROBE_INTERVAL_S = 30.0


def _probe_provider() -> SearchProvider | None:
    """The real provider if the corpus opens and has rows, else None.

    Prints WHY on stderr (the launcher's log) so a stub is never silent.
    create=False: a probe must not manufacture the folder it probes
    (spec principle 3, 2026-08-25).
    """
    try:
        from store.chunk_store import ChunkStore
        from store.config import resolve_data_dir

        # root=resolve_data_dir(), not the default (root=None): ChunkStore's
        # `self._root = (root or data_dir()) / "lancedb"` calls data_dir()
        # -- which CREATES the folder -- whenever root is omitted, regardless
        # of create=False. Passing the already-resolved, non-creating path
        # is the same pattern app/health.py and app/machine_config.py use
        # for every other create=False probe; skipping it here reproduced
        # the laptop bug one level up — a stub-triggered health check would
        # conjure the missing share directory it was reporting as missing.
        if ChunkStore(root=resolve_data_dir(), create=False).count("budget_chunks") > 0:
            return LanceSearchProvider()
        reason = "budget_chunks table is empty"
    except Exception as e:  # noqa: BLE001 — missing folder, unreadable share, engine error
        reason = f"{type(e).__name__}: {e}"
    print(
        f"jlbc-search: no usable corpus ({reason}) — serving stub search fixtures "
        "until the shared folder can be opened.",
        file=sys.stderr,
    )
    return None


def _default_provider() -> SearchProvider:
    """Real corpus present -> real provider; else the fixture stub.

    Chosen at startup and RE-PROBED while stub (see _install_reprobe): a
    share that is down at 8 AM and back at 8:05 must not mean fake rows all
    day. A real provider never swaps back to stub — a share that goes away
    mid-session surfaces as the search route's honest 503, never as fake
    rows.
    """
    return _probe_provider() or StubSearchProvider()


def _install_reprobe(app: FastAPI) -> None:
    lock = threading.Lock()
    last = {"at": float("-inf")}

    def reprobe(*, force: bool = False) -> str:
        """Re-run the corpus probe. Unforced: only while on the stub, at most
        once per REPROBE_INTERVAL_S. Forced (a repair was just saved): always
        — the repair screen can appear on a machine that booted with a REAL
        corpus whose handles are now dead, and skipping it because the
        provider is 'not stub' would make the repair a no-op."""
        current = app.state.provider
        if not force and current.name != "stub":
            return current.name
        # Non-blocking: lancedb.connect on an unreachable UNC path can block
        # for the SMB timeout; concurrent searches must not queue behind it
        # (spec S5). Whoever holds the lock is already probing.
        if not lock.acquire(blocking=force):
            return current.name
        try:
            now = time.monotonic()
            if not force and now - last["at"] < REPROBE_INTERVAL_S:
                return current.name
            last["at"] = now
            fresh = _probe_provider()
            from retrieval.pipeline import reset_default_collaborators

            if fresh is not None:
                app.state.provider = fresh
            if fresh is not None or force:
                # AI Mode caches its own ChunkStore; a pointer that changed
                # under it must not keep answering from the old folder.
                reset_default_collaborators()
            return app.state.provider.name
        finally:
            lock.release()

    app.state.reprobe = reprobe


def _start_archive_sweep() -> None:
    """Kick off the spec-T13 job-file tidy in the background. Never raises.

    A failure means the queue shows some finished rows it need not -- untidy,
    not broken -- so it is reported on stderr and swallowed rather than taking
    down a server whose search, fiscal notes and AI Mode are all fine.

    Two machines sweeping the same share at once is safe and expected; see
    `ingest.archive.sweep`.
    """
    def _run() -> None:
        try:
            from ingest.jobs import sweep_archive

            moved = sweep_archive()
            if moved:
                print(
                    f"jlbc-search: moved {moved} finished job files into "
                    "jobs/done/ so the queue shows outstanding work.",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as e:  # noqa: BLE001
            print(
                f"jlbc-search: could not tidy the job queue "
                f"({type(e).__name__}: {e}). The queue still works; it will "
                "just list finished documents too.",
                file=sys.stderr,
                flush=True,
            )

    try:
        threading.Thread(target=_run, name="jlbc-archive-sweep", daemon=True).start()
    except Exception as e:  # noqa: BLE001
        print(f"jlbc-search: could not start the queue tidy ({e}).",
              file=sys.stderr, flush=True)


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
    # Every exit path below (both early returns and the final one) must close
    # the /locate route's cached PyMuPDF handles — a handle left open on
    # Windows blocks a re-ingest from overwriting the cached PDF, and a server
    # restart is the only place that reliably happens for every document ever
    # opened, not just the ones evicted from the bounded cache in-process.
    try:
        from app.machine_config import ingest_enabled
        from ingest.worker import ensure_started

        # Spec T13's one-time tidy: move already-finished job files into
        # `jobs/done/` so the queue reads outstanding work instead of 7,104 rows
        # of history. Measured on the live data dir 2026-08-13: 7,118 files, of
        # which 14 needed anybody's attention.
        #
        # WHY before the two early returns below: this is about the queue FOLDER,
        # not about processing uploads. A machine with ingest switched off still
        # DISPLAYS the queue, and is still reading every one of those files to do
        # it. Sweeping only on the ingest machine would leave the page slow on the
        # other ~19, and slow for everyone in the entirely normal window where no
        # machine has ingest switched on.
        #
        # WHY a thread: the first sweep on the office share moves ~7,104 files and
        # the launcher opens a browser tab the moment the port answers, so seconds
        # of blocked startup read as "the app is broken". Later runs see only
        # outstanding work and failures -- tens of files.
        _start_archive_sweep()

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
                "jlbc-search: this computer is not set to process uploads, so the "
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
                f"jlbc-search: the ingest queue did not start ({type(e).__name__}: {e}). "
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
    finally:
        from app.routes.pdf import close_locate_cache

        close_locate_cache()


DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp" / "dist"
# Sentinel: distinguishes "caller passed nothing" (use the real webapp/dist)
# from "caller explicitly passed None" (simulate an unbuilt UI). A plain None
# default would conflate the two.
_MISSING = object()


class DataDirBody(BaseModel):
    """Body of POST /api/config/data-dir.

    Module-level, not nested inside create_app: this file has
    `from __future__ import annotations`, so a route parameter's type is
    resolved from a STRING against the function's module globals. A class
    defined inside create_app is a local, invisible to that lookup — the
    route silently read as taking no body at all (a bare 422 "field
    required: body"), never exercised by any test until this one.
    """

    path: str = ""


def create_app(
    *, provider: SearchProvider | None = None,
    static_dir: Path | None | object = _MISSING,
    session_factory: Callable[..., object] | None = None,
    ingest_worker: object | None = _MISSING,
) -> FastAPI:
    app = FastAPI(title="JLBC Search", lifespan=_lifespan)
    # Explicit None check, not `provider or ...`: an injected provider object
    # could be falsy (e.g. a fake defining __len__/__bool__) and get silently
    # swapped for the default, which would be a baffling test failure.
    app.state.provider = _default_provider() if provider is None else provider
    _install_reprobe(app)
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
    app.include_router(issues_router)
    app.include_router(pdf_router)
    app.include_router(upload_router)
    app.include_router(jobs_router)
    app.include_router(books_router)
    app.include_router(books_missing_router)
    # The admin's whole-report ("Full report") link table. Gated by
    # `Depends(require_admin)` on every route, and registered here — above
    # the `/{path:path}` catch-all — for the reason stated at the top of
    # this block.
    app.include_router(book_formats_router)
    # The upload page's agency picker (ungated read) plus the admin's
    # add/remove for agencies the shipped catalog does not carry.
    app.include_router(agencies_router)
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

        reprobe = getattr(app.state, "reprobe", None)
        if reprobe is not None:
            reprobe()
        report = health_detail()
        # Whether the Choose folder… button can render at all (spec §2.5) —
        # Linux/macOS have no Windows Forms dialog, so the button is simply
        # absent there rather than failing when clicked.
        report["can_pick"] = folder_picker.supported()
        return report

    @app.post("/api/config/pick-folder")
    def pick_folder_route():
        """Open Windows' folder dialog and return the choice (spec §2.5).

        Does NOT save it — the page submits the chosen path through
        /api/config/data-dir, the existing validate-and-save route, so
        nothing here can bypass that validation.
        """
        if not folder_picker.supported():
            return {"supported": False, "path": None}
        try:
            return {"supported": True, "path": folder_picker.pick_folder()}
        except folder_picker.PickerBusy:
            raise HTTPException(
                status_code=409, detail="The folder window is already open."
            )

    @app.post("/api/config/data-dir")
    def set_data_dir_route(body: DataDirBody):
        """Repoint THIS machine at the shared folder (S18). No auth — the
        app is unusable when this fires. Takes effect NOW: the launcher
        reuses a running server, so 'reopen the app' would be a no-op."""
        from app.machine_config import set_data_dir, validate_data_dir

        problem = validate_data_dir(body.path)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        resolved = set_data_dir(body.path)
        app.state.reprobe(force=True)
        return {"path": str(resolved)}

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
            "<h1>JLBC Search</h1><p>UI not built yet — run: "
            "cd webapp && npm run build</p>"
        )

    return app
