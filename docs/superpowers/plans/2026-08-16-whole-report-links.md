# Whole-Report Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-08-16-whole-report-links-design.md`](../specs/2026-08-16-whole-report-links-design.md) (R1–R13)

**Goal:** A new JLBC book edition surfaces on the Admin page for one-click
approval of its "Full report" links, so nobody ever edits code to add a year.

**Architecture:** The table of whole-report URLs moves out of
`webapp/src/reportFamilies.ts` into a committed `data/report-formats.json`,
merged at read time with an admin overlay on the shared drive. A new admin route
scans the corpus for editions that table does not answer, resolves candidate
URLs through the *existing* `ingest/book_discovery.plan_edition`, and an admin
panel approves, replaces, or marks a format as never published.

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
| `app/routes/book_formats.py` | **create.** Pending scan, probe cache, the three admin routes |
| `app/routes/corpus.py` | **modify.** `GET /api/corpus/documents` gains `report_formats` |
| `app/main.py` | **modify.** Register the new router |
| `scripts/verify_report_formats.py` | **modify.** Read the merged table instead of parsing TypeScript |
| `webapp/src/reportFamilies.ts` | **modify.** Delete `REPORT_FORMATS`; `reportFormats()` takes the table |
| `webapp/src/api.ts` | **modify.** `report_formats` on the corpus response + three admin calls |
| `webapp/src/pages/Search.tsx` | **modify.** Thread the table to the two call sites |
| `webapp/src/admin/ReportLinksPanel.tsx` | **create.** The approval card |
| `webapp/src/pages/Admin.tsx` | **modify.** Mount the panel in the "Needs attention" group |
| `tests/test_report_formats_store.py` | **create.** Load/merge/validate/save |
| `tests/test_report_formats_data.py` | **create.** The four guards against the committed file |
| `tests/test_book_formats_route.py` | **create.** Scan, probe cache, offline, the two writes |
| `webapp/src/reportFamilies.test.ts` | **modify.** Drop the four URL guards (they move to pytest) |
| `webapp/src/pages/Search.test.tsx` | **modify.** Fixture gains `report_formats` |
| `webapp/src/admin/ReportLinksPanel.test.tsx` | **create.** Panel behaviour |

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
    # A count, deliberately: this file was generated from the shipped
    # TypeScript, and a regex that silently matches fewer rows would look like
    # a clean smaller table rather than a loss.
    assert len(load_shipped()) == 39
```

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


def names_its_year(url: str, fiscal_year: int) -> bool:
    """Does this address mention the year it claims to be?

    JLBC's own filenames carry it — 19AR/FY2019AppropRpt.pdf,
    26baseline/26baselinesinglefile.pdf — so this is checkable with no network.
    It is the only defence against the probe ladder's rolling /budget/ rung,
    which returns a live 200 for a year that does not exist yet.

    The host is stripped first: "azjlbc" contains no digits today, but a future
    host or a query string could contribute a stray "27" and quietly make this
    guard always true.
    """
    path = url.lower().split("://", 1)[-1].partition("/")[2]
    return str(fiscal_year) in path or f"{fiscal_year % 100:02d}" in path


def shipped_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / REPORT_FORMATS_FILE


def overlay_path() -> Path:
    return data_dir() / REPORT_FORMATS_FILE


_lock = threading.Lock()
# (path_str, mtime_ns, size) -> parsed. Two entries at most (shipped, overlay).
_cache: dict[str, tuple[tuple[str, int, int], dict[str, EditionFormats]]] = {}


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
        return hit[1], []
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
        _cache[str(resolved)] = (stamp, parsed)
    return parsed, problems


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
        # The rolling directory: a live 200 that names no year at all. This is
        # the case the whole guard exists for.
        ("https://www.azjlbc.gov/budget/apprpttoc.pdf", 2028, False),
        # The realistic copy-paste slip: last year's report under this year's key.
        ("https://www.azjlbc.gov/19AR/FY2019AppropRpt.pdf", 2018, False),
    ],
)
def test_names_its_year(url, year, expected):
    assert names_its_year(url, year) is expected
```

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
git add data/report-formats.json store/report_formats.py tests/test_report_formats_store.py tests/test_report_formats_data.py
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
- Modify: `webapp/src/pages/Search.test.tsx` (fixture)

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
git add webapp/src/reportFamilies.ts webapp/src/reportFamilies.test.ts webapp/src/api.ts webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx
git commit -m "webapp: whole-report links come from the server, not a table in the bundle"
```

---

## Task 4: Which editions has nobody answered for?

**Files:**
- Create: `app/routes/book_formats.py`
- Modify: `app/main.py`
- Create: `tests/test_book_formats_route.py`

**Interfaces:**
- Consumes: `store.report_formats.load`, `format_key`, `names_its_year`;
  `app.routes.books_missing.corpus_editions` and `FAMILY_LABELS`;
  `ingest.book_discovery.plan_edition`, `DiscoveryError`;
  `app.routes.books.HttpProber`, `_prober`
- Produces: `GET /api/admin/book-formats` → the panel's whole state

> **Reuse, do not rewrite.** `app/routes/books_missing.py::corpus_editions()`
> already answers "which book editions does the corpus hold", reading each
> document's `source_url` and never its doc_id (21 doc_ids contradict their own
> title), and it already recognises all FOUR of JLBC's directory conventions —
> a two-pattern version was written first and measured wrong. `FAMILY_LABELS`
> in the same module maps `"approps" → "Appropriations Report"`. A second
> implementation of either would drift.

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

    def __init__(self, live: set[str] | None = None):
        self.live = live or set()
        self.asked: list[str] = []

    def head(self, url: str) -> bool:
        self.asked.append(url)
        return url in self.live

    def get(self, url: str):
        raise AssertionError("the pending scan must never download a book")


def _client(tmp_path, monkeypatch, *, documents, overlay=None, prober=None):
    import app.routes.books_missing as bm
    import store.report_formats as rf

    # 🔴 Patch the name in `books_missing`, NOT `store.documents`.
    # `books_missing.py` does `from store.documents import load_documents`, so
    # the function is already bound into that module's namespace and patching
    # the source module has no effect — the test would silently run against the
    # real 7,566-document corpus and pass or fail for reasons unrelated to it.
    monkeypatch.setattr(bm, "load_documents", lambda: documents)
    monkeypatch.setattr(rf, "overlay_path", lambda: overlay or (tmp_path / "absent.json"))
    monkeypatch.setattr("app.routes.book_formats._cache_path", lambda: tmp_path / "probe.json")
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
    assert row["candidates"]["single_file"]["url"].endswith("28ar/fy2028approprpt.pdf")
    assert row["candidates"]["single_file"]["names_its_year"] is True


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
    client.get("/api/admin/book-formats")
    assert len(prober.asked) == first


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

- [ ] **Step 3: Implement the route**

`app/routes/book_formats.py`:

```python
"""Which book editions have no "Full report" link yet? (spec R3-R6)

WHY a scan and not a hook on ingest: a scan also catches editions added by a
bulk backfill, added on a machine nobody opened the app on, and added before
this feature existed. A hook catches only books that arrive the one expected
way, and the FY2027 Appropriations Report — which appeared through the probe
ladder rather than the catalog — is the proof that they arrive other ways.

The scan itself is free: it reads `documents.json` and the merged link table,
both already cached, and touches no network. Only a PENDING edition is probed,
and that answer is cached for 12 hours. A fully-answered corpus — the normal
state — costs zero requests.
"""
from __future__ import annotations

import json
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

CACHE_FILENAME = "book-format-probe.json"
CACHE_TTL_SECONDS = 12 * 60 * 60

# Same 6-second bound app/routes/books_missing.py uses and for the same measured
# reason: every ladder rung that does not exist must time out before the next is
# tried, and at the books route's 30s an uncached check took 31 seconds.
PROBE_TIMEOUT_S = 6


def _cache_path() -> Path:
    return data_dir() / CACHE_FILENAME


def _candidate(url: str | None, fiscal_year: int, prober) -> dict | None:
    """One format's candidate, with the two facts the card shows."""
    if not url:
        return None
    size = None
    head = getattr(prober, "head_size", None)
    if head is not None:
        size = head(url)          # bytes, or None when the server omits it
    return {
        "url": url,
        "bytes": size,
        # R6: flagged, never refused. The rolling /budget/ rung produces
        # exactly this shape and is sometimes still the right answer.
        "names_its_year": names_its_year(url, fiscal_year),
    }


def pending_editions(prober, *, refresh: bool = False) -> dict:
    cached = _read_cache()
    if not refresh and cached and not _is_stale(cached.get("checked_at")):
        return cached

    table, problems = load()
    pending, online, reason = [], True, None
    for family_slug, years in corpus_editions().items():
        label = FAMILY_LABELS[family_slug]
        for year in sorted(years, reverse=True):
            if format_key(label, year) in table:
                continue
            try:
                plan = plan_edition(family_slug, year, prober=prober)
            except DiscoveryError:
                # JLBC published no whole-report file for this edition we can
                # find. Still pending — the admin can paste one by hand.
                plan = None
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
                "candidates": {
                    "single_file": _candidate(
                        getattr(plan, "single_file_url", None), year, prober),
                    "linked_toc": _candidate(
                        getattr(plan, "linked_toc_url", None), year, prober),
                },
                "source": getattr(plan, "source", None),
            })
        if not online:
            break

    if not online and cached:
        payload = dict(cached)
        payload.update(online=False, reason=reason, problems=problems)
        return payload

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
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
    if online:
        _write_cache(payload)
    return payload
```

`_read_cache`, `_write_cache` and `_is_stale` are byte-identical in intent to
`app/routes/books_missing.py`'s. **Import them from there rather than copying**;
if their signatures make that awkward, move all three into a small shared helper
and have `books_missing.py` import it, so there is one implementation.

Then the route:

```python
@router.get("/api/admin/book-formats")
def book_formats(request: Request, refresh: bool = False, _s=Depends(require_admin)):
    from app.routes.books import HttpProber, _prober

    prober = _prober(request)
    if isinstance(prober, HttpProber):
        prober = HttpProber(timeout_s=PROBE_TIMEOUT_S)
    return pending_editions(prober, refresh=refresh)
```

Register it in `app/main.py` beside `books_missing_router`.

> **`head_size` does not exist on `HttpProber` yet.** `_candidate` above calls
> it through `getattr` so the scan works without it, but the card is meant to
> show file size (R9). Add a `head_size(url) -> int | None` method to
> `HttpProber` returning `Content-Length` as an int, and have `FakeProber`
> implement it too. If adding it to `HttpProber` turns out to widen a class
> other routes depend on, put the helper in `book_formats.py` instead and note
> the deviation.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_book_formats_route.py -q`
Expected: all pass

- [ ] **Step 5: Mutation-check the offline guard**

Temporarily change the `except Exception` branch to `continue` instead of
setting `online = False`. Re-run:

Run: `uv run python -m pytest tests/test_book_formats_route.py -q`
Expected: FAIL on
`test_an_unreachable_network_says_so_instead_of_reporting_nothing_pending`.
Revert with a separate `git checkout app/routes/book_formats.py`.

- [ ] **Step 6: Commit**

```bash
git add app/routes/book_formats.py app/main.py tests/test_book_formats_route.py
git commit -m "app: report which book editions have no whole-report link yet"
```

---

## Task 5: Approving, replacing, and marking a format as never published

**Files:**
- Modify: `app/routes/book_formats.py`
- Modify: `tests/test_book_formats_route.py`

**Interfaces:**
- Consumes: `store.report_formats.save_edition`, `names_its_year`
- Produces:
  - `PUT /api/admin/book-formats`, body
    `{"family": str, "fiscal_year": int, "single_file": str | null, "linked_toc": str | null}`
    → `{"ok": true}`; 400 with a plain sentence on refusal
  - `POST /api/admin/book-formats/check`, body `{"url": str, "fiscal_year": int}`
    → `{"ok": bool, "status": int | null, "bytes": int | null, "names_its_year": bool, "reason": str | null}`

- [ ] **Step 1: Write the failing tests**

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
    body = client.get("/api/admin/book-formats?refresh=true").json()
    assert all(p["fiscal_year"] != 2028 for p in body["pending"])


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
    import store.report_formats as rf

    def boom(*a, **k):
        raise OSError("the share went away")

    monkeypatch.setattr(rf, "save_edition", boom)
    docs = {"d1": {"source_url": "https://www.azjlbc.gov/28ar/axs.pdf"}}
    client = _client(tmp_path, monkeypatch, documents=docs)
    r = client.put("/api/admin/book-formats", json={
        "family": "Appropriations Report", "fiscal_year": 2028,
        "single_file": "https://x/a.pdf", "linked_toc": None,
    })
    assert r.status_code >= 500 or r.status_code == 400
    assert "ok" not in r.json() or r.json().get("ok") is not True


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run python -m pytest tests/test_book_formats_route.py -q -k "approving or never_published or typed_url or unknown_family or failed_save"`
Expected: FAIL — 405 Method Not Allowed

- [ ] **Step 3: Implement**

```python
class EditionWrite(BaseModel):
    family: str
    fiscal_year: int
    single_file: str | None = None
    linked_toc: str | None = None


@router.put("/api/admin/book-formats")
def write_edition(body: EditionWrite, _s=Depends(require_admin)) -> dict:
    """Record one edition's whole-report links.

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
    _invalidate_cache()
    return {"ok": True}


class UrlCheck(BaseModel):
    url: str
    fiscal_year: int


@router.post("/api/admin/book-formats/check")
def check_url(body: UrlCheck, request: Request, _s=Depends(require_admin)) -> dict:
    from app.routes.books import HttpProber, _prober

    prober = _prober(request)
    if isinstance(prober, HttpProber):
        prober = HttpProber(timeout_s=PROBE_TIMEOUT_S)
    try:
        ok = bool(prober.head(body.url))
        reason = None
    except Exception as exc:  # noqa: BLE001 — offline is an answer, not a 500
        ok, reason = False, f"Couldn't reach that address ({type(exc).__name__})."
    size = None
    head_size = getattr(prober, "head_size", None)
    if ok and head_size is not None:
        size = head_size(body.url)
    return {
        "ok": ok,
        "bytes": size,
        "names_its_year": names_its_year(body.url, body.fiscal_year),
        "reason": reason,
    }
```

`_invalidate_cache()` deletes `_cache_path()` if it exists, ignoring `OSError` —
a stale probe cache after an approval would leave the just-approved edition on
the panel until the TTL expired.

- [ ] **Step 4: Run the tests**

Run: `uv run python -m pytest tests/test_book_formats_route.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add app/routes/book_formats.py tests/test_book_formats_route.py
git commit -m "app: approve, replace or dismiss a book edition's whole-report links"
```

---

## Task 6: The approval card

**Files:**
- Create: `webapp/src/admin/ReportLinksPanel.tsx`
- Create: `webapp/src/admin/ReportLinksPanel.test.tsx`
- Modify: `webapp/src/api.ts`
- Modify: `webapp/src/pages/Admin.tsx`

**Interfaces:**
- Consumes: the three routes from Tasks 4–5
- Produces:
  - `api.BookFormatCandidate = { url: string; bytes: number | null; names_its_year: boolean }`
  - `api.PendingEdition = { family: string; fiscal_year: number; candidates: { single_file: BookFormatCandidate | null; linked_toc: BookFormatCandidate | null }; source: string | null }`
  - `api.BookFormats = { pending: PendingEdition[]; approved: {...}[]; online: boolean; reason: string | null; problems: string[] }`
  - `api.bookFormats(): Promise<BookFormats>`
  - `api.saveBookFormat(family, fiscalYear, singleFile, linkedToc): Promise<void>`
  - `api.checkBookFormatUrl(url, fiscalYear): Promise<{ ok: boolean; bytes: number | null; names_its_year: boolean; reason: string | null }>`

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
    single_file: { url: "https://www.azjlbc.gov/28ar/fy2028approprpt.pdf", bytes: 47_000_000, names_its_year: true },
    linked_toc: { url: "https://www.azjlbc.gov/budget/apprpttoc.pdf", bytes: 200_000, names_its_year: false },
  },
  source: "probed",
};

function stub(over: Partial<api.BookFormats> = {}) {
  vi.spyOn(api, "bookFormats").mockResolvedValue({
    pending: [PENDING], approved: [], online: true, reason: null, problems: [], ...over,
  });
}

test("renders nothing at all when no edition is waiting", async () => {
  // Same rule as NoticesPanel and NeedsAttention directly above it: a box on
  // screen every day teaches an admin to scroll past it.
  stub({ pending: [] });
  const { container } = render(<ReportLinksPanel />);
  await waitFor(() => expect(api.bookFormats).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

test("a waiting edition shows both addresses as openable links", async () => {
  stub();
  render(<ReportLinksPanel />);
  const link = await screen.findByRole("link", { name: /open to check/i, exact: false });
  expect(link).toHaveAttribute("href", PENDING.candidates.single_file!.url);
  expect(link).toHaveAttribute("target", "_blank");
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
    .mockResolvedValue({ ok: true, bytes: 123, names_its_year: true, reason: null });
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
): Promise<{ ok: boolean; bytes: number | null; names_its_year: boolean; reason: string | null }> {
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

- **Renders nothing** when `pending` is empty AND `online` AND no `problems`.
- **Never renders a loading box** — an empty panel and a loading panel look the
  same, and the loading one flashes on every admin page open.
- One card per pending edition, titled `FY {year} {family} — no "Full report" link yet`.
- Per format: the address, its size in MB when known, **Open to check ↗**
  (`target="_blank" rel="noopener noreferrer"`), **Use a different link**,
  **None published**.
- The R6 warning renders when `names_its_year` is false:
  *"This address doesn't mention FY 2028 — open it before approving."*
- **Approve** sends the current choice for both formats; **Not now** does nothing.
- Approve is disabled when both formats are marked none-published, with the
  reason visible rather than a silently dead button.
- `problems` render as plain sentences above the cards.
- `online === false` renders `reason` and no claim about what is or is not missing.

> **jsdom applies no stylesheet.** Nothing in this task is visually verified by
> its tests; Task 7's acceptance walk is where the card is actually looked at.

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

## Task 7: The verifier follows the data, and somebody watches the whole loop

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
   `27ar/apprpttoc.pdf`, each with a working **Open to check ↗**.
3. Press **Approve**. **Expected:** the card disappears, and
   `<scratch>/report-formats.json` now holds the edition.
4. Open `/search`, expand Fiscal Year 2027. **Expected:** the FY 2027
   Appropriations Report row shows **Full report** and opens the chooser at
   those two files.
5. **Use a different link** on one format, paste
   `https://www.azjlbc.gov/26ar/fy2026approprpt.pdf` (a real, live, WRONG-year
   file), press Check. **Expected:** the R6 warning renders. Do not approve it.
6. **None published** on the single file, then Approve. **Expected:** the
   browse row becomes a plain link straight to the table of contents, with no
   chooser dialog.
7. **Disconnect the network**, restart the server, open `/admin`.
   **Expected:** the panel says it could not reach azjlbc.gov. It must NOT say
   there is nothing to add.

> ⚠ `uvicorn` runs without `--reload`, so **Python changes need a server
> restart**; only the SPA picks up a rebuild. Several rounds of testing on this
> project have measured a stale build.

- [ ] **Step 5: Record it in STATUS.md**

A section dated the day it ships, covering: what shipped, the suite counts, the
acceptance-walk result **including anything that did not behave as written
above**, that no eval was run and why, and the two standing items — the accepted
approve-without-looking risk (R9) and the fact that breakage of already-approved
links is left to `scripts/verify_report_formats.py` (R13).

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
