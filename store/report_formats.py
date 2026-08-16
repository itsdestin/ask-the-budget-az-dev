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
            out[str(key)] = EditionFormats(
                single_file=single or None, linked_toc=toc or None
            )
        except ValueError as err:
            if strict:
                raise
            problems.append(f"Ignoring the saved links for {key}: {err}.")
    return out, problems


def _read(
    resolved: Path, *, strict: bool
) -> tuple[dict[str, EditionFormats], list[str]]:
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
        return dict(hit[1]), list(hit[2])
    try:
        parsed, problems = _parse(
            json.loads(resolved.read_text(encoding="utf-8")), strict=strict
        )
    except (OSError, ValueError, TypeError) as err:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError — the
        # trap harness/ledger.py documents.
        if strict:
            raise
        _say_unavailable(resolved, err)
        return {}, [f"The saved link file could not be read ({err})."]
    with _lock:
        _cache[str(resolved)] = (stamp, parsed, problems)
    return dict(parsed), list(problems)


def _say_unavailable(resolved: Path, err: Exception) -> None:
    print(
        f"store.report_formats: ignoring {resolved} ({err}) — the admin's "
        "whole-report links are unavailable for this read.",
        file=sys.stderr,
    )


def load_shipped(path: Path | None = None) -> dict[str, EditionFormats]:
    return _read(path or shipped_path(), strict=True)[0]


def load_overlay(
    path: Path | None = None,
) -> tuple[dict[str, EditionFormats], list[str]]:
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
    # Per-call uuid suffix, not per-process — the chat-history lesson: two
    # writers on one file must not share a tmp name.
    tmp = resolved.with_name(f"{resolved.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, resolved)
    reset_cache()
