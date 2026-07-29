"""Single-process app server (spec S1).

Serves the built SPA (webapp/dist) plus the JSON API. Distinct from
retrieval/api.py (the legacy Phase-1c sidecar on 9200): this is the
consolidated app's front door, default port 9300. Static serving uses
an SPA fallback: any non-/api, non-/health path returns index.html so
client-side routing works on refresh/deep links.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
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
    app.state.provider = provider or StubSearchProvider()

    app.include_router(search_router)
    app.include_router(fiscal_notes_router)

    @app.get("/health")
    def health():
        return {"ok": True, "provider": app.state.provider.name}

    resolved = DEFAULT_STATIC_DIR if static_dir is _MISSING else static_dir

    @app.get("/{path:path}")
    def spa(path: str):
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
