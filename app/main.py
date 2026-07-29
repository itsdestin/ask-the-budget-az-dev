"""Single-process app server (spec S1).

Serves the built SPA (webapp/dist) plus the JSON API. Distinct from
retrieval/api.py (the legacy Phase-1c sidecar on 9200): this is the
consolidated app's front door, default port 9300. Static serving uses
an SPA fallback: any unmatched path that is not under /api/ returns
index.html so client-side routing works on refresh/deep links, while
unmatched /api/ paths get a JSON 404 instead.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.routes.fiscal_notes import router as fiscal_notes_router
from app.routes.search import router as search_router
from app.search_provider import SearchProvider, StubSearchProvider

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "webapp" / "dist"
# Sentinel: distinguishes "caller passed nothing" (use the real webapp/dist)
# from "caller explicitly passed None" (simulate an unbuilt UI). A plain None
# default would conflate the two.
_MISSING = object()


def create_app(
    *, provider: SearchProvider | None = None,
    static_dir: Path | None | object = _MISSING,
) -> FastAPI:
    app = FastAPI(title="JLBC Insight")
    # Explicit None check, not `provider or ...`: an injected provider object
    # could be falsy (e.g. a fake defining __len__/__bool__) and get silently
    # swapped for the stub, which would be a baffling test failure.
    app.state.provider = StubSearchProvider() if provider is None else provider

    # Route-registration order is load-bearing: FastAPI matches in registration
    # order, so the `/{path:path}` catch-all below MUST be registered after
    # every real router or it swallows /api/* and /health.
    app.include_router(search_router)
    app.include_router(fiscal_notes_router)

    @app.get("/health")
    def health():
        return {"ok": True, "provider": app.state.provider.name}

    resolved = DEFAULT_STATIC_DIR if static_dir is _MISSING else static_dir

    @app.get("/{path:path}")
    def spa(path: str):
        # Unmatched /api/ paths must fail as a JSON 404. Falling through to
        # index.html would hand fetch() callers HTML, and JSON.parse would
        # report the useless "Unexpected token '<'" instead of a clear 404.
        if path.startswith("api/"):
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
