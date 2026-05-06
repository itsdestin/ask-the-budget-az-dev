"""Sweep extracted markdown for candidate agency + fund mentions.

This is the variance-discovery half of Phase 0 Tasks 10/11. We don't
canonicalize here — that's the user's judgment call. We just surface
every distinct string that LOOKS like an agency or fund name, with
counts and example doc/page hits, so the user has a concrete list
to canonicalize against.

Output: samples/entity-catalog-draft.yaml — a structured draft with two
sections (agencies, funds), each entry listing observed variants +
where they were seen. The user reviews, decides canonical names,
merges aliases, and confirms or rejects each candidate.

Patterns are deliberately conservative — we'd rather miss a hit than
fabricate one. Phase 1 will widen these against the full corpus.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

EXTRACTOR_OUT = Path("samples/extractor-output")
OUTPUT_YAML = Path("samples/entity-catalog-draft.yaml")

# --- Patterns -----------------------------------------------------------------

# Agency acronyms commonly used in AZ budget documents. This is the
# anchor list — we look for each as a whole-word match. Any acronym we
# don't recognize won't get caught, but spelled-out names will via the
# DEPARTMENT_RE pattern below.
KNOWN_ACRONYMS = [
    "AHCCCS", "ADOT", "DCS", "DES", "DEMA", "DJC", "DPS", "ADE", "DEQ", "ADHS",
    "DHS", "DOR", "ASLD", "ADA", "AZDA", "ADOA", "ADC", "ADCRR", "ADWR",
    "AZSF", "DEU", "AZIVMD", "DOL", "DCSE", "OSPB", "JLBC", "AGAO",
    "ASRS", "PSPRS", "ABOR", "ASU", "UA", "NAU",
]
ACRONYM_RE = re.compile(r"\b(" + "|".join(KNOWN_ACRONYMS) + r")\b")

# Spelled-out department names. "Department of X" or "Arizona Department of X".
# Greedy capture up to ~80 chars; we truncate at first stop-word post-match
# (in clean_dept_capture). This is more reliable than trying to express the
# stop conditions in regex.
DEPARTMENT_RE = re.compile(
    r"\b(?:Arizona\s+)?(?:State\s+)?Department\s+of\s+([A-Z][A-Za-z][A-Za-z &,\-]{2,80})",
    re.IGNORECASE,
)

# Words that are unambiguously NOT part of an agency name. When we see
# any of these in the captured tail of "Department of <name>", truncate
# the capture before it. Anchored as whole-word matches.
DEPT_STOP_WORDS = {
    "shall", "may", "must", "will", "submits", "submit", "submitted",
    "account", "allocate", "distribute", "use", "uses", "used",
    "report", "reports", "reported", "transfer", "transfers", "transferred",
    "present", "presents", "presented", "do", "does", "did", "done",
    "line", "lines", "budget", "budgets", "its", "has", "have", "had",
    "can", "could", "should", "would", "is", "are", "was", "were",
    "be", "been", "being", "of", "in", "for", "to", "from", "with",
    "subaccount", "subaccounts",  # these are sub-units, not the dept name
}

# Page footer convention. Loose matching to absorb OCR drift:
#  "FY 2027 Executive Budget 32 AHCCCS"
#  "FY 2027 Boseline 48 AHCCCS" (OCR: Baseline)
#  "FY 2026 Appropriotions Report 3 Arizona Department of Administration"
# Pattern: FY YYYY + 1-3 words (doc-type, OCR-tolerant) + page num + tail.
# Tail = the agency tag we want. Empty tail means a summary page (skip).
FOOTER_RE = re.compile(
    r"^FY\s+\d{4}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,2}\s+\d+\s+(.+?)\s*$",
    re.MULTILINE,
)

# Fund mentions. "<Words> Fund" with optional numeric prefix. Case-sensitive
# leading capital so we skip "fund" used as a common noun.
# AFR uses a numeric prefix ("2005-STATE AVIATION FUND") — handle separately.
FUND_NAMED_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z]*['’]?[A-Za-z]*\s+){1,5}Fund)\b"
)
FUND_AFR_RE = re.compile(
    r"\b(\d{4,5}-[A-Z][A-Z &/\-]+ FUND)\b"
)

# Generic catch-alls for sanity — text we don't want to call an "agency".
AGENCY_NEGATIVE = {
    "transportation", "environment", "education", "health", "revenue",
    "agriculture", "administration", "corrections", "child safety",
    "economic security", "public safety",
}  # these would only match as the *capture group* of DEPARTMENT_RE; we keep them

# Funds where the leading word is a stop-word — false-positive prone.
FUND_NEGATIVE_PREFIXES = {
    "Trust", "the", "a", "this", "that",
}


# --- Sweep --------------------------------------------------------------------

def clean_dept_capture(raw: str) -> str | None:
    """Truncate a 'Department of X' capture at first stop word.

    "administration shall allocate adjustments" -> "administration"
    "child safety budget do not count toward"   -> "child safety"
    "corrections"                                -> "corrections"
    Returns None if the result would be empty.
    """
    raw = raw.strip().rstrip(".,;:")
    tokens = raw.split()
    kept: list[str] = []
    for t in tokens:
        # Strip trailing punctuation from a single token before stop-word check.
        bare = t.rstrip(".,;:'\"-").lower()
        if bare in DEPT_STOP_WORDS:
            break
        kept.append(t)
        if len(kept) >= 6:  # safety bound — proper agency names are short
            break
    if not kept:
        return None
    return " ".join(kept).rstrip("-,&")


def normalize_for_dedup(name: str) -> str:
    """Case-fold + collapse whitespace so 'Department of CORRECTIONS' and
    'Department of corrections' merge into one entry."""
    return " ".join(name.lower().split())


def sweep_file(text: str, source: str) -> tuple[dict, dict]:
    """Return (agency_hits, fund_hits) for one file's text.

    Each is normalized-name -> dict with {display, occurrences set}.
    """
    agency_hits: dict[str, dict] = defaultdict(lambda: {"display": "", "hits": set()})
    fund_hits: dict[str, dict] = defaultdict(lambda: {"display": "", "hits": set()})

    def record(d: dict, display: str, source: str, pos: int) -> None:
        key = normalize_for_dedup(display)
        if not d[key]["display"]:
            d[key]["display"] = display
        d[key]["hits"].add((source, text.count("\n", 0, pos) + 1))

    # Footer: highest confidence agency tag.
    for m in FOOTER_RE.finditer(text):
        tag = m.group(1).strip()
        # Skip if the tail is empty or just whitespace (summary page).
        # Also skip if it's purely numeric or short codes (page sub-numbers like "BH-24").
        if not tag or len(tag) < 3 or re.fullmatch(r"[A-Z]{1,3}-?\d+", tag):
            continue
        record(agency_hits, f"[FOOTER] {tag}", source, m.start())

    # Acronyms.
    for m in ACRONYM_RE.finditer(text):
        record(agency_hits, m.group(1), source, m.start())

    # Department names — clean the capture before recording.
    for m in DEPARTMENT_RE.finditer(text):
        cleaned = clean_dept_capture(m.group(1))
        if not cleaned:
            continue
        # Reconstruct prefix (Arizona/State + Department of <cleaned>)
        prefix_text = m.group(0)[: m.start(1) - m.start()].strip()
        full = f"{prefix_text} {cleaned}".strip()
        record(agency_hits, full, source, m.start())

    # Funds: named.
    for m in FUND_NAMED_RE.finditer(text):
        name = m.group(1).strip()
        first = name.split()[0]
        if first in FUND_NEGATIVE_PREFIXES:
            continue
        if name.lower().startswith("the "):
            continue
        record(fund_hits, name, source, m.start())

    # Funds: AFR numeric-prefix style.
    for m in FUND_AFR_RE.finditer(text):
        name = m.group(1).strip()
        record(fund_hits, name, source, m.start())

    return agency_hits, fund_hits


def merge_dicts(target: dict, src: dict) -> None:
    for k, v in src.items():
        if not target[k]["display"]:
            target[k]["display"] = v["display"]
        target[k]["hits"].update(v["hits"])


def collect_md_files() -> list[Path]:
    files: list[Path] = []
    files.extend(sorted(EXTRACTOR_OUT.glob("opendataloader/*/*.md")))
    files.extend(sorted(EXTRACTOR_OUT.glob("mineru/*/*.md")))
    files.extend(sorted(EXTRACTOR_OUT.glob("docx/*/*.md")))
    return files


def doc_id_of(path: Path) -> str:
    # extractor-output/<extractor>/<doc_id>/<file>.md
    return path.parent.name


def main(argv: list[str]) -> int:
    files = collect_md_files()
    if not files:
        print("no .md files under samples/extractor-output", file=sys.stderr)
        return 2

    agencies: dict[str, dict] = defaultdict(lambda: {"display": "", "hits": set()})
    funds: dict[str, dict] = defaultdict(lambda: {"display": "", "hits": set()})

    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        a, fu = sweep_file(text, f"{doc_id_of(f)}/{f.name}")
        merge_dicts(agencies, a)
        merge_dicts(funds, fu)

    # Cluster entries that share the same first 3 normalized words. The bill
    # DOCX produces a lot of "department of X <legalese>" variants of the same
    # agency (e.g. 'department of public safety joint', 'department of public
    # safety positions'). All of those collapse to 'department of public safety'.
    # Variants are preserved as 'aliases' on the parent entry so the user can
    # see what was merged.
    def cluster_key(name: str) -> str:
        norm = normalize_for_dedup(name)
        # Strip the [FOOTER] tag for clustering — "[FOOTER] AHCCCS" should
        # cluster with "AHCCCS".
        if norm.startswith("[footer] "):
            norm = norm[len("[footer] "):]
        words = norm.split()
        # For "department of X" entries, cluster by the 4-word prefix.
        # 4 words is enough to distinguish "department of child safety" from
        # "department of child support" without splitting "department of public
        # safety" by trailing legalese. Single-token entries (acronyms) stay as-is.
        if len(words) >= 4 and (words[0] == "department" or words[1] == "department"):
            offset = 0 if words[0] == "department" else 1
            return " ".join(words[offset:offset + 4])
        return " ".join(words[:3])

    def cluster_and_format(d: dict[str, dict]) -> list[dict]:
        clusters: dict[str, dict] = {}
        for _key, entry in d.items():
            ck = cluster_key(entry["display"])
            c = clusters.setdefault(ck, {
                "displays": [],
                "hits": set(),
                "saw_footer": False,
            })
            c["displays"].append(entry["display"])
            c["hits"].update(entry["hits"])
            if entry["display"].startswith("[FOOTER]"):
                c["saw_footer"] = True

        rows: list[dict] = []
        for ck, c in sorted(clusters.items(),
                            key=lambda kv: (-len(kv[1]["hits"]), kv[0])):
            hits = c["hits"]
            sources = sorted({src for src, _ in hits})
            # Pick the canonical display: prefer footer (high-confidence), then
            # the shortest one (longer ones are usually legalese tails).
            displays_sorted = sorted(set(c["displays"]),
                                     key=lambda s: (not s.startswith("[FOOTER]"),
                                                    len(s)))
            primary = displays_sorted[0].replace("[FOOTER] ", "")
            aliases = [d for d in displays_sorted if d != displays_sorted[0]]
            rows.append({
                "candidate": primary,
                "occurrences": len(hits),
                "seen_in_docs": sorted({s.split("/")[0] for s in sources}),
                "example_files": sources[:3],
                "aliases_observed": aliases[:5],  # cap to keep output readable
                "footer_confirmed": c["saw_footer"],
            })
        return rows

    def to_entries(d: dict[str, dict]) -> list[dict]:
        return cluster_and_format(d)

    out = {
        "_meta": {
            "generated_from": "samples/extractor-output (Phase 0 sample only — 23 PDF pages + 1 DOCX)",
            "patterns": {
                "agency_acronyms": KNOWN_ACRONYMS,
                "agency_spelled_out": "Department of <name>",
                "agency_footer": "FY YYYY <DocType> <Page> <AgencyTag>",
                "fund_named": "<words> Fund",
                "fund_afr": "<NNNN-NAME FUND>",
            },
            "instructions_for_user": (
                "This is a candidate list, NOT canonical. For each candidate: "
                "decide canonical name, group aliases, mark false-positives, "
                "or defer. Phase 1 will run this against the full corpus."
            ),
        },
        "agencies": to_entries(agencies),
        "funds": to_entries(funds),
    }

    OUTPUT_YAML.write_text(
        yaml.dump(out, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )

    print(f"wrote {OUTPUT_YAML}")
    print(f"  agencies: {len(out['agencies'])} candidates")
    print(f"  funds:    {len(out['funds'])} candidates")
    print(f"  files swept: {len(files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
