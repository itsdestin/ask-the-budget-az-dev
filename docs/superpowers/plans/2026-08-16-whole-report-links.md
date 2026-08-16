# Whole-Report Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-08-16-whole-report-links-design.md`](../specs/2026-08-16-whole-report-links-design.md) (R1–R13)

**Goal:** A new JLBC book edition surfaces on the Admin page for one-click
approval of its "Full report" links, so nobody ever edits code to add a year.

**Architecture:** The table of whole-report URLs moves out of
`webapp/src/reportFamilies.ts` into a committed `data/report-formats.json`,
merged at read time with an admin overlay on the shared drive. New admin routes
scan the corpus for editions that table does not answer, resolve candidate URLs
through the *existing* `ingest/book_discovery.plan_edition` and confirm each one
responds, and an admin panel approves, replaces, marks a format as never
published, or corrects an edition already answered.

**Tech Stack:** Python 3.12 / FastAPI / pytest on the server; React 18 + Vite +
vitest in `webapp/`. No new dependencies.

---

## Global Constraints

- **Family names are exactly `"Baseline"` and `"Appropriations Report"`** — the
  strings `store/book_family.py::section_of` returns and
  `webapp/src/reportFamilies.ts::familyOf` displays. Never invent a third
  spelling, never lowercase them for storage (R2).
- **`null` means "JLBC published no such format"; an absent edition key means
  "nobody has answered yet".** These are different states (R1).
- **An overlay entry replaces its shipped entry wholesale**, never field by
  field (R1).
- **Nothing renders on the analyst-facing page until an edition is approved**
  (R7).
- **Read paths degrade, write paths raise.** A bad overlay must never 500 a
  page; a failed save must reach the admin's screen (R10). Mirror
  `store/office_aliases.py`.
- **`ingest/book_discovery.py` is imported read-only and never modified** (R4).
- **No eval run is required** — nothing under `retrieval/`, `chunking/`,
  `citation/` or `harness/system-prompt.md` is touched.
- **Gates after every task:** `uv run python -m pytest -q`, and for any task
  touching `webapp/`: `npx vitest run`, `npx tsc -b`, `npm run build`.
- **Annotate every non-trivial edit with a WHY comment** recording the evidence
  that drove the choice, per `CLAUDE.md`.

> ⚠ **The code blocks in this plan are sketches to RUN and CORRECT, not text to
> transcribe.** This repo has recorded plan-code defects on five consecutive
> features — a function name that does not exist, a call against a signature
> that never gains the parameter, and tests that passed whether or not the
> feature worked. Run every snippet. When a snippet disagrees with the
> codebase, the codebase wins; record the deviation in `STATUS.md`.

---

## File Structure

| File | Responsibility |
|---|---|
| `data/report-formats.json` | **create.** The 39 verified editions, committed, ships in the bundle via `git ls-files` |
| `store/report_formats.py` | **create.** Load shipped + overlay, merge, validate, save. mtime-stamped cache |
| `app/routes/book_formats.py` | **create.** Pending scan, per-edition probe cache, the three admin routes |
| `app/routes/books.py` | **modify.** `HttpProber` gains `head_info` (status + Content-Length) |
| `app/routes/corpus.py` | **modify.** `GET /api/corpus/documents` gains `report_formats` |
| `app/main.py` | **modify.** Register the new router |
| `scripts/verify_report_formats.py` | **modify.** Read the merged table instead of parsing TypeScript |
| `webapp/src/reportFamilies.ts` | **modify.** Delete `REPORT_FORMATS`; `reportFormats()` takes the table |
| `webapp/src/api.ts` | **modify.** `report_formats` on the corpus response + three admin calls |
| `webapp/src/pages/Search.tsx` | **modify.** Thread the table to the two call sites |
| `webapp/src/admin/ReportLinksPanel.tsx` | **create.** The approval card |
| `webapp/src/pages/Admin.tsx` | **modify.** Mount the panel in the "Needs attention" group |
| `tests/test_report_formats_store.py` | **create.** Load/merge/validate/save |
| `tests/test_report_formats_data.py` | **create.** The guards against the committed file |
| `tests/test_book_formats_route.py` | **create.** Scan, probe cache, offline, the writes |
| `tests/test_packaging_manifest.py` | **modify.** The committed table must ship in the Windows bundle |
| `webapp/src/reportFamilies.test.ts` | **modify.** Drop the four URL guards (they move to pytest) |
| `webapp/src/pages/Search.test.tsx` | **modify.** Fixture gains `report_formats` (2 mock sites) |
| `webapp/src/pages/Search.content.test.tsx` | **modify.** Fixture gains `report_formats` (8 mock sites) |
| `webapp/src/pages/Search.ai-mode.test.tsx` | **modify.** Fixture gains `report_formats` |
| `webapp/src/pdf/__tests__/search-source-panel.test.tsx` | **modify.** Fixture gains `report_formats` |
| `webapp/src/admin/ReportLinksPanel.test.tsx` | **create.** Panel behaviour |

> **`corpusDocuments` is mocked at 16 sites across 4 test files.** Counted
> 2026-08-16 with `grep -rn corpusDocuments webapp/src`. Every one must be
> updated in Task 3, and `report_formats` must stay a **required** field on the
> return type. Making it optional (`report_formats?`) is the shortcut that
> compiles instantly and then silently defaults every un-updated caller to no
> table — which removes every "Full report" button on the page while the whole
> suite stays green.

---

## Task 1: The table becomes data the server owns

**Files:**
- Create: `data/report-formats.json`
- Create: `store/report_formats.py`
- Create: `tests/test_report_formats_store.py`
- Create: `tests/test_report_formats_data.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `store.report_formats.EditionFormats` — frozen dataclass, fields
    `single_file: str | None`, `linked_toc: str | None`
  - `format_key(family: str, fiscal_year: int) -> str` → `"Baseline:2027"`
  - `BOOK_FAMILIES: tuple[str, str]` = `("Baseline", "Appropriations Report")`
  - `shipped_path() -> Path`, `overlay_path() -> Path`
  - `load_shipped(path: Path | None = None) -> dict[str, EditionFormats]`
  - `load_overlay(path: Path | None = None) -> tuple[dict[str, EditionFormats], list[str]]`
    — the second element is one plain-English sentence per dropped row
  - `load(...) -> tuple[dict[str, EditionFormats], list[str]]` — merged table
    plus the overlay's problems
  - `save_edition(family, fiscal_year, single_file, linked_toc, *, path=None) -> None` — RAISES on failure
  - `names_its_year(url: str, fiscal_year: int) -> bool`
  - `YEARLESS_BY_DESIGN: frozenset[str]`
  - `reset_cache() -> None` (tests)

> **Naming note, do not skip:** `ingest/book_discovery.py` already exports
> `edition_key(family, fiscal_year)` producing `"approps-fy2027"` with a
> LOWERCASE family. This module's key is a different thing in a different
> vocabulary, so it is `format_key` and produces `"Appropriations Report:2027"`.
> Importing the wrong one silently produces a table nothing matches.

- [ ] **Step 1: Generate `data/report-formats.json` from the shipped TypeScript**

Run this once. It reads the current table so the 39 verified editions are moved,
not retyped:

```bash
uv run python - <<'PY'
import json, re
from pathlib import Path

src = Path("webapp/src/reportFamilies.ts").read_text(encoding="utf-8")
row = re.compile(
    r'"(?P<key>[^"]+:\d{4})":\s*\{\s*'
    r'singleFile:\s*(?P<single>"[^"]*"|null),\s*'
    r'linkedToc:\s*(?P<toc>"[^"]*"|null)'
)
def val(raw):
    return None if raw == "null" else raw.strip('"')

editions = {
    m.group("key"): {"single_file": val(m.group("single")),
                     "linked_toc": val(m.group("toc"))}
    for m in row.finditer(src)
}
assert len(editions) == 39, f"expected 39 editions, parsed {len(editions)}"
Path("data/report-formats.json").write_text(
    json.dumps({"version": 1, "editions": dict(sorted(editions.items()))}, indent=2) + "\n",
    encoding="utf-8",
)
print("wrote", len(editions), "editions")
PY
```

Expected: `wrote 39 editions`. If the assert fires, the TypeScript has been
reformatted out of the regex's shape — fix the regex, do not lower the count.

- [ ] **Step 2: Write the failing tests for the committed file**

`tests/test_report_formats_data.py` — these are the four guards moving out of
`webapp/src/reportFamilies.test.ts`, unchanged in meaning:

```python
"""Guards on the COMMITTED whole-report link table (spec R11).

These are the checks that run offline. Reachability is network-bound and lives
in scripts/verify_report_formats.py; what is guarded here is the class of
mistake a green download check waves through — a URL that resolves fine and is
the WRONG YEAR.
"""
import re

from store.report_formats import (
    BOOK_FAMILIES,
    YEARLESS_BY_DESIGN,
    load_shipped,
    names_its_year,
)


def test_every_key_is_a_known_family_and_a_four_digit_year():
    # A typo'd family produces a button that never appears, which is
    # indistinguishable from an uncurated year.
    for key in load_shipped():
        family, _, year = key.rpartition(":")
        assert family in BOOK_FAMILIES, key
        assert re.fullmatch(r"\d{4}", year), key


def test_every_url_names_its_own_fiscal_year():
    # THE load-bearing guard. Copying a row and forgetting to bump the URL
    # yields a live, downloadable, WRONG report behind a button labelled
    # "Full report" — a false provenance claim no 200 OK can detect.
    for key, formats in load_shipped().items():
        year = int(key.rpartition(":")[2])
        for url in (formats.single_file, formats.linked_toc):
            if url is None or url in YEARLESS_BY_DESIGN:
                continue
            assert names_its_year(url, year), f"{key} points at {url}"


def test_every_url_is_a_jlbc_pdf():
    for key, formats in load_shipped().items():
        for url in (formats.single_file, formats.linked_toc):
            if url is None:
                continue
            assert re.fullmatch(r"https://www\.azjlbc\.gov/\S+\.pdf", url), f"{key} {url}"


def test_every_edition_offers_at_least_one_format():
    # {single_file: null, linked_toc: null} is indistinguishable from having no
    # entry, so such a row is dead weight that reads as coverage.
    for key, formats in load_shipped().items():
        assert formats.single_file or formats.linked_toc, key


def test_the_committed_table_still_covers_every_edition_it_did_on_2026_08_16():
    # A floor, deliberately: this file was generated from the shipped
    # TypeScript, and a regex that silently matched fewer rows would look like
    # a clean smaller table rather than a loss. `>=` rather than `==` so that
    # promoting an approved edition into the committed file is a data change,
    # not a data change plus a test edit.
    assert len(load_shipped()) >= 39
```

- [ ] **Step 2b: Pin that the table actually ships**

The committed table is worthless if the Windows bundle drops it: every office
install would silently lose all 39 editions and every "Full report" button, with
no error anywhere. `packaging/build_bundle.py` selects files with `git ls-files`
minus `EXCLUDED_PREFIXES`, and `data/` is not excluded — so this holds today and
nothing pins it.

Add `"data/report-formats.json"` to the tuple in
`tests/test_packaging_manifest.py::test_source_files_ships_the_live_application`.
Verify by temporarily adding `"data/report-formats.json"` to
`build_bundle.EXCLUDED_PREFIXES` and confirming the test goes red.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run python -m pytest tests/test_report_formats_data.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'store.report_formats'`

- [ ] **Step 4: Write `store/report_formats.py`**

```python
"""The whole-report ("Full report") link table (spec R1, R2, R6, R10, R11).

TWO FILES, ONE SCHEMA, MERGED HERE.

  data/report-formats.json      committed, ships in the bundle, holds the 39
                                editions verified by download on 2026-08-16
  <data_dir>/report-formats.json  the admin's approvals, on the shared drive

WHY the table is not in the webapp any more: an approval overlay plus a
hand-maintained TypeScript table would be two owners of the same information in
two languages, with the merge in one of them. STATUS.md records that exact
shape producing silent drift at least four times (`_DOC_TYPES` vs the registry,
Upload.tsx's publisher map, three drifted documents.json readers, two "is the
queue stalled?" implementations).

`null` means "JLBC published no such format" — Appropriations Reports before
FY2011 have a linked table of contents and no single file. An ABSENT edition
key means "nobody has answered for this edition yet", which is what puts it on
the admin page. Do not collapse the two.

Read posture mirrors store/office_aliases.py, which was reviewed into this
shape for the same reason: a hand-editable file on a network drive must not be
able to take a page down. Writes are tmp+os.replace and RAISE — a failed save
must reach the admin's screen, not vanish.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from store.config import data_dir

REPORT_FORMATS_FILE = "report-formats.json"

# Verbatim from store/book_family.py, which is what stamps these names onto
# documents and what webapp/src/reportFamilies.ts displays. A third spelling
# anywhere grows a duplicate family card on the browse page.
BOOK_FAMILIES = ("Baseline", "Appropriations Report")

# The ONE published URL with no year in its path. JLBC put the FY2023
# Appropriations Report in the undated /budget/ directory; verified by download
# 2026-08-16 that this address serves "FY 2023 APPROPRIATIONS REPORT".
#
# If a SECOND entry ever needs listing here, stop and re-measure the rule
# instead of adding it — this repo's own guidance is that a guard needing two
# exemptions is measuring the wrong thing.
YEARLESS_BY_DESIGN = frozenset({"https://www.azjlbc.gov/budget/apprpttoc.pdf"})


@dataclass(frozen=True)
class EditionFormats:
    single_file: str | None
    linked_toc: str | None


def format_key(family: str, fiscal_year: int) -> str:
    """"Appropriations Report:2027". NOT ingest.book_discovery.edition_key,
    which is "approps-fy2027" — a different vocabulary for a different table."""
    return f"{family}:{fiscal_year}"


# Maximal runs of digits. The year must be a WHOLE run, never a substring of
# one -- see names_its_year.
_DIGIT_RUN = re.compile(r"\d+")


def names_its_year(url: str, fiscal_year: int) -> bool:
    """Does this address mention the year it claims to be?

    JLBC's own filenames carry it -- 19AR/FY2019AppropRpt.pdf,
    26baseline/26baselinesinglefile.pdf -- so this is checkable with no network.
    It is the only defence against the probe ladder's rolling /budget/ rung,
    which returns a live 200 for a year that does not exist yet.

    🔴 SUBSTRING MATCHING DOES NOT WORK HERE, AND IT FAILS EXACTLY WHERE IT
    MATTERS. The obvious form -- `str(fy) in path or f"{fy % 100:02d}" in path`
    -- was measured against the real 71 URLs on 2026-08-16 and accepted **32
    wrong year/URL pairs**, because "20" is a substring of every `fy20xx`
    filename JLBC publishes. Under the key `Appropriations Report:2020` it
    accepted SIXTEEN other editions' reports, including
    `11app/FY2011AppropRpt.pdf`. The one guard standing between a copy-pasted
    row and a live, downloadable, wrong-year report was therefore off for that
    edition entirely. `:2001`..`:2009` have the same hole ("01" sits inside
    "2019").

    Comparing whole digit runs instead separates perfectly on the same data:
    **0 real URLs wrongly rejected, 0 wrong pairs accepted.** `19ar/
    fy2019approprpt.pdf` yields the runs {"19", "2019"}, which answers FY2019
    and refuses FY2020.

    The host is stripped first: "azjlbc" contains no digits today, but a future
    host or a query string could contribute a stray "27" and quietly make this
    guard always true.
    """
    path = url.lower().split("://", 1)[-1].partition("/")[2]
    runs = set(_DIGIT_RUN.findall(path))
    return str(fiscal_year) in runs or f"{fiscal_year % 100:02d}" in runs


def shipped_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / REPORT_FORMATS_FILE


def overlay_path() -> Path:
    return data_dir() / REPORT_FORMATS_FILE


_lock = threading.Lock()
# path -> (stamp, parsed, problems). Two entries at most (shipped, overlay).
#
# The PROBLEMS are cached with the rows, not recomputed and not dropped. An
# earlier shape cached only `parsed` and returned `[]` on a hit, so the sentence
# explaining a dropped row appeared on the admin's first page load and vanished
# on every one after it -- while the row went on being dropped. A test that
# loads once cannot see that, so the guard below loads twice.
_cache: dict[
    str, tuple[tuple[str, int, int], dict[str, EditionFormats], list[str]]
] = {}


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = {}


def _parse(raw: object, *, strict: bool) -> tuple[dict[str, EditionFormats], list[str]]:
    """Rows -> EditionFormats, collecting a sentence per row dropped.

    `strict` is the difference between the two files and it is deliberate: a bad
    row in the COMMITTED file is a defect a test must catch, while a bad row in
    the hand-editable overlay costs itself and nothing else.
    """
    problems: list[str] = []
    out: dict[str, EditionFormats] = {}
    if not isinstance(raw, dict):
        raise ValueError(f"expected an object, got {type(raw).__name__}")
    editions = raw.get("editions") or {}
    if not isinstance(editions, dict):
        raise ValueError("`editions` is not an object")
    for key, row in editions.items():
        try:
            if not isinstance(row, dict):
                raise ValueError("not an object")
            family, _, year = str(key).rpartition(":")
            if family not in BOOK_FAMILIES:
                raise ValueError(f"unknown report family {family!r}")
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError(f"{year!r} is not a four-digit fiscal year")
            single = row.get("single_file")
            toc = row.get("linked_toc")
            for url in (single, toc):
                if url is not None and not isinstance(url, str):
                    raise ValueError("a link must be a web address or empty")
            if not single and not toc:
                raise ValueError("neither format is set, so there is nothing to link")
            out[str(key)] = EditionFormats(single_file=single or None, linked_toc=toc or None)
        except ValueError as err:
            if strict:
                raise
            problems.append(f"Ignoring the saved links for {key}: {err}.")
    return out, problems


def _read(resolved: Path, *, strict: bool) -> tuple[dict[str, EditionFormats], list[str]]:
    try:
        stat = resolved.stat()
        stamp = (str(resolved), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        if strict:
            raise
        return {}, []          # no overlay yet is the normal, silent case
    except OSError as err:
        if strict:
            raise
        _say_unavailable(resolved, err)
        return {}, []
    with _lock:
        hit = _cache.get(str(resolved))
    if hit is not None and hit[0] == stamp:
        return hit[1], list(hit[2])
    try:
        parsed, problems = _parse(json.loads(resolved.read_text(encoding="utf-8")), strict=strict)
    except (OSError, ValueError, TypeError) as err:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError — the
        # trap harness/ledger.py documents.
        if strict:
            raise
        _say_unavailable(resolved, err)
        return {}, [f"The saved link file could not be read ({err})."]
    with _lock:
        _cache[str(resolved)] = (stamp, parsed, problems)
    return parsed, list(problems)


def _say_unavailable(resolved: Path, err: Exception) -> None:
    print(
        f"store.report_formats: ignoring {resolved} ({err}) — the admin's "
        "whole-report links are unavailable for this read.",
        file=sys.stderr,
    )


def load_shipped(path: Path | None = None) -> dict[str, EditionFormats]:
    return _read(path or shipped_path(), strict=True)[0]


def load_overlay(path: Path | None = None) -> tuple[dict[str, EditionFormats], list[str]]:
    return _read(path or overlay_path(), strict=False)


def load(
    shipped: Path | None = None, overlay: Path | None = None
) -> tuple[dict[str, EditionFormats], list[str]]:
    """The merged table, plus a sentence per overlay row that was dropped.

    The overlay REPLACES a shipped entry wholesale. The unit the admin acts on
    is an edition, and a field-level merge would create states nobody chose —
    half this year's answer and half last year's.
    """
    try:
        base = dict(load_shipped(shipped))
    except Exception as err:  # noqa: BLE001 — a broken bundle must not 500 the page
        _say_unavailable(shipped or shipped_path(), err)
        base = {}
    extra, problems = load_overlay(overlay)
    base.update(extra)
    return base, problems


def save_edition(
    family: str,
    fiscal_year: int,
    single_file: str | None,
    linked_toc: str | None,
    *,
    path: Path | None = None,
) -> None:
    """Write one edition into the overlay. RAISES on any failure."""
    if family not in BOOK_FAMILIES:
        raise ValueError(f"Unknown report family {family!r}.")
    if not single_file and not linked_toc:
        # Refused because it is indistinguishable from having no entry, so the
        # edition would silently re-appear as unanswered forever.
        raise ValueError(
            "At least one of the two formats must have a link. If JLBC "
            "published neither, this edition has nothing to open."
        )
    resolved = path or overlay_path()
    current: dict = {"version": 1, "editions": {}}
    if resolved.exists():
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("editions"), dict):
                current = loaded
        except (OSError, ValueError):
            # A corrupt overlay is replaced rather than appended to. It holds
            # only approvals, each of which is one click to redo, and refusing
            # to save would strand the admin with no way to fix it from the UI.
            pass
    current.setdefault("version", 1)
    current.setdefault("editions", {})
    current["editions"][format_key(family, fiscal_year)] = {
        "single_file": single_file or None,
        "linked_toc": linked_toc or None,
    }
    current["editions"] = dict(sorted(current["editions"].items()))
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, resolved)
    reset_cache()
```

- [ ] **Step 5: Run the data guards to verify they pass**

Run: `uv run python -m pytest tests/test_report_formats_data.py -q`
Expected: 5 passed

- [ ] **Step 6: Write the store's own tests**

`tests/test_report_formats_store.py`:

```python
import json

import pytest

from store.report_formats import (
    EditionFormats,
    format_key,
    load,
    load_overlay,
    names_its_year,
    reset_cache,
    save_edition,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_cache()
    yield
    reset_cache()


def _write(path, editions):
    path.write_text(json.dumps({"version": 1, "editions": editions}), encoding="utf-8")


def test_the_overlay_replaces_a_shipped_edition_wholesale(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": "https://x/b.pdf"}})
    _write(overlay, {"Baseline:2027": {"single_file": "https://y/c.pdf", "linked_toc": None}})
    table, problems = load(shipped, overlay)
    assert table["Baseline:2027"] == EditionFormats("https://y/c.pdf", None)
    assert problems == []


def test_a_torn_overlay_row_costs_itself_not_the_file(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    _write(overlay, {
        "Nonsense Family:2027": {"single_file": "https://y/c.pdf", "linked_toc": None},
        "Baseline:2026": {"single_file": "https://y/d.pdf", "linked_toc": None},
    })
    table, problems = load(shipped, overlay)
    assert "Baseline:2026" in table          # the good row survived
    assert "Baseline:2027" in table          # the shipped table survived
    assert "Nonsense Family:2027" not in table
    assert len(problems) == 1 and "Nonsense Family:2027" in problems[0]


def test_the_reason_a_row_was_dropped_survives_a_second_load(tmp_path):
    # The second load is the one that comes off the mtime cache. A first version
    # cached only the rows, so the admin saw the explanation once and never
    # again while the row went on being dropped -- a warning that disappears is
    # worse than no warning, because the page then looks healthy.
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    _write(overlay, {"Nonsense Family:2027": {"single_file": "https://y/c.pdf", "linked_toc": None}})
    assert load(shipped, overlay)[1] == load(shipped, overlay)[1] != []


def test_unreadable_overlay_json_leaves_the_shipped_table_serving(tmp_path):
    shipped = tmp_path / "shipped.json"
    overlay = tmp_path / "overlay.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    overlay.write_text("{ this is not json", encoding="utf-8")
    table, problems = load(shipped, overlay)
    assert table["Baseline:2027"].single_file == "https://x/a.pdf"
    assert problems and "could not be read" in problems[0]


def test_a_missing_overlay_is_silent(tmp_path):
    shipped = tmp_path / "shipped.json"
    _write(shipped, {"Baseline:2027": {"single_file": "https://x/a.pdf", "linked_toc": None}})
    table, problems = load(shipped, tmp_path / "absent.json")
    assert list(table) == ["Baseline:2027"]
    assert problems == []


def test_save_then_load_round_trips(tmp_path):
    overlay = tmp_path / "overlay.json"
    save_edition("Appropriations Report", 2028, "https://x/28.pdf", None, path=overlay)
    table, problems = load_overlay(overlay)
    assert table[format_key("Appropriations Report", 2028)] == EditionFormats("https://x/28.pdf", None)
    assert problems == []


def test_saving_an_edition_with_neither_format_is_refused(tmp_path):
    # Both-null is indistinguishable from having no entry, so the edition would
    # re-appear as unanswered forever and the admin could never settle it.
    with pytest.raises(ValueError, match="at least one"):
        save_edition("Baseline", 2028, None, None, path=tmp_path / "overlay.json")


def test_saving_an_unknown_family_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Unknown report family"):
        save_edition("Baselines", 2028, "https://x/a.pdf", None, path=tmp_path / "overlay.json")


def test_a_failed_save_raises_rather_than_degrading(tmp_path):
    # The read paths degrade on purpose; this one must not. An admin who
    # presses Approve and is told nothing has no way to learn it did not stick.
    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory", encoding="utf-8")
    with pytest.raises(OSError):
        save_edition("Baseline", 2028, "https://x/a.pdf", None, path=unwritable / "overlay.json")


def test_saving_preserves_other_editions_already_in_the_overlay(tmp_path):
    overlay = tmp_path / "overlay.json"
    save_edition("Baseline", 2028, "https://x/28b.pdf", None, path=overlay)
    save_edition("Appropriations Report", 2028, "https://x/28a.pdf", None, path=overlay)
    table, _ = load_overlay(overlay)
    assert len(table) == 2


def test_a_corrupt_overlay_is_replaced_rather_than_blocking_every_future_save(tmp_path):
    overlay = tmp_path / "overlay.json"
    overlay.write_text("{ torn", encoding="utf-8")
    save_edition("Baseline", 2028, "https://x/a.pdf", None, path=overlay)
    table, _ = load_overlay(overlay)
    assert list(table) == ["Baseline:2028"]


@pytest.mark.parametrize(
    "url,year,expected",
    [
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2019, True),
        ("https://www.azjlbc.gov/26baseline/26baselinesinglefile.pdf", 2026, True),
        ("https://www.azjlbc.gov/12book1/12BaselineSingleFile.pdf", 2012, True),
        ("https://www.azjlbc.gov/05app/apprpttoc.pdf", 2005, True),
        ("https://www.azjlbc.gov/budget/24baselinelinks.pdf", 2024, True),
        # The rolling directory: a live 200 that names no year at all. This is
        # the case the whole guard exists for.
        ("https://www.azjlbc.gov/budget/apprpttoc.pdf", 2028, False),
        # The realistic copy-paste slip: last year's report under this year's key.
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2018, False),
        # 🔴 THE CASE A SUBSTRING TEST GETS WRONG, and the reason this function
        # compares whole digit runs. "20" sits inside "fy2019", so a substring
        # test answers True here and the FY2020 key accepts sixteen other
        # editions' reports. Measured on the real table 2026-08-16: 32 wrong
        # pairs accepted, all of them on :2020. Delete this row and the hole
        # comes back invisibly.
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2020, False),
        ("https://www.azjlbc.gov/26ar/fy2026approprpt.pdf", 2020, False),
        # Same hole one digit along: "01" sits inside "2019".
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2001, False),
    ],
)
def test_names_its_year(url, year, expected):
    assert names_its_year(url, year) is expected
```

> **Mutation check, run it:** replace the body with the substring form
> (`str(fiscal_year) in path or f"{fiscal_year % 100:02d}" in path`) and confirm
> the three `:2020` / `:2001` rows go red. They are the only rows that move.

- [ ] **Step 7: Run the store tests**

Run: `uv run python -m pytest tests/test_report_formats_store.py -q`
Expected: all pass. Fix `store/report_formats.py` where they do not — the tests
are the specification here, not the sketch above.

- [ ] **Step 8: Mutation-check the load-bearing guard**

Edit `data/report-formats.json` in place so `Appropriations Report:2018`'s
`single_file` reads `https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf`, then run:

Run: `uv run python -m pytest tests/test_report_formats_data.py -q`
Expected: FAIL on `test_every_url_names_its_own_fiscal_year`, naming that key.

Then `git checkout data/report-formats.json` and re-run to confirm green.

> ⚠ Revert with a **separate** command. Chaining `git checkout` onto the test
> run in one shell line reverted an entire hour of work during this feature's
> predecessor.

- [ ] **Step 9: Commit**

```bash
git add data/report-formats.json store/report_formats.py tests/test_report_formats_store.py tests/test_report_formats_data.py tests/test_packaging_manifest.py
git commit -m "store: the whole-report link table becomes data with an admin overlay"
```

---

## Task 2: Serve the merged table to the browse page

**Files:**
- Modify: `app/routes/corpus.py` (`corpus_documents`)
- Test: `tests/test_corpus_documents_route.py`

**Interfaces:**
- Consumes: `store.report_formats.load`, `EditionFormats`
- Produces: `GET /api/corpus/documents` → `{"documents": [...], "report_formats": {"<family>:<year>": {"single_file": str|null, "linked_toc": str|null}}}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_corpus_documents_route.py`:

```python
def test_the_listing_carries_the_whole_report_link_table(tmp_path, monkeypatch):
    # The browse page needs documents and their "Full report" links together.
    # A second endpoint would let the rows render one frame before their
    # buttons, which reads as a flash of missing controls on every load.
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    body = TestClient(app).get("/api/corpus/documents").json()
    assert "report_formats" in body
    entry = body["report_formats"]["Appropriations Report:2027"]
    assert entry["single_file"] == "https://www.azjlbc.gov/27ar/fy2027approprpt.pdf"
    assert entry["linked_toc"] == "https://www.azjlbc.gov/27ar/apprpttoc.pdf"


def test_a_broken_overlay_still_serves_the_documents(tmp_path, monkeypatch):
    # An unreadable file on the share must cost the links, never the listing.
    import store.report_formats as rf
    from app.main import create_app
    from fastapi.testclient import TestClient

    bad = tmp_path / "report-formats.json"
    bad.write_text("{ torn", encoding="utf-8")
    monkeypatch.setattr(rf, "overlay_path", lambda: bad)
    rf.reset_cache()
    body = TestClient(create_app()).get("/api/corpus/documents").json()
    assert isinstance(body["documents"], list)
    assert "Appropriations Report:2027" in body["report_formats"]  # shipped table survived
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest tests/test_corpus_documents_route.py -q -k whole_report`
Expected: FAIL — `KeyError: 'report_formats'`

- [ ] **Step 3: Implement**

In `app/routes/corpus.py`:

```python
from store.report_formats import load as load_report_formats


@router.get("/api/corpus/documents")
def corpus_documents() -> dict:
    """The budget corpus as a browsable listing, plus its whole-report links.

    ... (existing docstring kept verbatim) ...

    `report_formats` rides along rather than living at its own endpoint: the
    page needs both together, and a separate call would let document rows paint
    a frame before their "Full report" buttons. Overlay problems are NOT
    reported here — this route is ungated and an analyst can do nothing about a
    malformed file on the share; they surface on the admin panel instead.
    """
    table, _problems = load_report_formats()
    return {
        "documents": document_listing(),
        "report_formats": {
            key: {"single_file": f.single_file, "linked_toc": f.linked_toc}
            for key, f in table.items()
        },
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_corpus_documents_route.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add app/routes/corpus.py tests/test_corpus_documents_route.py
git commit -m "app: the corpus listing carries the whole-report link table"
```

---

## Task 3: The webapp stops owning URLs

**Files:**
- Modify: `webapp/src/reportFamilies.ts` (delete `REPORT_FORMATS`, change `reportFormats`)
- Modify: `webapp/src/reportFamilies.test.ts` (drop the four URL guards)
- Modify: `webapp/src/api.ts` (`corpusDocuments` return type)
- Modify: `webapp/src/pages/Search.tsx` (thread the table)
- Modify: `webapp/src/pages/Search.test.tsx` (fixture, 2 mock sites)
- Modify: `webapp/src/pages/Search.content.test.tsx` (8 mock sites)
- Modify: `webapp/src/pages/Search.ai-mode.test.tsx` (mock site)
- Modify: `webapp/src/pdf/__tests__/search-source-panel.test.tsx` (mock site)

**Interfaces:**
- Consumes: `GET /api/corpus/documents` → `report_formats` (Task 2)
- Produces:
  - `api.ReportFormatTable = Record<string, { single_file: string | null; linked_toc: string | null }>`
  - `api.corpusDocuments(): Promise<{ documents: CorpusDocument[]; report_formats: ReportFormatTable }>`
  - `reportFormats(family: string, fiscalYear: number | null, table: ReportFormatTable): ReportFormats`

- [ ] **Step 1: Write the failing test**

In `webapp/src/reportFamilies.test.ts`, DELETE the four guards added on
2026-08-16 (`every curated key…`, `every curated URL names its own fiscal
year`, `every curated URL is a JLBC PDF`, `a curated edition offers at least
one format`) and the `CURATED` / `YEARLESS_BY_DESIGN` constants — they now live
in `tests/test_report_formats_data.py`. Replace them with:

```ts
import { reportFormats } from "./reportFamilies";

// The URL table now comes from the server (spec R1). These pin the lookup
// itself, which is all this module still owns.

const TABLE = {
  "Baseline:2027": { single_file: "https://x/b27.pdf", linked_toc: "https://x/b27toc.pdf" },
  "Appropriations Report:2005": { single_file: null, linked_toc: "https://x/ar05toc.pdf" },
};

test("an edition in the table resolves both of its formats", () => {
  expect(reportFormats("Baseline", 2027, TABLE)).toEqual({
    singleFile: "https://x/b27.pdf",
    linkedToc: "https://x/b27toc.pdf",
  });
});

test("an edition the table does not answer resolves to neither format", () => {
  // This is what "no button" looks like, and it must stay distinct from an
  // edition that answers with one format.
  expect(reportFormats("Baseline", 2099, TABLE)).toEqual({ singleFile: null, linkedToc: null });
});

test("a null format survives as null rather than becoming undefined", () => {
  // ReportRow branches on `singleFile && linkedToc`; an undefined here reads
  // the same as null today and would stop doing so the moment anything checks
  // for the key's presence.
  expect(reportFormats("Appropriations Report", 2005, TABLE)).toEqual({
    singleFile: null,
    linkedToc: "https://x/ar05toc.pdf",
  });
});

test("an unknown fiscal year resolves to neither format", () => {
  expect(reportFormats("Baseline", null, TABLE)).toEqual({ singleFile: null, linkedToc: null });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp && npx vitest run src/reportFamilies.test.ts`
Expected: FAIL — `reportFormats` takes two arguments, and `REPORT_FORMATS` is
still exported.

- [ ] **Step 3: Rewrite the lookup**

In `webapp/src/reportFamilies.ts`, delete the whole `REPORT_FORMATS` constant
and its comment block, and replace `reportFormats`:

```ts
/** The table as the server sends it on `GET /api/corpus/documents`. */
export type ReportFormatTable = Record<
  string,
  { single_file: string | null; linked_toc: string | null }
>;

/** Both whole-report format URLs for one edition, or neither.
 *
 *  The table moved OUT of this file on 2026-08-16 (spec R1). It is now
 *  `data/report-formats.json` merged with the admin's approvals on the share,
 *  because adding a year used to mean editing this file and rebuilding the
 *  app — a step a non-developer successor cannot perform, for a list that
 *  gains two rows a year forever.
 *
 *  An edition missing from the table returns neither format, which renders as
 *  no button. That is the honest state: the app has nothing verified to open.
 *  Do NOT add a fallback that guesses a URL from the year — a wrong PDF behind
 *  a button labelled "Full report" is a false provenance claim (Invariant 1),
 *  and JLBC has used four different naming conventions. */
export function reportFormats(
  family: string,
  fiscalYear: number | null,
  table: ReportFormatTable,
): ReportFormats {
  if (fiscalYear === null) return NO_FORMATS;
  const row = table[`${family}:${fiscalYear}`];
  if (!row) return NO_FORMATS;
  return { singleFile: row.single_file ?? null, linkedToc: row.linked_toc ?? null };
}
```

- [ ] **Step 4: Update the API type**

In `webapp/src/api.ts`:

```ts
import type { ReportFormatTable } from "./reportFamilies";

// Re-exported so consumers can write `api.ReportFormatTable` alongside every
// other wire type they use, instead of importing the same concept from two
// modules. The type is DEFINED in reportFamilies.ts because that is where the
// lookup that consumes it lives; defining it here instead would make api.ts
// import reportFamilies and reportFamilies import api.
export type { ReportFormatTable };

export async function corpusDocuments(): Promise<{
  documents: CorpusDocument[];
  // REQUIRED, never `report_formats?`. Optional compiles instantly against all
  // 16 existing mock sites and then hands every un-updated caller no table at
  // all -- which removes every "Full report" button on the page with the whole
  // suite green. The compiler errors are the work item, not an obstacle to it.
  report_formats: ReportFormatTable;
}> {
  const r = await fetch("/api/corpus/documents");
  if (!r.ok) await fail(r, "corpus documents");
  return r.json();
}
```

- [ ] **Step 5: Thread the table through `Search.tsx`**

Three edits, no behaviour change:

1. Store it. The corpus fetch already lands in a `useEffect` around line 811 —
   keep the table in state beside the documents, defaulting to `{}` so a page
   that has not loaded yet renders no buttons rather than crashing.
2. `resolveFullReportAction(family, year, docs, onChoose)` gains a fifth
   parameter `table: api.ReportFormatTable` and passes it to `reportFormats`.
3. Both callers — `ReportRow` (~line 315) and the search-match row (~line 476) —
   take a `formats: api.ReportFormatTable` prop and pass it down, as does the
   `ReportChooser` render at ~line 1425.

> **WHY a prop and not a module-level setter.** A `setReportFormats(table)`
> global is a smaller diff and makes the table invisible to the component
> tests, which then pass whether or not the wiring works. This project has
> shipped that exact shape twice (the annotation that never reached the UI, the
> availability probe with no cache) and both times every test stayed green.

- [ ] **Step 6: Update the Search fixture**

In `webapp/src/pages/Search.test.tsx`, `mount()` currently mocks
`api.corpusDocuments` with `{ documents: docs }`. Give it the table the existing
assertions already depend on:

```ts
// The two editions this file's tests expect a "Full report" control for. The
// third, program-review, is deliberately absent — it is the fixture for the
// CRITICAL docs[0]-fallback guard and must stay unanswered.
const FIXTURE_FORMATS: api.ReportFormatTable = {
  "Baseline:2027": {
    single_file: "https://www.azjlbc.gov/budget/27baselinesinglefile.pdf",
    linked_toc: "https://www.azjlbc.gov/budget/27baselinelinks.pdf",
  },
  "Appropriations Report:2026": {
    single_file: "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf",
    linked_toc: "https://www.azjlbc.gov/26ar/apprpttoc.pdf",
  },
};

function mount(docs = DOCS, entry = "/search", formats = FIXTURE_FORMATS) {
  vi.spyOn(api, "corpusDocuments").mockResolvedValue({ documents: docs, report_formats: formats });
  // ... unchanged ...
}
```

- [ ] **Step 6b: Update the other three suites' mock sites**

`tsc -b` will name every one. As of 2026-08-16 there are **16 mock sites across
4 files**:

| file | sites | table to pass |
|---|---|---|
| `webapp/src/pages/Search.test.tsx` | 2 | `FIXTURE_FORMATS` above |
| `webapp/src/pages/Search.content.test.tsx` | 8 | `{}` unless a test asserts a Full report control |
| `webapp/src/pages/Search.ai-mode.test.tsx` | 1 | `{}` |
| `webapp/src/pdf/__tests__/search-source-panel.test.tsx` | 1 | `{}` |

Re-count before starting (`grep -rn corpusDocuments webapp/src`) — master moves
daily. Pass `{}` wherever the file makes no assertion about a "Full report"
control; where one does, give it the specific edition it asserts on and nothing
else, so the fixture states what the test depends on.

- [ ] **Step 7: Run the webapp suites**

Run: `cd webapp && npx vitest run && npx tsc -b && npm run build`
Expected: all pass, `tsc -b` exit 0, build clean. **Every existing `Search.test.tsx`
assertion must pass unedited apart from the fixture** — they are the proof this
task changed the data source and nothing else.

- [ ] **Step 8: Prove the button really comes from the server now**

Add to `webapp/src/pages/Search.test.tsx`:

```ts
test("an edition absent from the server's table renders no Full report control", async () => {
  // The whole point of Task 3: the page has no built-in URLs left. If this
  // passes with an empty table AND the earlier tests pass with a populated
  // one, the data is genuinely coming off the wire.
  mount(DOCS, "/search", {});
  await screen.findByRole("button", { name: /Fiscal Year 2027:/i });
  const row = screen.getByText("FY 2027 Baseline").closest(".doc")!;
  expect(row).not.toHaveTextContent(/full report/i);
  expect(row).toHaveClass("doc-unlinked");
});
```

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add webapp/src/reportFamilies.ts webapp/src/reportFamilies.test.ts webapp/src/api.ts webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx webapp/src/pages/Search.content.test.tsx webapp/src/pages/Search.ai-mode.test.tsx webapp/src/pdf/__tests__/search-source-panel.test.tsx
git commit -m "webapp: whole-report links come from the server, not a table in the bundle"
```

---

## Task 4: The three admin routes

**Files:**
- Create: `app/routes/book_formats.py`
- Modify: `app/routes/books.py` (`HttpProber.head_info`)
- Modify: `app/main.py`
- Create: `tests/test_book_formats_route.py`

**Interfaces:**
- Consumes: `store.report_formats.load`, `save_edition`, `format_key`,
  `names_its_year`; `app.routes.books_missing.corpus_editions` and
  `FAMILY_LABELS`; `ingest.book_discovery.plan_edition`, `DiscoveryError`;
  `app.routes.books.HttpProber`, `_prober`
- Produces:
  - `GET /api/admin/book-formats` → the panel's whole state
  - `PUT /api/admin/book-formats`, body
    `{"family": str, "fiscal_year": int, "single_file": str | null, "linked_toc": str | null}`
    → `{"ok": true}`; 400 with a plain sentence on refusal
  - `POST /api/admin/book-formats/check`, body `{"url": str, "fiscal_year": int}`
    → `{"ok": bool, "status": int | null, "bytes": int | null, "names_its_year": bool, "reason": str | null}`
  - `app.routes.books.HttpProber.head_info(url) -> tuple[int | None, int | None]`
    — (HTTP status, Content-Length), both `None` when the host is unreachable

> **Reuse, do not rewrite.** `app/routes/books_missing.py::corpus_editions()`
> already answers "which book editions does the corpus hold", reading each
> document's `source_url` and never its doc_id (21 doc_ids contradict their own
> title), and it already recognises all FOUR of JLBC's directory conventions —
> a two-pattern version was written first and measured wrong. `FAMILY_LABELS`
> in the same module maps `"approps" → "Appropriations Report"`. A second
> implementation of either would drift.

> **Where that reuse deviates from spec R3, and what would make it bite.** R3
> says to derive the corpus side "exactly as the browse page derives it" —
> `section_of` first, `doc_type` second. `corpus_editions()` instead reads the
> `{yy}ar|app|baseline|book1/` directory out of `source_url` for every document.
> **Measured over all 7,574 documents on 2026-08-16: both rules yield the same
> 39 editions, with zero disagreement in either direction.** The reuse is
> therefore correct today and is chosen because the alternative needs the
> `doc_type → family` map, which lives in TypeScript
> (`reportFamilies.ts::FAMILY_OF_DOC_TYPE`) and would have to be copied into
> Python — a second copy of a different rule, which is worse.
>
> The two WILL diverge for a book document with no azjlbc `{yy}dir/` address:
> a hand-upload through the Upload page, or a fifth directory convention. The
> browse page would group it under a family and year; this scan would not see
> it, so it could never become pending and would never get a button — silently.
> Record it in `STATUS.md` as the known limit, and if a hand-uploaded book
> section ever appears, that is the trigger to move the family map server-side.

> **`HttpProber` gains `head_info`, and it is not optional.** `head()` returns
> only a boolean, and the card must show status and size (R9). Add:
>
> ```python
> def head_info(self, url: str) -> tuple[int | None, int | None]:
>     """(status, Content-Length). (None, None) when the host is unreachable."""
>     try:
>         r = requests.head(url, timeout=self._timeout_s, allow_redirects=True)
>         if r.status_code >= 400:
>             r = requests.get(url, timeout=self._timeout_s, stream=True,
>                              allow_redirects=True)
>             r.close()
>         raw = r.headers.get("Content-Length")
>         return r.status_code, int(raw) if raw and raw.isdigit() else None
>     except requests.RequestException:
>         return None, None
> ```
>
> Mirror `head()`'s existing HEAD-then-GET fallback — azjlbc.gov's IIS answers
> some HEADs with a 405 — and reuse `head_info` inside `head()` rather than
> keeping two request paths. **Do not reach for it through `getattr` with a
> `None` fallback.** That shape ships a card with no size and no status while
> every test passes, and R9's whole mitigation for "an admin approves without
> looking" is the size and the status.

- [ ] **Step 1: Write the failing tests**

`tests/test_book_formats_route.py`:

```python
"""The pending-edition scan (spec R3, R5, R6)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class FakeProber:
    """Stands in for HttpProber. Records what was asked."""

    def __init__(
        self,
        live: set[str] | None = None,
        broken: set[str] | None = None,
        size: int = 47_000_000,
    ):
        self.live = live or set()
        # Addresses the ladder accepts but that do not actually serve. This is
        # not a contrived shape: `plan_edition` answers a catalogued edition
        # straight from `data/jlbc-book-catalog.json`, which is built to feed a
        # ladder that TOLERATES a 404 and therefore carries URLs nobody ever
        # fetched. A candidate can be offered and be dead.
        self.broken = broken or set()
        self.size = size
        self.asked: list[str] = []

    def head(self, url: str) -> bool:
        self.asked.append(url)
        return url in self.live or url in self.broken

    def head_info(self, url: str) -> tuple[int | None, int | None]:
        self.asked.append(url)
        return (200, self.size) if url in self.live else (404, None)

    def get(self, url: str):
        raise AssertionError("the pending scan must never download a book")


def _client(tmp_path, monkeypatch, *, documents, overlay=None, prober=None):
    import app.routes.book_formats as bf
    import app.routes.books_missing as bm
    import store.report_formats as rf

    # 🔴 Patch the name in `books_missing`, NOT `store.documents`.
    # `books_missing.py` does `from store.documents import load_documents`, so
    # the function is already bound into that module's namespace and patching
    # the source module has no effect — the test would silently run against the
    # real 7,566-document corpus and pass or fail for reasons unrelated to it.
    # The same rule applies to everything `book_formats.py` imports by name:
    # patch `bf.save_edition`, never `rf.save_edition`.
    monkeypatch.setattr(bm, "load_documents", lambda: documents)
    monkeypatch.setattr(rf, "overlay_path", lambda: overlay or (tmp_path / "absent.json"))
    monkeypatch.setattr(bf, "_cache_path", lambda: tmp_path / "probe.json")
    rf.reset_cache()
    app = create_app()
    app.state.book_prober = prober or FakeProber()
    return TestClient(app)


def _doc(url):
    return {"source_url": url, "doc_type": "approps-per-agency", "fiscal_year": 2028}


def test_an_edition_the_table_answers_is_not_pending(tmp_path, monkeypatch):
    # FY2026 approps is in the committed table, so holding it must produce no
    # card. On a healthy corpus this is EVERY edition, which is why the panel
    # is empty by default.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs).get("/api/admin/book-formats").json()
    assert body["pending"] == []


def test_an_edition_with_no_entry_becomes_pending_with_its_candidates(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={
        "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
        "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    assert row["family"] == "Appropriations Report"
    single = row["candidates"]["single_file"]
    assert single["url"].endswith("28ar/fy2028approprpt.pdf")
    assert single["names_its_year"] is True
    # R9: the card claims the address responded and how big it is, so both must
    # come off a real request rather than being assumed from the ladder.
    assert single["status"] == 200
    assert single["bytes"] == 47_000_000


def test_a_candidate_that_does_not_respond_is_shown_as_not_responding(tmp_path, monkeypatch):
    # 🔴 The case that makes this check load-bearing rather than decorative.
    # `plan_edition` is CATALOG-FIRST, so for any edition the committed catalog
    # names it returns URLs with ZERO network calls — and STATUS.md records
    # that catalog carrying unverified addresses, one of which
    # (`budget/fy2027approprpt.pdf`) is a live 404. Without this the panel
    # offers a dead link as confidently as a good one.
    #
    # `broken` is what makes the assertion mean something: the address IS
    # offered, so the row cannot pass by the candidate simply being absent.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(
        live={"https://www.azjlbc.gov/28ar/apprpttoc.pdf"},
        broken={"https://www.azjlbc.gov/28ar/fy2028approprpt.pdf"},
    )
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    single = row["candidates"]["single_file"]
    assert single["url"].endswith("28ar/fy2028approprpt.pdf")
    assert single["status"] == 404 and single["bytes"] is None
    assert row["candidates"]["linked_toc"]["status"] == 200


def test_a_candidate_from_the_rolling_directory_is_flagged_not_dropped(tmp_path, monkeypatch):
    # /budget/apprpttoc.pdf has no year in it and JLBC republishes it every
    # cycle — verified 2026-08-16 that it currently serves the FY2023 book. It
    # must reach the admin WITH a warning, because it is sometimes the right
    # answer (FY2023's own table of contents genuinely lives there).
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/budget/apprpttoc.pdf"})
    body = _client(tmp_path, monkeypatch, documents=docs, prober=prober).get(
        "/api/admin/book-formats"
    ).json()
    row = next(p for p in body["pending"] if p["fiscal_year"] == 2028)
    assert row["candidates"]["linked_toc"]["names_its_year"] is False


def test_an_unreachable_network_says_so_instead_of_reporting_nothing_pending(tmp_path, monkeypatch):
    # A panel that renders "nothing to add" because the WiFi is off is a
    # confident wrong answer. This app cold-starts offline by design.
    class Dead:
        def head(self, url):
            raise OSError("no route to host")

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, prober=Dead()).get(
        "/api/admin/book-formats"
    ).json()
    assert body["online"] is False
    assert "azjlbc.gov" in body["reason"]


def test_the_probe_answer_is_cached_so_opening_the_page_twice_costs_one_look(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/28ar/apprpttoc.pdf"})
    client = _client(tmp_path, monkeypatch, documents=docs, prober=prober)
    client.get("/api/admin/book-formats")
    first = len(prober.asked)
    assert first > 0
    client.get("/api/admin/book-formats")
    assert len(prober.asked) == first


def test_a_healthy_corpus_asks_the_network_nothing(tmp_path, monkeypatch):
    # The scan is free by construction: it reads documents.json and the merged
    # table, both already cached. Only a PENDING edition costs a request, and
    # on a healthy corpus there are none.
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    prober = FakeProber()
    _client(tmp_path, monkeypatch, documents=docs, prober=prober).get("/api/admin/book-formats")
    assert prober.asked == []


def test_a_newly_ingested_edition_appears_at_once(tmp_path, monkeypatch):
    # 🔴 The reason the cache holds PROBE RESULTS and not the whole answer. A
    # cached payload would keep reporting the old pending list for its full TTL,
    # so an analyst who ingests a book sees an admin page saying nothing is
    # waiting — for up to twelve hours, with nothing on screen explaining why.
    # Noticing the book costs no network, so nothing justifies delaying it.
    import app.routes.books_missing as bm

    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    assert client.get("/api/admin/book-formats").json()["pending"] == []
    docs["d2"] = {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}
    monkeypatch.setattr(bm, "load_documents", lambda: docs)
    body = client.get("/api/admin/book-formats").json()
    assert [p["fiscal_year"] for p in body["pending"]] == [2028]


def test_overlay_problems_reach_the_admin(tmp_path, monkeypatch):
    # The ungated corpus route deliberately drops these; this is where they go.
    overlay = tmp_path / "report-formats.json"
    overlay.write_text(json.dumps({"version": 1, "editions": {"Bogus:2028": {}}}), encoding="utf-8")
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    body = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay).get(
        "/api/admin/book-formats"
    ).json()
    assert body["problems"] and "Bogus:2028" in body["problems"][0]


def test_the_route_is_admin_gated(tmp_path, monkeypatch):
    # The gate is app/identity.py: JLBC_USER vs settings.admin_username, and it
    # is OPEN TO EVERYONE until the admin seat is claimed — so a test that
    # forgets save_settings() passes whether or not the route is gated.
    # Verbatim shape from tests/test_admin_tuning_routes.py.
    from harness.settings import Settings, reset_settings_cache, save_settings

    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "analyst1")
    reset_settings_cache()
    save_settings(Settings(admin_username="Destin"))
    reset_settings_cache()
    try:
        client = TestClient(create_app(ingest_worker=None))
        assert client.get("/api/admin/book-formats").status_code == 403
        assert client.put("/api/admin/book-formats", json={
            "family": "Baseline", "fiscal_year": 2028,
            "single_file": "https://x/a.pdf", "linked_toc": None,
        }).status_code == 403
        assert client.post("/api/admin/book-formats/check", json={
            "url": "https://x/a.pdf", "fiscal_year": 2028,
        }).status_code == 403
    finally:
        reset_settings_cache()
```

> **`save_settings(Settings(admin_username=...))` is not optional decoration.**
> `app/identity.py`'s gate is a soft one that stands open until the admin seat
> is claimed, so a gate test that omits it passes identically whether or not
> `Depends(require_admin)` is on the route. Confirmed by reading
> `tests/test_admin_tuning_routes.py::_isolated_share`, whose own comment says
> exactly this.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run python -m pytest tests/test_book_formats_route.py -q`
Expected: FAIL — 404 on `/api/admin/book-formats`

- [ ] **Step 3: Implement the routes**

`app/routes/book_formats.py`:

```python
"""Which book editions have no "Full report" link yet? (spec R3-R6)

WHY a scan and not a hook on ingest: a scan also catches editions added by a
bulk backfill, added on a machine nobody opened the app on, and added before
this feature existed. A hook catches only books that arrive the one expected
way, and the FY2027 Appropriations Report — which appeared through the probe
ladder rather than the catalog — is the proof that they arrive other ways.

WHAT IS CACHED IS THE PROBE, NOT THE ANSWER. The scan is free -- it reads
`documents.json` and the merged link table, both already cached, and touches no
network -- so it runs on every request and a newly ingested edition appears at
once. Only the candidate lookup for a PENDING edition costs requests, and those
results are stored per edition for 12 hours. A fully-answered corpus, the normal
state, costs zero requests and zero staleness.

Caching the whole reply instead would mean an analyst ingests a book, opens
/admin, and is told nothing is waiting -- for up to twelve hours, with nothing on
screen saying why.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.routes.admin import require_admin
from app.routes.books_missing import FAMILY_LABELS, corpus_editions
from ingest.book_discovery import DiscoveryError, plan_edition
from store.config import data_dir
from store.report_formats import (
    format_key,
    load,
    names_its_year,
    save_edition,
)

router = APIRouter()

# Its OWN file. `books_missing.py` has helpers of the same shape, but they are
# hardwired to `book-check.json` -- importing them would make the two panels
# read and overwrite one payload, so whichever ran last would hand the other
# its data and the "Add a JLBC book" panel would report an empty gap it never
# measured. Two files, two helper sets, no shared state.
CACHE_FILENAME = "book-format-probe.json"
CACHE_TTL_SECONDS = 12 * 60 * 60

# Same 6-second bound app/routes/books_missing.py uses and for the same measured
# reason: every ladder rung that does not exist must time out before the next is
# tried, and at the books route's 30s an uncached check took 31 seconds.
PROBE_TIMEOUT_S = 6


def _cache_path() -> Path:
    return data_dir() / CACHE_FILENAME


def _read_cache() -> dict:
    """{edition_key: {"checked_at": iso, "single_file": {...}|None, ...}}."""
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt or absent cache costs a probe, never the page. Same rule as
        # books_missing.py and store/documents.py.
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_cache(payload: dict) -> None:
    try:
        resolved = _cache_path()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        tmp = resolved.with_suffix(f".json.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, resolved)
    except OSError:
        # An unwritable data dir means we probe every time. Slower, never wrong.
        pass


def _is_stale(checked_at: str | None) -> bool:
    if not checked_at:
        return True
    try:
        when = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() > CACHE_TTL_SECONDS


def _candidate(url: str | None, fiscal_year: int, prober) -> dict | None:
    """One format's candidate, with the facts the card shows (R6, R9)."""
    if not url:
        return None
    status, size = prober.head_info(url)
    return {
        "url": url,
        # 🔴 A REAL REQUEST, not an assumption. `plan_edition` is catalog-first,
        # so for a catalogued edition it returns URLs having made no network
        # call at all -- and that catalog is built to feed a ladder that
        # TOLERATES a 404, so it carries addresses nobody verified. Without
        # this the panel offers a dead link exactly as confidently as a good
        # one, and the size that R9 leans on for "a 0.2 MB book is visibly
        # wrong" would never appear.
        "status": status,
        "bytes": size,
        # R6: flagged, never refused. The rolling /budget/ rung produces
        # exactly this shape and is sometimes still the right answer.
        "names_its_year": names_its_year(url, fiscal_year),
    }


def _candidates_for(label, family_slug, year, prober, cache) -> tuple[dict, str | None, bool]:
    """This edition's two candidates, from cache when fresh.

    Third element says whether the network was actually used, so the caller
    only rewrites the cache file when there is something new in it.
    """
    key = format_key(label, year)
    hit = cache.get(key)
    if isinstance(hit, dict) and not _is_stale(hit.get("checked_at")):
        return (
            {"single_file": hit.get("single_file"), "linked_toc": hit.get("linked_toc")},
            hit.get("source"),
            False,
        )
    try:
        plan = plan_edition(family_slug, year, prober=prober)
    except DiscoveryError:
        # JLBC published no whole-report file for this edition we can find.
        # Still pending — the admin can paste one by hand.
        plan = None
    found = {
        "single_file": _candidate(getattr(plan, "single_file_url", None), year, prober),
        "linked_toc": _candidate(getattr(plan, "linked_toc_url", None), year, prober),
    }
    source = getattr(plan, "source", None)
    cache[key] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        **found,
    }
    return found, source, True


def pending_editions(prober, *, refresh: bool = False) -> dict:
    table, problems = load()
    cache = {} if refresh else _read_cache()
    pending, online, reason = [], True, None
    dirty = False

    for family_slug, years in corpus_editions().items():
        label = FAMILY_LABELS[family_slug]
        for year in sorted(years, reverse=True):
            if format_key(label, year) in table:
                continue
            try:
                candidates, source, probed = _candidates_for(
                    label, family_slug, year, prober, cache
                )
                dirty = dirty or probed
            except Exception as exc:  # noqa: BLE001 — network, DNS, timeout
                online = False
                reason = (
                    "Couldn't reach azjlbc.gov to look up the links "
                    f"({type(exc).__name__}). Showing what we knew last time."
                )
                break
            pending.append({
                "family": label,
                "fiscal_year": year,
                "candidates": candidates,
                "source": source,
            })
        if not online:
            break

    if dirty and online:
        _write_cache(cache)

    return {
        "online": online,
        "reason": reason,
        "problems": problems,
        "pending": sorted(pending, key=lambda p: (-p["fiscal_year"], p["family"])),
        "approved": sorted(
            (
                {"family": k.rpartition(":")[0], "fiscal_year": int(k.rpartition(":")[2]),
                 "single_file": v.single_file, "linked_toc": v.linked_toc}
                for k, v in table.items()
            ),
            key=lambda a: (-a["fiscal_year"], a["family"]),
        ),
    }
```

**`approved` is not decoration** — it is what makes an already-answered edition
correctable. Without it the panel can only ever show editions nobody has
answered, so approving a wrong link would be unfixable from the app and the
admin would be back to hand-editing JSON on the share, which is the exact thing
this feature exists to abolish. It is also what the spec's concurrency risk row
assumes ("the loser re-appears as approved-with-the-other-URL, visible on the
same panel").

Then the routes:

```python
@router.get("/api/admin/book-formats")
def book_formats(request: Request, refresh: bool = False, _s=Depends(require_admin)):
    return pending_editions(_probe_with(request), refresh=refresh)


def _probe_with(request: Request):
    from app.routes.books import HttpProber, _prober

    prober = _prober(request)
    if isinstance(prober, HttpProber):
        prober = HttpProber(timeout_s=PROBE_TIMEOUT_S)
    return prober


class EditionWrite(BaseModel):
    family: str
    fiscal_year: int
    single_file: str | None = None
    linked_toc: str | None = None


@router.put("/api/admin/book-formats")
def write_edition(body: EditionWrite, _s=Depends(require_admin)) -> dict:
    """Record one edition's whole-report links.

    The same route both approves a pending edition and corrects one that was
    already answered — the overlay entry replaces its key wholesale either way
    (R1), so there is one write path and no separate "edit" verb to keep in
    step with it.

    A `ValueError` from the store is the admin's own input being refused, so it
    becomes a 400 carrying the store's sentence verbatim — that sentence is
    written for a reader and rewriting it here would give the office two
    wordings for one refusal. Anything else is a real failure and is allowed to
    500: a save that did not happen must never report success.
    """
    try:
        save_edition(body.family, body.fiscal_year, body.single_file, body.linked_toc)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"ok": True}


class UrlCheck(BaseModel):
    url: str
    fiscal_year: int


@router.post("/api/admin/book-formats/check")
def check_url(body: UrlCheck, request: Request, _s=Depends(require_admin)) -> dict:
    """Does a typed address respond, how big is it, does it name its year?

    Same three facts `_candidate` reports, so the pasted link and the offered
    one are described identically on the card.
    """
    try:
        status, size = _probe_with(request).head_info(body.url)
        reason = None
    except Exception as exc:  # noqa: BLE001 — offline is an answer, not a 500
        status, size = None, None
        reason = f"Couldn't reach that address ({type(exc).__name__})."
    return {
        "ok": status is not None and status < 400,
        "status": status,
        "bytes": size,
        "names_its_year": names_its_year(body.url, body.fiscal_year),
        "reason": reason,
    }
```

Register the router in `app/main.py` beside `books_missing_router`.

**No cache invalidation on write.** The pending list is recomputed from the
merged table on every request, and `save_edition` resets the store's own mtime
cache, so an approved edition leaves the list on the very next load. The probe
cache holds only candidate URLs for editions that are still pending, and an
approved edition is no longer consulted.

- [ ] **Step 4: Write the failing write tests**

Append to `tests/test_book_formats_route.py`:

```python
def test_approving_an_edition_writes_it_and_clears_it_from_pending(tmp_path, monkeypatch):
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf",
        "linked_toc": "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    assert r.status_code == 200
    # No ?refresh — the list must be right on an ordinary load, or an admin who
    # presses Approve watches the card sit there and presses it again.
    body = client.get("/api/admin/book-formats").json()
    assert all(p["fiscal_year"] != 2028 for p in body["pending"])


def test_an_already_approved_edition_can_be_corrected(tmp_path, monkeypatch):
    # Approving a wrong link must be recoverable from the app. Without this the
    # only repair is hand-editing JSON on the share — the thing this feature
    # exists to abolish — and the spec's concurrency risk row is unfounded.
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/26ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    for url in ("https://www.azjlbc.gov/26ar/wrong.pdf",
                "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf"):
        assert client.put("/api/admin/book-formats", json={
            "family": "Appropriations Report", "fiscal_year": 2026,
            "single_file": url, "linked_toc": None,
        }).status_code == 200
    row = next(
        a for a in client.get("/api/admin/book-formats").json()["approved"]
        if a["fiscal_year"] == 2026 and a["family"] == "Appropriations Report"
    )
    assert row["single_file"].endswith("fy2026approprpt.pdf")


def test_marking_one_format_as_never_published_is_accepted(tmp_path, monkeypatch):
    # Appropriations Reports before FY2011 genuinely have no single file. The
    # row must then link straight to the table of contents with no chooser.
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": None,
        "linked_toc": "https://www.azjlbc.gov/28ar/apprpttoc.pdf",
    })
    assert r.status_code == 200
    saved = json.loads(overlay.read_text(encoding="utf-8"))
    assert saved["editions"]["Appropriations Report:2028"]["single_file"] is None


def test_marking_BOTH_formats_as_never_published_is_refused_in_plain_english(tmp_path, monkeypatch):
    overlay = tmp_path / "report-formats.json"
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, overlay=overlay)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": None, "linked_toc": None,
    })
    assert r.status_code == 400
    assert "at least one" in r.json()["detail"].lower()


def test_an_unknown_family_is_refused(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    r = client.put("/api/admin/book-formats", json={
        "family": "Baselines", "fiscal_year": 2028,
        "single_file": "https://x/a.pdf", "linked_toc": None,
    })
    assert r.status_code == 400


def test_a_failed_save_reaches_the_caller_rather_than_reporting_success(tmp_path, monkeypatch):
    # The read paths degrade on purpose. This one must not: an admin told
    # nothing has no way to learn the approval did not stick.
    #
    # 🔴 Patch `book_formats`, NOT `store.report_formats`. The route does
    # `from store.report_formats import save_edition`, so the name is already
    # bound into the route module and patching the source module changes
    # nothing — the real save would succeed, the route would return 200, and
    # this test would fail for a reason that has nothing to do with what it
    # asserts. Same trap `_client` documents for `load_documents`.
    import app.routes.book_formats as bf

    def boom(*a, **k):
        raise OSError("the share went away")

    monkeypatch.setattr(bf, "save_edition", boom)
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    with pytest.raises(OSError):
        client.put("/api/admin/book-formats", json={
            "family": "Appropriations Report", "fiscal_year": 2028,
            "single_file": "https://x/a.pdf", "linked_toc": None,
        })


def test_checking_a_typed_url_reports_its_year_and_size(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    prober = FakeProber(live={"https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf"})
    client = _client(tmp_path, monkeypatch, documents=docs, prober=prober)
    r = client.post("/api/admin/book-formats/check", json={
        "url": "https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", "fiscal_year": 2028,
    })
    # Flagged, not refused (R6) — the admin may be correcting a genuinely
    # year-less address, and one such address really exists.
    assert r.json()["names_its_year"] is False
    assert r.json()["ok"] is True
    assert r.json()["bytes"] == 47_000_000


def test_a_typed_url_that_does_not_respond_says_so(tmp_path, monkeypatch):
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs, prober=FakeProber())
    r = client.post("/api/admin/book-formats/check", json={
        "url": "https://www.azjlbc.gov/28ar/nope.pdf", "fiscal_year": 2028,
    }).json()
    assert r["ok"] is False and r["status"] == 404
```

> `TestClient` re-raises a server-side exception by default, which is why the
> failed-save test uses `pytest.raises` rather than asserting a 500. If the app
> is built with `raise_server_exceptions=False` anywhere in this suite, assert
> `r.status_code == 500` instead — but never assert only `!= 200`, which passes
> on a 400 and would let a refusal masquerade as a failure.

Run them before implementing the two write routes:
`uv run python -m pytest tests/test_book_formats_route.py -q -k "approving or corrected or never_published or typed_url or unknown_family or failed_save"`
Expected: FAIL — 405 Method Not Allowed / 404 on `/check`.

- [ ] **Step 5: Run the tests**

Run: `uv run python -m pytest tests/test_book_formats_route.py -q`
Expected: all pass

- [ ] **Step 6: Mutation-check the three guards that carry this task**

Run each in place, confirm the named test goes red, then revert with a
**separate** `git checkout app/routes/book_formats.py`.

| mutate | must turn red |
|---|---|
| `except Exception` branch → `continue` instead of `online = False` | `..._unreachable_network_says_so...` |
| `_candidate`'s `status, size = prober.head_info(url)` → `status, size = 200, None` | `..._candidate_that_does_not_respond...` |
| `_read_cache()` → `{}` unconditionally in `pending_editions` | `..._probe_answer_is_cached...` |

- [ ] **Step 7: Commit**

```bash
git add app/routes/book_formats.py app/routes/books.py app/main.py tests/test_book_formats_route.py
git commit -m "app: report, approve and correct a book edition's whole-report links"
```

---

## Task 5: The approval card

**Files:**
- Create: `webapp/src/admin/ReportLinksPanel.tsx`
- Create: `webapp/src/admin/ReportLinksPanel.test.tsx`
- Modify: `webapp/src/api.ts`
- Modify: `webapp/src/pages/Admin.tsx`

**Interfaces:**
- Consumes: the three routes from Task 4
- Produces:
  - `api.BookFormatCandidate = { url: string; status: number | null; bytes: number | null; names_its_year: boolean }`
  - `api.PendingEdition = { family: string; fiscal_year: number; candidates: { single_file: BookFormatCandidate | null; linked_toc: BookFormatCandidate | null }; source: string | null }`
  - `api.BookFormats = { pending: PendingEdition[]; approved: {...}[]; online: boolean; reason: string | null; problems: string[] }`
  - `api.bookFormats(): Promise<BookFormats>`
  - `api.saveBookFormat(family, fiscalYear, singleFile, linkedToc): Promise<void>`
  - `api.checkBookFormatUrl(url, fiscalYear): Promise<{ ok: boolean; status: number | null; bytes: number | null; names_its_year: boolean; reason: string | null }>`

- [ ] **Step 1: Write the failing tests**

`webapp/src/admin/ReportLinksPanel.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import * as api from "../api";
import { ReportLinksPanel } from "./ReportLinksPanel";

const PENDING: api.PendingEdition = {
  family: "Appropriations Report",
  fiscal_year: 2028,
  candidates: {
    single_file: { url: "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf", status: 200, bytes: 47_000_000, names_its_year: true },
    linked_toc: { url: "https://www.azjlbc.gov/budget/apprpttoc.pdf", status: 200, bytes: 200_000, names_its_year: false },
  },
  source: "probed",
};

const APPROVED: api.ApprovedEdition = {
  family: "Appropriations Report",
  fiscal_year: 2026,
  single_file: "https://www.azjlbc.gov/26ar/fy2026approprpt.pdf",
  linked_toc: "https://www.azjlbc.gov/26ar/apprpttoc.pdf",
};

function stub(over: Partial<api.BookFormats> = {}) {
  vi.spyOn(api, "bookFormats").mockResolvedValue({
    pending: [PENDING], approved: [], online: true, reason: null, problems: [], ...over,
  });
}

test("renders nothing at all when no edition is waiting", async () => {
  // Same rule as NoticesPanel and NeedsAttention directly above it: a box on
  // screen every day teaches an admin to scroll past it. `approved` is
  // populated here on purpose — the already-answered list must not be what
  // keeps the panel on screen.
  stub({ pending: [], approved: [APPROVED] });
  const { container } = render(<ReportLinksPanel />);
  await waitFor(() => expect(api.bookFormats).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test("an already-answered edition can be reopened and corrected", async () => {
  // Without this, approving a wrong link is unfixable from the app and the
  // admin is back to hand-editing JSON on the share — the exact step this
  // feature exists to remove. It is deliberately behind a disclosure, so the
  // panel still renders nothing when nothing is waiting.
  stub({ approved: [APPROVED] });
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue();
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByRole("button", { name: /already answered/i }));
  fireEvent.click(screen.getByRole("button", { name: /change the links for FY 2026/i }));
  fireEvent.change(screen.getAllByLabelText(/web address/i)[0], {
    target: { value: "https://www.azjlbc.gov/26ar/corrected.pdf" },
  });
  fireEvent.click(screen.getAllByRole("button", { name: /^approve$/i })[0]);
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "Appropriations Report", 2026,
      "https://www.azjlbc.gov/26ar/corrected.pdf",
      APPROVED.linked_toc,
    ),
  );
});

test("a candidate that did not respond is marked as not responding", async () => {
  // A dead address must look different from a live one before it is approved.
  // `plan_edition` returns catalogued URLs with no network call at all, and
  // that catalog is known to carry addresses that 404.
  stub({
    pending: [{
      ...PENDING,
      candidates: {
        ...PENDING.candidates,
        single_file: { ...PENDING.candidates.single_file!, status: 404, bytes: null },
      },
    }],
  });
  render(<ReportLinksPanel />);
  expect(await screen.findByText(/didn't respond/i)).toBeInTheDocument();
});

test("a waiting edition shows both addresses as openable links", async () => {
  stub();
  render(<ReportLinksPanel />);
  const link = await screen.findByRole("link", { name: /open to check/i, exact: false });
  expect(link).toHaveAttribute("href", PENDING.candidates.single_file!.url);
  expect(link).toHaveAttribute("target", "_blank");
});

test("the file size is shown, because it is half of R9's defence", async () => {
  // The other half is the year warning. Between them they are the only thing
  // catching an admin who approves without opening either link — a 0.2 MB
  // "book" or a 47 MB "table of contents" is visibly wrong. A size that
  // silently never renders would leave that risk unmitigated with every test
  // green, so it is asserted rather than assumed.
  stub();
  render(<ReportLinksPanel />);
  expect(await screen.findByText(/47\.0 MB/)).toBeInTheDocument();
});

test("an address that does not name the edition's year is flagged", async () => {
  // The rolling /budget/ address returns a live 200 for a year that does not
  // exist yet. This warning is the only thing standing between that and a
  // button opening the wrong year's report.
  stub();
  render(<ReportLinksPanel />);
  expect(await screen.findByText(/doesn't mention FY 2028/i)).toBeInTheDocument();
});

test("approving sends both addresses and removes the card", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue();
  render(<ReportLinksPanel />);
  fireEvent.click(await screen.findByRole("button", { name: /^approve$/i }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "Appropriations Report", 2028,
      PENDING.candidates.single_file!.url,
      PENDING.candidates.linked_toc!.url,
    ),
  );
});

test("marking a format as never published sends null for it", async () => {
  stub();
  const save = vi.spyOn(api, "saveBookFormat").mockResolvedValue();
  render(<ReportLinksPanel />);
  fireEvent.click((await screen.findAllByRole("button", { name: /none published/i }))[0]);
  fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "Appropriations Report", 2028, null, PENDING.candidates.linked_toc!.url,
    ),
  );
});

test("a typed replacement is checked before it can be approved", async () => {
  stub();
  const check = vi
    .spyOn(api, "checkBookFormatUrl")
    .mockResolvedValue({ ok: true, status: 200, bytes: 123, names_its_year: true, reason: null });
  render(<ReportLinksPanel />);
  fireEvent.click((await screen.findAllByRole("button", { name: /use a different link/i }))[0]);
  fireEvent.change(screen.getByLabelText(/web address/i), {
    target: { value: "https://www.azjlbc.gov/28ar/other.pdf" },
  });
  fireEvent.click(screen.getByRole("button", { name: /check/i }));
  await waitFor(() => expect(check).toHaveBeenCalled());
});

test("an offline check says so instead of showing an empty list", async () => {
  stub({ pending: [], online: false, reason: "Couldn't reach azjlbc.gov to look up the links." });
  render(<ReportLinksPanel />);
  expect(await screen.findByText(/couldn't reach azjlbc\.gov/i)).toBeInTheDocument();
});

test("a problem with the saved file is shown to the admin", async () => {
  stub({ pending: [], problems: ["Ignoring the saved links for Bogus:2028: unknown report family."] });
  render(<ReportLinksPanel />);
  expect(await screen.findByText(/ignoring the saved links/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp && npx vitest run src/admin/ReportLinksPanel.test.tsx`
Expected: FAIL — cannot resolve `./ReportLinksPanel`

- [ ] **Step 3: Add the API client calls**

In `webapp/src/api.ts`. `fail()` is the existing helper that surfaces FastAPI's
`detail`, which is what carries the store's own refusal sentence to the screen —
use it rather than throwing a generic error, or "at least one of the two formats
must have a link" becomes "Request failed".

```ts
export interface BookFormatCandidate {
  url: string;
  /** HTTP status from a real request. Null when the host was unreachable. */
  status: number | null;
  /** From Content-Length. Null when the server omits it — show nothing, never a 0. */
  bytes: number | null;
  /** False when the address does not mention this edition's year (spec R6). */
  names_its_year: boolean;
}

export interface PendingEdition {
  family: string;
  fiscal_year: number;
  candidates: {
    single_file: BookFormatCandidate | null;
    linked_toc: BookFormatCandidate | null;
  };
  source: string | null;
}

export interface ApprovedEdition {
  family: string;
  fiscal_year: number;
  single_file: string | null;
  linked_toc: string | null;
}

export interface BookFormats {
  pending: PendingEdition[];
  approved: ApprovedEdition[];
  online: boolean;
  reason: string | null;
  /** One sentence per row dropped from the saved file on the share. */
  problems: string[];
}

export async function bookFormats(refresh = false): Promise<BookFormats> {
  const r = await fetch(`/api/admin/book-formats${refresh ? "?refresh=true" : ""}`);
  if (!r.ok) await fail(r, "whole-report links");
  return r.json();
}

export async function saveBookFormat(
  family: string,
  fiscalYear: number,
  singleFile: string | null,
  linkedToc: string | null,
): Promise<void> {
  const r = await fetch("/api/admin/book-formats", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      family,
      fiscal_year: fiscalYear,
      single_file: singleFile,
      linked_toc: linkedToc,
    }),
  });
  if (!r.ok) await fail(r, "saving the whole-report links");
}

export async function checkBookFormatUrl(
  url: string,
  fiscalYear: number,
): Promise<{
  ok: boolean;
  status: number | null;
  bytes: number | null;
  names_its_year: boolean;
  reason: string | null;
}> {
  const r = await fetch("/api/admin/book-formats/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, fiscal_year: fiscalYear }),
  });
  if (!r.ok) await fail(r, "checking that address");
  return r.json();
}
```

- [ ] **Step 4: Build the panel**

`webapp/src/admin/ReportLinksPanel.tsx`. The skeleton — the choice model is the
part worth getting from here rather than inventing, because "keep the candidate
/ replace it / it was never published" has to be one value per format, not three
booleans that can disagree:

```tsx
import { useEffect, useState } from "react";
import * as api from "../api";

/** What the admin has decided about ONE format, before pressing Approve.
 *
 *  A single value rather than separate `dismissed` / `replacement` flags: with
 *  two flags, "replaced AND marked never-published" is representable and
 *  nothing says which wins. Here it cannot be expressed. */
type Choice =
  | { kind: "candidate" }                 // use what the app found
  | { kind: "none" }                      // JLBC published no such format
  | { kind: "typed"; url: string };       // the admin pasted one

type Decisions = Record<string, Choice>;   // key: `${fiscal_year}:${family}:${format}`

function urlFor(choice: Choice, candidate: api.BookFormatCandidate | null): string | null {
  if (choice.kind === "none") return null;
  if (choice.kind === "typed") return choice.url.trim() || null;
  return candidate?.url ?? null;
}

function sizeLabel(bytes: number | null): string {
  // Nothing rather than "0 MB" when the server omitted Content-Length: an
  // invented zero next to a 600-page book reads as a broken link.
  return bytes === null ? "" : `${(bytes / 1e6).toFixed(1)} MB`;
}

export function ReportLinksPanel() {
  const [state, setState] = useState<api.BookFormats | null>(null);
  const [decisions, setDecisions] = useState<Decisions>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.bookFormats().then(setState, (e) => setError(String(e.message ?? e)));
  }, []);

  // Render NOTHING until there is something to say. Deliberately no loading
  // box: an empty panel and a loading panel look identical, so the loading one
  // would flash on every admin page open for a feature that is silent almost
  // always. Same rule as NoticesPanel and NeedsAttention directly above.
  if (!state && !error) return null;
  if (state && state.online && state.pending.length === 0 && state.problems.length === 0) {
    return null;
  }

  // ... cards, one per state.pending entry, per the requirements below ...
}
```

Requirements, each pinned by a test above:

- **Renders nothing** when `pending` is empty AND `online` AND no `problems`,
  **however many editions are in `approved`** — the already-answered list is a
  reference, never a reason to occupy the page.
- **Never renders a loading box** — an empty panel and a loading panel look the
  same, and the loading one flashes on every admin page open.
- One card per pending edition, titled `FY {year} {family} — no "Full report" link yet`.
- Per format: the address, its size in MB when known, **Open to check ↗**
  (`target="_blank" rel="noopener noreferrer"`), **Use a different link**,
  **None published**.
- **A candidate whose `status` is not 2xx says so** — *"This address didn't
  respond (404)."* — and `status === null` says the site could not be reached.
  A dead link must not look identical to a good one, because a catalogued
  candidate is returned with no network call and the catalog carries addresses
  nobody verified.
- The R6 warning renders when `names_its_year` is false:
  *"This address doesn't mention FY 2028 — open it before approving."*
- **Approve** sends the current choice for both formats; **Not now** does nothing.
- Approve is disabled when both formats are marked none-published, with the
  reason visible rather than a silently dead button.
- `problems` render as plain sentences above the cards.
- `online === false` renders `reason` and no claim about what is or is not missing.
- **Already answered** — a collapsed disclosure listing `approved`, each row
  offering **Change the links for FY {year}**, which opens the same per-format
  editor and the same **Approve** against the same `PUT`. It renders only when
  something else has already put the panel on screen, so it costs nothing on a
  healthy install. Without it an approved mistake is unfixable from the app and
  the admin is back to hand-editing JSON on the share.

> **jsdom applies no stylesheet.** Nothing in this task is visually verified by
> its tests; Task 6's acceptance walk is where the card is actually looked at.

- [ ] **Step 5: Mount it**

In `webapp/src/pages/Admin.tsx`, inside `<Group title="Needs attention">`,
after `<NeedsAttention …/>` and before `<NoticesPanel …/>`. It self-fetches, like
`AliasesPanel` and `IssuesPanel`, so a slow azjlbc.gov probe cannot delay the
rest of the page.

- [ ] **Step 6: Run everything**

Run: `cd webapp && npx vitest run && npx tsc -b && npm run build`
Expected: all pass, exit 0, clean build

- [ ] **Step 7: Commit**

```bash
git add webapp/src/admin/ReportLinksPanel.tsx webapp/src/admin/ReportLinksPanel.test.tsx webapp/src/api.ts webapp/src/pages/Admin.tsx
git commit -m "webapp: approve a new book edition's Full report links from /admin"
```

---

## Task 6: The verifier follows the data, and somebody watches the whole loop

**Files:**
- Modify: `scripts/verify_report_formats.py`
- Modify: `STATUS.md`

**Interfaces:**
- Consumes: `store.report_formats.load`

- [ ] **Step 1: Point the verifier at the merged table**

Replace the regex-over-TypeScript reader with:

```python
from store.report_formats import load


def rows() -> list[tuple[str, str, str]]:
    """(edition key, format name, url) for every curated URL.

    Reads the MERGED table — committed file plus the admin's approvals — so
    this checks what the app actually serves, not only what shipped. Overlay
    problems are printed before the check rather than swallowed.
    """
    table, problems = load()
    for problem in problems:
        print(f"note: {problem}")
    out = []
    for key, formats in sorted(table.items()):
        for kind, url in (("single", formats.single_file), ("toc", formats.linked_toc)):
            if url:
                out.append((key, kind, url))
    return out
```

Keep the existing "parsed no URLs must FAIL, not report a clean sweep" guard and
the `--full` mode unchanged. Update the module docstring: it no longer parses
TypeScript.

- [ ] **Step 2: Run it**

Run: `uv run python scripts/verify_report_formats.py`
Expected: `72 curated URLs`, `72 ok, 0 failed`

- [ ] **Step 3: Full gates on the merged tree**

Run: `uv run python -m pytest -q`
Run: `cd webapp && npx vitest run && npx tsc -b && npm run build`
Expected: all green. Record the counts — they go in `STATUS.md`.

- [ ] **Step 4: THE ACCEPTANCE WALK — the panel is empty on a healthy corpus**

All 39 editions are already answered, so a working feature and a completely
broken one both render nothing. This step is the only thing that tells them
apart, and it must not be skipped or replaced with reasoning.

Set up a scratch data dir that symlinks the corpus read-only (the pattern the
admin-extensions eval used, so the 14 GB working dir is never modified), then:

1. **Make one edition pending.** Write an overlay that answers nothing, and
   temporarily remove `"Appropriations Report:2027"` from a COPY of
   `data/report-formats.json`. Start the server:
   `JLBC_DATA_DIR=<scratch> uv run uvicorn app.main:create_app --factory --port 9301`
2. Open `/admin`. **Expected:** a card reading *FY 2027 Appropriations Report —
   no "Full report" link yet*, offering `27ar/fy2027approprpt.pdf` and
   `27ar/apprpttoc.pdf`, each with a working **Open to check ↗** and a real
   size (~43.9 MB and ~1 page respectively). **A missing size or a size of
   "0 MB" is a failure, not a cosmetic gap** — it is half of what R9 relies on.
3. Press **Approve**. **Expected:** the card disappears **without a manual
   refresh**, and `<scratch>/report-formats.json` now holds the edition.
4. Open `/search`, expand Fiscal Year 2027. **Expected:** the FY 2027
   Appropriations Report row shows **Full report** and opens the chooser at
   those two files.
5. Back on `/admin`, expand **Already answered**, choose **Change the links for
   FY 2027**, paste a different address and Approve. **Expected:** the browse
   row follows it. Then put the correct address back.
6. **Use a different link** on one format, paste
   `https://www.azjlbc.gov/26ar/fy2026approprpt.pdf` (a real, live, WRONG-year
   file), press Check. **Expected:** the R6 warning renders. Do not approve it.
7. Paste an address that does not exist (`…/27ar/nope.pdf`) and press Check.
   **Expected:** it reports that the address did not respond, with the status.
8. **None published** on the single file, then Approve. **Expected:** the
   browse row becomes a plain link straight to the table of contents, with no
   chooser dialog.
9. **Disconnect the network**, restart the server, open `/admin`.
   **Expected:** the panel says it could not reach azjlbc.gov. It must NOT say
   there is nothing to add.

> ⚠ `uvicorn` runs without `--reload`, so **Python changes need a server
> restart**; only the SPA picks up a rebuild. Several rounds of testing on this
> project have measured a stale build.

- [ ] **Step 5: Record it in STATUS.md**

A section dated the day it ships, covering: what shipped, the suite counts, the
acceptance-walk result **including anything that did not behave as written
above**, that no eval was run and why, and the three standing items — the
accepted approve-without-looking risk (R9), the fact that breakage of
already-approved links is left to `scripts/verify_report_formats.py` (R13), and
the R3 derivation deviation recorded in Task 4 (a book document with no
azjlbc `{yy}dir/` address would render on the browse page and never become
pending; measured identical on 7,574 documents 2026-08-16).

- [ ] **Step 6: Commit, merge, push, clean up**

```bash
git add scripts/verify_report_formats.py STATUS.md
git commit -m "scripts+docs: the link verifier reads the merged table; record the acceptance walk"
git fetch origin && git log --oneline -1 origin/master   # master moves in large merges
```

Then merge to `master`, **re-run the full gates on the merged tree** (this repo
has recorded a cross-branch defect where git merged cleanly and both suites
stayed green), push, and `git worktree remove` + `git branch -d`.

---

## Notes for the implementer

- **Read `STATUS.md` before starting.** It is the single source of truth for
  what is shipped and what is broken, and it moves daily.
- **The plan's prose is more reliable than its code.** Where they disagree, run
  the code and follow the measurement, then record the deviation.
- **Do not add a fallback that guesses a URL** anywhere in this feature. Four
  naming conventions exist, the ladder already encodes them, and a guess behind
  a button labelled "Full report" is a false provenance claim.
- **Do not report a count as a success measure.** "39 editions answered" says
  nothing about whether any of them is right; the year guard and the acceptance
  walk are what carry that weight.
- **Patch names where they are BOUND, not where they are defined.** Every module
  here does `from x import y`, so `monkeypatch.setattr(x, "y", ...)` changes
  nothing. This plan's own tests were wrong about it once; check each one.
- **Every network fact on the card must come from a request.** `plan_edition`
  answers a catalogued edition with zero network calls, and that catalog is
  built to tolerate a 404, so "the ladder returned it" is not evidence the file
  exists.
