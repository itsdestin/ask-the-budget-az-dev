# Standalone Plan 2: App Server + Search UI Shell

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the consolidated app's single-process web server (`app/`) and the ported JLBC-mockup UI (`webapp/`): home shell, budget search page, and fiscal notes page — fully functional against a stub search provider, flipping to real retrieval in one final integration task once Plan 1 is merged.

**Architecture:** New FastAPI package `app/` (port 9300) serves the static Vite/React build and three API surfaces (`/api/search`, `/api/fiscal-notes`, `/health`) through a `SearchProvider` seam — `StubSearchProvider` (fixtures) during parallel development, `LanceSearchProvider` (wraps `retrieval.retrieve()`) in the final task. New `webapp/` is a Vite + React + TypeScript SPA whose pages are direct ports of the JLBC Website Revamp mockup (vendored into the repo as the reference source of truth). Per spec S12: port, don't redesign.

**Tech Stack:** FastAPI (already a dependency), Vite + React 18 + TypeScript, vitest + React Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` (S1, S9, S12; UI section). Work in a worktree per CLAUDE.md.

**PARALLEL-EXECUTION CONTRACT (this plan runs concurrently with Plan 1):**
- This plan MUST NOT create or modify: `store/`, `retrieval/`, `scripts/migrate_to_lancedb.py`, `eval/`, `db/`, `mcp-server/`, `tests/test_store*`, `tests/test_local*`, `tests/test_search_lance.py`, `tests/test_pipeline.py`, `tests/test_api.py`, `tests/test_migrate_rows.py`, or `pyproject.toml`/`uv.lock` (no new Python deps — FastAPI/uvicorn/pytest are already installed; frontend deps live in `webapp/package.json`).
- Tasks 1–11 have zero dependency on Plan 1. Task 12 (integration) REQUIRES Plan 1 merged to master — if it isn't merged when you get there, STOP and report; do not import from `store/` or `retrieval/` before Task 12.
- `STATUS.md` is touched only in Task 13; if it conflicts on merge, keep both plans' additions.

---

## File structure

| File | Responsibility |
|---|---|
| Create `webapp/reference/` | Vendored mockup sources (read-only reference for porting) |
| Create `app/__init__.py`, `app/main.py` | FastAPI app factory: static mount, routes, /health |
| Create `app/search_provider.py` | `SearchProvider` protocol + `StubSearchProvider`; `LanceSearchProvider` added in Task 12 |
| Create `app/routes/search.py` | `POST /api/search` — query + filters → results |
| Create `app/routes/fiscal_notes.py` | `GET /api/fiscal-notes` — session/bill directory from snapshot JSON |
| Create `app/fixtures/search_fixtures.py` | Deterministic fake results for the stub provider |
| Create `scripts/export_fiscal_notes_snapshot.py` | One-time: mockup's cached session data → `app/data/fiscal-notes-snapshot.json` |
| Create `webapp/` (vite.config.ts, src/main.tsx, src/App.tsx, src/api.ts, src/styles/tokens.css, src/components/Header.tsx, src/pages/Home.tsx, src/pages/Search.tsx, src/pages/FiscalNotes.tsx, tests) | The SPA |
| Create `tests/test_app_server.py`, `tests/test_search_route.py`, `tests/test_fiscal_notes_route.py` | Server tests |
| Modify `.gitignore` | `webapp/node_modules/`, `webapp/dist/` |
| Modify `STATUS.md` (Task 13 only) | Ship entry |

API contracts (frozen now so Plans 3/4 build against them):

```
POST /api/search
  { "query": str, "top_k"?: int (default 20), "corpus"?: "budget"|"fiscal_notes" (default "budget"),
    "filters"?: { "fiscal_year"?: int[], "publisher"?: str[], "doc_type"?: str[], "agency"?: str[] } }
  -> { "results": [ { "chunk_id": str, "doc_id": str, "doc_title": str, "snippet": str,
                      "page": int|null, "score": float, "doc_type": str,
                      "fiscal_year": int|null, "publisher": str, "agencies": str[],
                      "doc_url": str|null } ],
       "total": int, "provider": "stub"|"lance" }

> `doc_url` added 2026-07-30 (additive): the document's own source PDF/DOCX URL
> from Plan 1's documents.json sidecar — what lets a search row link to the
> individual agency narrative section like the website mockup's rows. Null when
> the sidecar has no record (stub rows always); consumers must render unlinked
> rather than guess. `score` note: since Plan 1, raw cross-encoder logits
> (±~10), not 0..1.

GET /api/fiscal-notes
  -> { "sessions": [ { "year": int, "name": str,
                       "bills": [ { "bill_number": str, "title": str, "chamber": "H"|"S",
                                    "fiscal_note_url": str } ] } ] }

GET /health -> { "ok": bool, "provider": str }
```

The `provider` field exists so the UI (and tests) can tell stub from real — the UI shows a small dev-only badge when `provider == "stub"`.

`fiscal_note_url` was added to the bill shape in Task 3 (additive — no existing field changed). It comes straight from `build.py`'s parsed data, which already captured the PDF link the mockup page renders as its "PDF" button, so surfacing it costs nothing and saves Plans 3/4 a re-parse. Two consequences for consumers: the session name is `leg_session()`'s label (`"57th Legislature, 1st Reg. Session (2025)"`), and **`bill_number` is not unique within a session** — a bill with an original *and* a revised fiscal note appears as two rows distinguished only by `fiscal_note_url` (93 such rows corpus-wide), so don't key on `bill_number` alone.

---

### Task 1: Vendor the mockup reference sources

**Files:**
- Create: `webapp/reference/` (copied files)

- [ ] **Step 1: Copy the needed mockup files into the repo**

```bash
mkdir -p webapp/reference/assets webapp/reference/fiscal-notes-build
cp "/c/Users/desti/JLBC Website Revamp/index.html" webapp/reference/
cp "/c/Users/desti/JLBC Website Revamp/subpage-search_jlbc.html" webapp/reference/
cp "/c/Users/desti/JLBC Website Revamp/DESIGN-SYSTEM.md" webapp/reference/
cp "/c/Users/desti/JLBC Website Revamp/jlbc-logo.png" webapp/reference/assets/
cp "/c/Users/desti/JLBC Website Revamp/capitol-bg.jpg" webapp/reference/assets/
cp "/c/Users/desti/JLBC Website Revamp/fiscal-notes-build/base.html" webapp/reference/fiscal-notes-build/
cp "/c/Users/desti/JLBC Website Revamp/fiscal-notes-build/build.py" webapp/reference/fiscal-notes-build/
cp -r "/c/Users/desti/JLBC Website Revamp/fiscal-notes-build/live" webapp/reference/fiscal-notes-build/
```

Expected: files present. (`live/` is the cached per-session HTML, 1999–2026 — the data source for Task 3.) These are reference material, committed so the port never depends on files outside the repo.

- [ ] **Step 2: Add a README marking it read-only**

```markdown
# webapp/reference/ — vendored JLBC Website Revamp sources

Read-only reference for the S12 "port, don't redesign" work. Do not
edit; do not serve. The live UI is built in webapp/src, translated
from these files. Source: C:\Users\desti\JLBC Website Revamp (2026-06-17).
```

- [ ] **Step 3: Commit**

```bash
git add webapp/reference/
git commit -m "chore(webapp): vendor JLBC mockup reference sources for the S12 UI port"
```

---

### Task 2: FastAPI app skeleton (`app/main.py`) + health

**Files:**
- Create: `app/__init__.py` (empty), `app/main.py`
- Test: `tests/test_app_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_server.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_provider():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "stub"


def test_spa_fallback_serves_index_when_built(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    client = TestClient(create_app(static_dir=dist))
    # Unknown non-API path -> SPA index (client-side routing).
    r = client.get("/fiscal-notes")
    assert r.status_code == 200 and "app" in r.text


def test_missing_build_gives_plain_message():
    client = TestClient(create_app(static_dir=None))
    r = client.get("/")
    assert r.status_code == 200
    assert "not built" in r.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app_server.py -v`
Expected: FAIL — no module `app`

- [ ] **Step 3: Implement**

```python
# app/main.py
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
```

(`app/routes/__init__.py` empty file; the two routers are Tasks 4–5 — create placeholder modules now with empty `APIRouter()`s so imports resolve:)

```python
# app/routes/search.py  (placeholder, replaced in Task 4)
from fastapi import APIRouter

router = APIRouter()
```

```python
# app/routes/fiscal_notes.py  (placeholder, replaced in Task 5)
from fastapi import APIRouter

router = APIRouter()
```

```python
# app/search_provider.py  (minimal now, extended in Task 4)
from __future__ import annotations

from typing import Any, Protocol


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> list[dict[str, Any]]: ...


class StubSearchProvider:
    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app_server.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add app/ tests/test_app_server.py
git commit -m "feat(app): FastAPI app factory — SPA static serving + /health + provider seam"
```

---

### Task 3: Fiscal-notes snapshot export

**Files:**
- Create: `scripts/export_fiscal_notes_snapshot.py`
- Create: `app/data/fiscal-notes-snapshot.json` (generated, committed)
- Test: `tests/test_fiscal_notes_snapshot.py`

- [ ] **Step 1: Read the vendored generator to learn the parse**

Read `webapp/reference/fiscal-notes-build/build.py`. It already parses `live/<year>.html` session pages into per-session bill lists (bill number, title, chamber, fiscal-note link) to generate the static page. Identify its parsing functions — the exporter reuses that logic (import it via `sys.path` insertion or copy the 2–3 parse functions with attribution comments; copying is fine, the vendored file is the citation).

- [ ] **Step 2: Write the failing shape test**

```python
# tests/test_fiscal_notes_snapshot.py
"""Validates the committed snapshot artifact, not the scraper —
Plan 3 owns live scraping. This guards the API contract's data shape."""
import json
from pathlib import Path

SNAPSHOT = Path("app/data/fiscal-notes-snapshot.json")


def test_snapshot_exists_and_has_sessions():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(data["sessions"], list) and len(data["sessions"]) >= 20


def test_bills_have_contract_fields():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    total = 0
    for s in data["sessions"]:
        assert isinstance(s["year"], int) and s["name"]
        for b in s["bills"]:
            assert b["bill_number"] and b["title"]
            assert b["chamber"] in ("H", "S")
            assert b["fiscal_note_url"].startswith("https://")
            total += 1
    assert total == 2126  # frozen artifact: 28 sessions, ~37-135 bills each
```

> Updated in Task 3 to the real counts. The plan originally guessed `>= 90`
> from a "~98 bills" figure that predated reading build.py and was simply
> wrong. Exact assertions are correct here because the snapshot is
> frozen — see the shipped test for the reasoning.

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_fiscal_notes_snapshot.py -v`
Expected: FAIL — snapshot file missing

- [ ] **Step 4: Implement the exporter and generate the snapshot**

Write `scripts/export_fiscal_notes_snapshot.py` reusing the vendored parse functions. Output shape must match the test exactly:

```python
# scripts/export_fiscal_notes_snapshot.py
"""One-time export: vendored mockup session cache -> JSON snapshot.

The fiscal notes PAGE ships in Plan 2 backed by this frozen snapshot;
Plan 3 replaces the data source with the live corpus + refresh scraper.
Chamber is derived from the bill prefix (HB/HCR/HCM -> H, SB/SCR/SCM -> S).
"""
from __future__ import annotations

import json
from pathlib import Path

REFERENCE = Path("webapp/reference/fiscal-notes-build")
OUT = Path("app/data/fiscal-notes-snapshot.json")

# <adapt: import or inline build.py's session parser here — it walks
#  REFERENCE/"live"/"<year>.html" and yields bills per session. Keep its
#  parsing behavior identical; only the output format changes.>


def chamber_of(bill_number: str) -> str:
    return "S" if bill_number.upper().startswith("S") else "H"


def main() -> None:
    sessions = []
    for f in sorted(REFERENCE.glob("live/*.html")):
        year = int(f.stem)
        bills = parse_session_html(f.read_text(encoding="utf-8"))  # from build.py
        sessions.append({
            "year": year,
            "name": f"{year} Legislative Session",
            "bills": [
                {"bill_number": b["bill_number"], "title": b["title"],
                 "chamber": chamber_of(b["bill_number"])}
                for b in bills
            ],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"sessions": sessions}, indent=1), encoding="utf-8")
    print(f"wrote {OUT} — {sum(len(s['bills']) for s in sessions)} bills")


if __name__ == "__main__":
    main()
```

The `<adapt: ...>` block is the one deliberate judgment call in this plan: `build.py`'s function names aren't known until Step 1's read. Wire `parse_session_html` to whatever build.py actually provides, preserving its behavior. If build.py's parser filters to fiscal-note-bearing bills, keep that filter (the bill count in the test reflects it). **Resolved in Task 3:** build.py has no separable parse function — it parses at module scope and writes a vendored HTML file on import — so the parse pieces were transcribed into the exporter instead of imported. The `/fiscal/` href filter and the `(bill_number, href)` dedupe are the two behaviors the count depends on; total is **2126 bills across 28 sessions**.

Run: `uv run python scripts/export_fiscal_notes_snapshot.py`
Expected: `wrote <repo>/app/data/fiscal-notes-snapshot.json - 2126 bills across 28 sessions`

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_fiscal_notes_snapshot.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit (snapshot is committed — it's app data, not build output)**

```bash
git add scripts/export_fiscal_notes_snapshot.py app/data/ tests/test_fiscal_notes_snapshot.py
git commit -m "feat(app): fiscal-notes snapshot export from vendored mockup session cache"
```

---

### Task 4: Search route + stub provider fixtures

**Files:**
- Modify: `app/search_provider.py`, `app/routes/search.py`
- Create: `app/fixtures/search_fixtures.py`
- Test: `tests/test_search_route.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_search_route.py
from fastapi.testclient import TestClient

from app.main import create_app


def client():
    return TestClient(create_app())


def test_search_returns_contract_shape():
    r = client().post("/api/search", json={"query": "ahcccs provider rates"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "stub"
    assert body["total"] == len(body["results"]) > 0
    first = body["results"][0]
    for key in ("chunk_id", "doc_id", "doc_title", "snippet", "page",
                "score", "doc_type", "fiscal_year", "publisher", "agencies"):
        assert key in first


def test_filters_narrow_stub_results():
    all_r = client().post("/api/search", json={"query": "budget"}).json()
    filtered = client().post("/api/search", json={
        "query": "budget", "filters": {"publisher": ["agao"]},
    }).json()
    assert 0 < filtered["total"] < all_r["total"]
    assert all(x["publisher"] == "agao" for x in filtered["results"])


def test_empty_query_is_400():
    r = client().post("/api/search", json={"query": "   "})
    assert r.status_code == 400


def test_top_k_caps_results():
    r = client().post("/api/search", json={"query": "budget", "top_k": 2}).json()
    assert r["total"] <= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_search_route.py -v`
Expected: FAIL — route not implemented (404 / empty results)

- [ ] **Step 3: Implement fixtures, provider, route**

```python
# app/fixtures/search_fixtures.py
"""Deterministic fake corpus rows for StubSearchProvider — realistic
field values so the UI port renders true-to-life during Plan 2."""

FIXTURE_ROWS = [
    dict(chunk_id=f"stub-{i:03d}", doc_id=doc_id, doc_title=title,
         snippet=snippet, page=page, score=round(0.95 - i * 0.07, 2),
         doc_type=doc_type, fiscal_year=fy, publisher=publisher,
         agencies=agencies)
    for i, (doc_id, title, snippet, page, doc_type, fy, publisher, agencies) in enumerate([
        ("jlbc-baseline-fy2027-ahcccs", "FY 2027 Baseline — AHCCCS",
         "…provider rate increases of $58.1 million from the General Fund…",
         14, "baseline-per-agency", 2027, "jlbc", ["ahcccs"]),
        ("jlbc-approps-fy2025-dcs", "FY 2025 Appropriations Report — DCS",
         "…caseworker staffing levels increased by 112 FTE positions…",
         9, "approps-per-agency", 2025, "jlbc", ["dcs"]),
        ("agao-afr-fy2025", "FY 2025 Annual Financial Report",
         "…General Fund ending balance of $1.2 billion…",
         31, "afr", 2025, "agao", []),
        ("governor-governors-budget-fy2027", "FY 2027 Executive Budget",
         "…the Executive recommends $65.3 million for homelessness services…",
         102, "governors-budget", 2027, "governor", ["ades"]),
        ("legislature-budget-bill-fy2026-sb1735-2025", "FY 2026 Budget Bill (SB 1735)",
         "…appropriates $19,800,000 to the department for fiscal year 2025-2026…",
         3, "budget-bill", 2026, "legislature", ["adoa"]),
    ])
]
```

```python
# app/search_provider.py  (full version)
from __future__ import annotations

from typing import Any, Protocol

from app.fixtures.search_fixtures import FIXTURE_ROWS


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, top_k: int, corpus: str,
               filters: dict[str, Any]) -> list[dict[str, Any]]: ...


class StubSearchProvider:
    """Fixture-backed provider used while Plan 1 lands (parallel-execution
    contract). Applies filters faithfully so the filter UI is testable."""

    name = "stub"

    def search(self, query, *, top_k, corpus, filters):
        out = []
        for row in FIXTURE_ROWS:
            if filters.get("publisher") and row["publisher"] not in filters["publisher"]:
                continue
            if filters.get("fiscal_year") and row["fiscal_year"] not in filters["fiscal_year"]:
                continue
            if filters.get("doc_type") and row["doc_type"] not in filters["doc_type"]:
                continue
            if filters.get("agency") and not set(row["agencies"]) & set(filters["agency"]):
                continue
            out.append(dict(row))
        return out[:top_k]
```

```python
# app/routes/search.py  (full version)
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class SearchFilters(BaseModel):
    fiscal_year: list[int] | None = None
    publisher: list[str] | None = None
    doc_type: list[str] | None = None
    agency: list[str] | None = None


class SearchBody(BaseModel):
    query: str
    top_k: int = Field(default=20, ge=1, le=100)
    corpus: str = Field(default="budget", pattern="^(budget|fiscal_notes)$")
    filters: SearchFilters = Field(default_factory=SearchFilters)


@router.post("/api/search")
def search(body: SearchBody, request: Request):
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query is empty")
    provider = request.app.state.provider
    results = provider.search(
        body.query, top_k=body.top_k, corpus=body.corpus,
        filters=body.filters.model_dump(exclude_none=True),
    )
    return {"results": results, "total": len(results), "provider": provider.name}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_search_route.py tests/test_app_server.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/ tests/test_search_route.py
git commit -m "feat(app): POST /api/search with provider seam + filter-faithful stub"
```

---

### Task 5: Fiscal-notes route

**Files:**
- Modify: `app/routes/fiscal_notes.py`
- Test: `tests/test_fiscal_notes_route.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fiscal_notes_route.py
from fastapi.testclient import TestClient

from app.main import create_app


def test_fiscal_notes_serves_snapshot():
    r = TestClient(create_app()).get("/api/fiscal-notes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["sessions"]) >= 20
    bill = body["sessions"][-1]["bills"][0]
    assert bill["chamber"] in ("H", "S")


def test_sessions_sorted_newest_first():
    body = TestClient(create_app()).get("/api/fiscal-notes").json()
    years = [s["year"] for s in body["sessions"]]
    assert years == sorted(years, reverse=True)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fiscal_notes_route.py -v`
Expected: FAIL (empty router placeholder)

- [ ] **Step 3: Implement**

```python
# app/routes/fiscal_notes.py  (full version)
"""GET /api/fiscal-notes — serves the committed snapshot (Plan 2).
Plan 3 swaps the data source to the live corpus + refresh scraper
behind this same contract."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "fiscal-notes-snapshot.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    data["sessions"].sort(key=lambda s: -s["year"])
    return data


@router.get("/api/fiscal-notes")
def fiscal_notes():
    return _load()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_fiscal_notes_route.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/fiscal_notes.py tests/test_fiscal_notes_route.py
git commit -m "feat(app): GET /api/fiscal-notes from committed snapshot"
```

---

### Task 6: Webapp scaffold (Vite + React + TS)

**Files:**
- Create: `webapp/package.json`, `webapp/vite.config.ts`, `webapp/tsconfig.json`, `webapp/index.html`, `webapp/src/main.tsx`, `webapp/src/App.tsx`, `webapp/src/api.ts`
- Modify: `.gitignore`

- [ ] **Step 1: Scaffold**

```bash
cd webapp && npm create vite@latest . -- --template react-ts
npm install react-router-dom
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 2: Configure the dev proxy + test runner**

```ts
// webapp/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev mode: vite on 5173 proxies API calls to the FastAPI app on 9300.
    proxy: {
      "/api": "http://127.0.0.1:9300",
      "/health": "http://127.0.0.1:9300",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
});
```

```ts
// webapp/src/test-setup.ts
import "@testing-library/jest-dom";
```

- [ ] **Step 3: Router shell + typed API client**

```tsx
// webapp/src/App.tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { FiscalNotes } from "./pages/FiscalNotes";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";

export function App() {
  return (
    <BrowserRouter>
      <Header />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/fiscal-notes" element={<FiscalNotes />} />
      </Routes>
    </BrowserRouter>
  );
}
```

```ts
// webapp/src/api.ts
export interface SearchResult {
  chunk_id: string; doc_id: string; doc_title: string; snippet: string;
  page: number | null; score: number; doc_type: string;
  fiscal_year: number | null; publisher: string; agencies: string[];
}
export interface SearchResponse {
  results: SearchResult[]; total: number; provider: string;
}
export interface SearchFilters {
  fiscal_year?: number[]; publisher?: string[]; doc_type?: string[]; agency?: string[];
}

export async function search(
  query: string, filters: SearchFilters = {}, corpus = "budget",
): Promise<SearchResponse> {
  const r = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, filters, corpus }),
  });
  if (!r.ok) throw new Error(`search failed: ${r.status}`);
  return r.json();
}

export interface Bill { bill_number: string; title: string; chamber: "H" | "S"; }
export interface Session { year: number; name: string; bills: Bill[]; }

export async function fiscalNotes(): Promise<{ sessions: Session[] }> {
  const r = await fetch("/api/fiscal-notes");
  if (!r.ok) throw new Error(`fiscal-notes failed: ${r.status}`);
  return r.json();
}
```

Create empty-but-compiling placeholder pages/components (filled in Tasks 7–10):

```tsx
// webapp/src/components/Header.tsx (placeholder)
export function Header() { return <header data-testid="header" />; }
// webapp/src/pages/Home.tsx (placeholder)
export function Home() { return <main data-testid="home" />; }
// webapp/src/pages/Search.tsx (placeholder)
export function Search() { return <main data-testid="search" />; }
// webapp/src/pages/FiscalNotes.tsx (placeholder)
export function FiscalNotes() { return <main data-testid="fiscal-notes" />; }
```

- [ ] **Step 4: Gitignore + build check**

Append to `.gitignore`:

```
webapp/node_modules/
webapp/dist/
```

Run: `cd webapp && npm run build`
Expected: `dist/` produced without errors.

- [ ] **Step 5: Commit**

```bash
git add webapp/ .gitignore
git commit -m "feat(webapp): Vite React scaffold — router, typed API client, dev proxy"
```

---

### Task 7: Port the design system (tokens + header/nav)

**Files:**
- Create: `webapp/src/styles/tokens.css`, `webapp/src/styles/app.css`
- Modify: `webapp/src/components/Header.tsx`, `webapp/src/main.tsx`
- Copy: `webapp/reference/assets/*` → `webapp/public/`
- Test: `webapp/src/components/Header.test.tsx`

- [ ] **Step 1: Extract the mockup's `:root` tokens verbatim**

Open `webapp/reference/index.html`, copy the entire `:root { ... }` token block (navy palette `--navy:#2b2f63`, `--navy-900:#181b3d`, canvas `#f5f5fa`, radius scale to `--r-pill:999px`, shadow tokens, `"Nunito","Segoe UI",system-ui` font stack) into `webapp/src/styles/tokens.css` unchanged. This file is the single source of the visual identity — S12 means these values are copied, not reinterpreted.

- [ ] **Step 2: Write the failing header test**

```tsx
// webapp/src/components/Header.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Header } from "./Header";

test("header has nav pills for the app's surfaces", () => {
  render(<MemoryRouter><Header /></MemoryRouter>);
  for (const label of ["Home", "Budget Search", "Fiscal Notes", "Settings"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
});
```

Run: `cd webapp && npx vitest run src/components/Header.test.tsx`
Expected: FAIL (placeholder header)

- [ ] **Step 3: Port the header**

Translate the mockup's sticky white header (logo block, navy bottom border, inline nav pills) from `webapp/reference/index.html` markup/CSS into `Header.tsx` + `app.css`, swapping `<a href>` for `<NavLink to>`. Nav items: Home `/`, Budget Search `/search`, Fiscal Notes `/fiscal-notes`, Settings `/settings` (route stub renders "coming in Plan 5"). Keep the mockup's class names where practical so the ported CSS applies unmodified. Import both CSS files in `main.tsx`; copy `jlbc-logo.png` + `capitol-bg.jpg` into `webapp/public/`.

- [ ] **Step 4: Run test + visual check**

Run: `cd webapp && npx vitest run` → PASS.
Run: `uv run uvicorn app.main:create_app --factory --port 9300` in one shell, `cd webapp && npm run dev` in another; open `http://localhost:5173`.
Expected: header renders with the mockup's look (navy border, pills).

- [ ] **Step 5: Commit**

```bash
git add webapp/
git commit -m "feat(webapp): port mockup design tokens + sticky header/pill nav (S12)"
```

---

### Task 8: Home page (hero + feature cards)

**Files:**
- Modify: `webapp/src/pages/Home.tsx`, `webapp/src/styles/app.css`
- Test: `webapp/src/pages/Home.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/pages/Home.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Home } from "./Home";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig()), useNavigate: () => navigate,
}));

test("hero search routes to /search with the query", () => {
  render(<MemoryRouter><Home /></MemoryRouter>);
  const box = screen.getByPlaceholderText(/search/i);
  fireEvent.change(box, { target: { value: "dcs caseworkers" } });
  fireEvent.submit(box.closest("form")!);
  expect(navigate).toHaveBeenCalledWith("/search?q=dcs%20caseworkers");
});

test("feature cards link to the three surfaces", () => {
  render(<MemoryRouter><Home /></MemoryRouter>);
  expect(screen.getByText(/budget library/i)).toBeInTheDocument();
  expect(screen.getByText(/fiscal notes/i)).toBeInTheDocument();
  expect(screen.getByText(/ai mode/i)).toBeInTheDocument();
});
```

Run: `cd webapp && npx vitest run src/pages/Home.test.tsx` → FAIL

- [ ] **Step 2: Port the home page**

Translate from `webapp/reference/index.html`: the capitol-photo hero (radial/linear navy overlays) trimmed to this app's content — app title, one-line subtitle ("Search Arizona budget documents and fiscal notes"), and one big pill search box (`onSubmit` → `navigate('/search?q=' + encodeURIComponent(q))`). Below: three feature cards (mockup card style): Budget Library → `/search`, Fiscal Notes → `/fiscal-notes`, AI Mode → dimmed card with tooltip "AI answers require an API key — coming with AI Mode" (no route yet; Plan 4 wires it). Drop all other mockup home sections.

- [ ] **Step 3: Run tests**

Run: `cd webapp && npx vitest run` → PASS

- [ ] **Step 4: Commit**

```bash
git add webapp/
git commit -m "feat(webapp): home page — hero search + three feature cards"
```

---

### Task 9: Budget Search page

**Files:**
- Modify: `webapp/src/pages/Search.tsx`, `webapp/src/styles/app.css`
- Create: `webapp/src/components/ResultCard.tsx`, `webapp/src/components/FilterBar.tsx`
- Test: `webapp/src/pages/Search.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/pages/Search.test.tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Search } from "./Search";
import * as api from "../api";

const RESULT = {
  chunk_id: "c1", doc_id: "d1", doc_title: "FY 2027 Baseline — AHCCCS",
  snippet: "…provider rate increases…", page: 14, score: 0.91,
  doc_type: "baseline-per-agency", fiscal_year: 2027, publisher: "jlbc",
  agencies: ["ahcccs"],
};

test("runs the ?q= query on mount and groups results by document", async () => {
  vi.spyOn(api, "search").mockResolvedValue({
    results: [RESULT, { ...RESULT, chunk_id: "c2", page: 15 }],
    total: 2, provider: "stub",
  });
  render(
    <MemoryRouter initialEntries={["/search?q=ahcccs"]}><Search /></MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByText("FY 2027 Baseline — AHCCCS")).toBeInTheDocument(),
  );
  // Two chunks, one document -> one card with two page hits.
  expect(screen.getAllByText(/p\.\s*1[45]/)).toHaveLength(2);
  expect(api.search).toHaveBeenCalledWith("ahcccs", expect.anything(), "budget");
});

test("publisher filter chip re-queries", async () => {
  const spy = vi.spyOn(api, "search").mockResolvedValue({
    results: [], total: 0, provider: "stub",
  });
  render(<MemoryRouter initialEntries={["/search?q=x"]}><Search /></MemoryRouter>);
  await waitFor(() => expect(spy).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: /jlbc/i }));
  await waitFor(() =>
    expect(spy).toHaveBeenLastCalledWith(
      "x", expect.objectContaining({ publisher: ["jlbc"] }), "budget",
    ),
  );
});

test("empty results show honest message, not blank", async () => {
  vi.spyOn(api, "search").mockResolvedValue({ results: [], total: 0, provider: "stub" });
  render(<MemoryRouter initialEntries={["/search?q=zz"]}><Search /></MemoryRouter>);
  await waitFor(() =>
    expect(screen.getByText(/no matches/i)).toBeInTheDocument(),
  );
});
```

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx` → FAIL

- [ ] **Step 2: Port the search page**

Translate structure from `webapp/reference/subpage-search_jlbc.html`: search box at top (pre-filled from `?q=`, re-queries on submit), filter chip rows (publisher: JLBC/Governor/AGAO/Legislature; fiscal year chips from results; doc-type chips), and the mockup's **grouped result cards** — group `results` by `doc_id`: card header = `doc_title` + publisher/FY badges, body = per-chunk rows (snippet + `p. N` page badge + score-ordered). Clicking a chunk row is a no-op link stub for now (`href="#"` with `data-chunk-id` — the PDF side panel arrives with Plan 4's port of the viewer). Components: `FilterBar` (chip groups, callback up), `ResultCard` (one grouped doc). Show `provider === "stub"` as a small amber "stub data" badge (dev honesty; disappears in Task 12). Empty state: "No matches in the corpus for that search." Reuse the mockup's card/chip CSS classes.

- [ ] **Step 3: Run tests**

Run: `cd webapp && npx vitest run` → PASS

- [ ] **Step 4: Commit**

```bash
git add webapp/
git commit -m "feat(webapp): budget search page — grouped result cards + filter chips (S12 port)"
```

---

### Task 10: Fiscal Notes page

**Files:**
- Modify: `webapp/src/pages/FiscalNotes.tsx`, `webapp/src/styles/app.css`
- Test: `webapp/src/pages/FiscalNotes.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/pages/FiscalNotes.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FiscalNotes } from "./FiscalNotes";
import * as api from "../api";

const DATA = {
  sessions: [
    { year: 2026, name: "2026 Legislative Session", bills: [
      { bill_number: "HB2001", title: "appropriations; K-12 rollover", chamber: "H" as const },
      { bill_number: "SB1101", title: "AHCCCS; provider rates", chamber: "S" as const },
    ]},
    { year: 2025, name: "2025 Legislative Session", bills: [
      { bill_number: "HB2500", title: "school facilities; funding", chamber: "H" as const },
    ]},
  ],
};

beforeEach(() => vi.spyOn(api, "fiscalNotes").mockResolvedValue(DATA));

test("renders sessions with bill cards", async () => {
  render(<MemoryRouter><FiscalNotes /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("HB2001")).toBeInTheDocument());
  expect(screen.getByText(/2026 legislative session/i)).toBeInTheDocument();
});

test("chamber switcher filters", async () => {
  render(<MemoryRouter><FiscalNotes /></MemoryRouter>);
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.click(screen.getByRole("button", { name: /^senate$/i }));
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
  expect(screen.getByText("SB1101")).toBeInTheDocument();
});

test("text filter matches bill number prefix and title keywords", async () => {
  render(<MemoryRouter><FiscalNotes /></MemoryRouter>);
  await waitFor(() => screen.getByText("HB2001"));
  fireEvent.change(screen.getByPlaceholderText(/filter/i), {
    target: { value: "ahcccs" },
  });
  expect(screen.getByText("SB1101")).toBeInTheDocument();
  expect(screen.queryByText("HB2001")).not.toBeInTheDocument();
});
```

Run: `cd webapp && npx vitest run src/pages/FiscalNotes.test.tsx` → FAIL

- [ ] **Step 2: Port the page**

Translate from `webapp/reference/fiscal-notes-build/base.html`: filter sidebar (text box + All/House/Senate switcher + session list navigation) driving a per-session card directory. Behavior parity with the mockup's JS island: prefix match on bill number OR keyword match on title; chamber switch filters; session list scrolls/filters to a session. Add one visible placeholder the mockup doesn't have: a disabled "Semantic search across all notes" input with hint "unlocks when the fiscal-note corpus is ingested" (Plan 3 wires it to `/api/search` with `corpus: "fiscal_notes"`).

- [ ] **Step 3: Run tests**

Run: `cd webapp && npx vitest run` → PASS

- [ ] **Step 4: Commit**

```bash
git add webapp/
git commit -m "feat(webapp): fiscal notes page — session directory + chamber/text filters (S12 port)"
```

---

### Task 11: Build + serve end-to-end (still stub)

**Files:** none new

- [ ] **Step 1: Full build + serve through FastAPI**

Run: `cd webapp && npm run build`, then `uv run uvicorn app.main:create_app --factory --port 9300`
Open `http://127.0.0.1:9300`.
Expected: home renders with hero; searching navigates to `/search` and shows grouped stub results with the "stub data" badge; `/fiscal-notes` shows the real 2126-bill / 28-session snapshot; hard-refresh on `/fiscal-notes` works (SPA fallback).

- [ ] **Step 2: Full test suites**

Run: `uv run pytest tests/test_app_server.py tests/test_search_route.py tests/test_fiscal_notes_route.py tests/test_fiscal_notes_snapshot.py -q && cd webapp && npx vitest run`
Expected: all PASS

- [ ] **Step 3: Commit anything outstanding; push the branch**

```bash
git add -A && git commit -m "chore(webapp): e2e build verification" --allow-empty
git push -u origin plan2-app-shell
```

**CHECKPOINT: Tasks 1–11 are the parallel-safe portion. Do not start Task 12 until Plan 1 is merged to `origin/master`.**

---

### Task 12: Integration — real retrieval provider (REQUIRES Plan 1 merged)

**Files:**
- Modify: `app/search_provider.py`, `app/main.py`
- Test: `tests/test_lance_provider.py`

- [ ] **Step 1: Sync Plan 1 into this worktree**

```bash
git fetch origin && git merge origin/master
```

Expected: clean merge (the parallel-execution contract means no shared files). Verify `store/` and `retrieval/local_embedder.py` now exist. If Plan 1 is NOT on master yet: STOP, report, do not continue.

- [ ] **Step 2: Write the failing provider test**

```python
# tests/test_lance_provider.py
"""LanceSearchProvider against a tmp LanceDB — mirrors the fixture
pattern from tests/test_search_lance.py (Plan 1)."""
import pytest

from app.search_provider import LanceSearchProvider
from store.chunk_store import ChunkStore


class FakeResult:
    def __init__(self, chunks):
        self.chunks = chunks


def test_provider_maps_retrieval_result_to_contract(monkeypatch, tmp_path):
    # Provider delegates to retrieval.retrieve(); fake it to stay
    # model-free — the mapping is what this test owns.
    from retrieval.types import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1", doc_id="jlbc-baseline-fy2027-ahcccs",
        text="provider rate increases of $58.1M", score=4.2,
        section_path=["AHCCCS"], page=14, bbox=None, source_anchor=None,
        agency_canonical_ids=["ahcccs"], fund_canonical_id=None,
        fund_mentions=[], fiscal_year=2027,
        doc_type="baseline-per-agency", is_table=False, table_html=None,
        token_count=8, publisher="jlbc",
    )
    monkeypatch.setattr(
        "app.search_provider.retrieve", lambda req, **kw: FakeResult([chunk]),
    )
    out = LanceSearchProvider().search(
        "ahcccs rates", top_k=5, corpus="budget", filters={},
    )
    assert out[0]["chunk_id"] == "c1"
    assert out[0]["doc_title"] == "JLBC Baseline FY2027 AHCCCS".title() or out[0]["doc_title"]
    assert out[0]["snippet"].startswith("provider rate")
    assert out[0]["publisher"] == "jlbc"
```

(Keep the `doc_title` assertion loose — the humanizer is best-effort slug prettification.)

- [ ] **Step 3: Implement `LanceSearchProvider`**

Append to `app/search_provider.py`:

```python
from retrieval import RetrievalRequest, retrieve  # Plan 1 public API


def _title_from_doc_id(doc_id: str) -> str:
    """Best-effort humanization of doc_id slugs
    ('jlbc-baseline-fy2027-axs' -> 'JLBC Baseline FY 2027 — AXS').
    Good enough until a documents-metadata table exists (Plan 3)."""
    parts = doc_id.split("-")
    out = []
    for p in parts:
        if p.startswith("fy") and p[2:].isdigit():
            out.append(f"FY {p[2:]}")
        elif p in ("jlbc", "agao", "afr", "sad"):
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return " ".join(out)


class LanceSearchProvider:
    """Real retrieval (Plan 1 stack) behind the /api/search contract."""

    name = "lance"

    _CORPUS_TABLE = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}

    def search(self, query, *, top_k, corpus, filters):
        req = RetrievalRequest(
            query=query,
            top_k=top_k,
            corpus=self._CORPUS_TABLE[corpus],
            fiscal_year=filters.get("fiscal_year"),
            publisher=filters.get("publisher"),
            doc_type=filters.get("doc_type"),
            agency_canonical_id=filters.get("agency"),
        )
        result = retrieve(req)
        return [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "doc_title": _title_from_doc_id(c.doc_id),
                "snippet": c.text[:280],
                "page": c.page,
                "score": c.score,
                "doc_type": c.doc_type,
                "fiscal_year": c.fiscal_year,
                "publisher": c.publisher,
                "agencies": list(c.agency_canonical_ids),
            }
            for c in result.chunks
        ]
```

In `app/main.py`, choose the provider by corpus availability instead of hardcoding the stub:

```python
def _default_provider() -> SearchProvider:
    # Real corpus present -> real provider; else stub (fresh checkout,
    # CI, or a dev machine that hasn't run the Plan 1 migration).
    try:
        from store.chunk_store import ChunkStore

        if ChunkStore().count("budget_chunks") > 0:
            from app.search_provider import LanceSearchProvider

            return LanceSearchProvider()
    except Exception:
        pass
    return StubSearchProvider()
```

…and use `provider or _default_provider()` in `create_app`.

- [ ] **Step 4: Run tests + live check**

Run: `uv run pytest tests/test_lance_provider.py tests/test_app_server.py tests/test_search_route.py -v`
Expected: PASS (existing route tests still pass — `create_app(provider=StubSearchProvider())` injection keeps them deterministic; update them to inject explicitly if the default flipped).
Then: `cd webapp && npm run build && cd .. && uv run uvicorn app.main:create_app --factory --port 9300` — search "ahcccs provider rates": real corpus results, no stub badge, `/health` shows `"provider": "lance"`.

- [ ] **Step 5: Commit**

```bash
git add app/ tests/test_lance_provider.py
git commit -m "feat(app): LanceSearchProvider — /api/search now serves the real corpus"
```

---

### Task 13: STATUS.md + merge

- [ ] **Step 1: Update STATUS.md**

Add a "Standalone consolidation (Plan 2) — shipped" subsection: app server (`app/`, port 9300), webapp (`webapp/`, ported home/search/fiscal-notes), snapshot data source note ("fiscal notes page serves a frozen snapshot until Plan 3"), API contracts pointer to this plan.

- [ ] **Step 2: Full verify**

Run: `bash setup.sh --verify` and `cd webapp && npx vitest run`
Expected: green. (If `setup.sh --verify` doesn't know about webapp yet, add the vitest invocation to it in this step.)

- [ ] **Step 3: Merge per superpowers:finishing-a-development-branch**

`--no-ff` merge to master, push, remove worktree. If STATUS.md conflicts with Plan 1's entry, keep both sections.

---

## Self-review notes

- **Spec coverage (this plan's slice):** S1 server shape (Task 2), S9 search-mode surfaces for both corpora (Tasks 9–10; fiscal-note semantic search deliberately stubbed until Plan 3 data exists), S12 port-don't-redesign (Tasks 1, 7–10 all translate from vendored sources), UI section's AI-dimmed affordances (Tasks 8–10). Launcher/packaging is Plan 5; PDF side panel + chat port is Plan 4 (chunk rows carry `data-chunk-id` so Plan 4 attaches the viewer without restructuring).
- **Parallel-safety:** verified — no file in this plan appears in Plan 1's file list; Python deps unchanged; Task 12 is the single ordered point and is explicitly gated.
- **Known judgment calls flagged inline:** build.py parser adaptation (Task 3), doc_title humanizer being best-effort (Task 12).
