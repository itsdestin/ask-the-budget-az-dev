"""Build the canonical agency catalog from publisher-provided data.

Sources (all under samples/raw-pdfs/):

1. JLBC agency-index PDFs — `jlbc-{baseline,approps}-fy{YYYY}-agency-index.pdf`.
   Each is a 1-page PDF with hyperlinks; each link rect contains the agency
   name (TOC dot-leader + page-in-doc), each link target is the per-agency
   PDF (e.g. axs.pdf for AHCCCS). Currently spans:
     - Baselines:  FY 2023 — FY 2027 (5 years)
     - Approps:    FY 2015 — FY 2026 (12 years)

2. Governor's FY 2027 State Agency Detail PDF outline tree
   (samples/raw-pdfs/governors-state-agency-detail-fy27.pdf) — 102 level-2
   agency entries under "Agency Operating Budget Detail".

The JLBC slug (URL filename without `.pdf`) is the stable canonical_id —
it has been consistent for years (axs always = AHCCCS, dot always = ADOT)
and survives agency renames within the JLBC. We key the catalog on it.

For each agency we track:
  - canonical_name       (the most recent JLBC name, with full variant list)
  - canonical_id         (= "agency:<slug>")
  - aliases.jlbc_names   (every distinct name JLBC used across years)
  - aliases.gov_name     (the Governor's outline name, if matched)
  - source_indexes       (which year/doctype indexes the agency appeared in)
  - per_index_pages      (page-in-doc for each index it appeared in)
  - first_seen_index     / last_seen_index — useful for spotting
                         create/delete/rename events

Then we cross-reference against the Phase-0 sweep candidates and surface
matches + unmatched. Improved matcher v2:
  - Hardcoded AZ-acronym → slug shortcut (DPS→dps, AHCCCS→axs, …).
  - Token-jaccard over normalized names (as before, threshold 0.4).
  - Substring fallback: candidate ⊂ entry or entry ⊂ candidate.
  - Edit-distance ≤ 2 fallback for short candidates (catches OCR drift
    like "Public Safetv" vs "Public Safety").

Output: samples/entity-catalog.yaml
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF
import yaml

RAW_PDFS = Path("samples/raw-pdfs")
GOV_DETAIL = Path("samples/raw-pdfs/governors-state-agency-detail-fy27.pdf")
DRAFT = Path("samples/entity-catalog-draft.yaml")
OUT = Path("samples/entity-catalog.yaml")

# JLBC index file pattern: jlbc-{kind}-fy{YYYY}-agency-index.pdf
INDEX_FILE_RE = re.compile(
    r"^jlbc-(baseline|approps)-fy(\d{4})-agency-index\.pdf$"
)

# --- Common patterns ---------------------------------------------------------

DOTS_TAIL_RE = re.compile(r"\s*\.{2,}\s*\d+\s*$")


# --- Source: JLBC agency-index PDFs -----------------------------------------

def parse_one_index(pdf_path: Path) -> tuple[str, int, list[dict]]:
    """Parse a single agency-index PDF.

    Returns (kind, fy, entries) where entries is
    [{name, slug, page_in_doc, url}].
    """
    m = INDEX_FILE_RE.match(pdf_path.name)
    if not m:
        return "?", 0, []
    kind, fy_str = m.group(1), m.group(2)
    fy = int(fy_str)

    doc = fitz.open(pdf_path)
    try:
        entries: list[dict] = []
        for pno, page in enumerate(doc):
            for link in page.get_links():
                uri = link.get("uri")
                rect = link.get("from")
                if not (uri and rect and uri.endswith(".pdf")):
                    continue
                raw = page.get_text(clip=rect).strip().replace("\n", " ")
                # Pull page number from dot-leader before stripping.
                page_in_doc = None
                pm = re.search(r"\.{2,}\s*(\d+)\s*$", raw)
                if pm:
                    page_in_doc = int(pm.group(1))
                cleaned = DOTS_TAIL_RE.sub("", raw).strip()
                # Trim stray leading char from previous-line bleed-through.
                cleaned = re.sub(r"^[a-z0-9],?\s+", "", cleaned)
                if not cleaned or len(cleaned) < 3:
                    continue
                slug = uri.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                # Only keep links pointing into a JLBC-hosted PDF.
                # JLBC migrated hosts at some point: older approps reports
                # (FY15-FY22 verified) link to azleg.gov/jlbc/<YY>AR/<slug>.pdf,
                # newer baselines + approps link to azjlbc.gov/<YY>{baseline,ar}/.
                # Both forms are legitimate; bare external links aren't.
                if not ("azjlbc.gov" in uri or
                        ("azleg.gov" in uri and "/jlbc/" in uri)):
                    continue
                # Filter section/page-content URLs that aren't agencies.
                # Agency slugs are 2-15 chars, lowercase, alpha+hyphen only.
                # Bogus examples: "390" (page number), "capitaloutlay"
                # (section), "s7" (summary section).
                if not re.match(r"^[a-z]+(-[a-z]+)*$", slug):
                    continue
                if slug in {"capitaloutlay", "agencyindex", "crr",
                            "tobacco", "csbg"}:
                    # Whole-document/section PDFs that get linked from the
                    # index but are not per-agency content.
                    continue
                if slug.startswith("s") and len(slug) <= 3 and slug[1:].isdigit():
                    # "s7", "s15" — summary-section links.
                    continue
                entries.append({
                    "name": cleaned,
                    "slug": slug,
                    "page_in_doc": page_in_doc,
                    "url": uri,
                })
        return kind, fy, entries
    finally:
        doc.close()


# --- Source: Governor's outline tree ----------------------------------------

GOV_AGENCY_PARENT = "Agency Operating Budget Detail"


def parse_gov_outline(pdf_path: Path) -> list[dict]:
    if not pdf_path.exists():
        return []
    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
        entries: list[dict] = []
        in_agencies = False
        for level, title, pno in toc:
            if level == 1:
                in_agencies = (title.strip() == GOV_AGENCY_PARENT)
                continue
            if in_agencies and level == 2:
                entries.append({"name": title.strip(), "page": pno})
        return entries
    finally:
        doc.close()


# --- Normalize + match -------------------------------------------------------

def normalize(name: str) -> str:
    """Aggressive normalize for matching: lowercase, drop org-type words
    + state prefix + punctuation. Goal is "agency identity," not exact
    string."""
    s = name.lower()
    # Collapse whitespace FIRST so multi-space variants ("Department  of")
    # match the single-space drop-phrases below.
    s = re.sub(r"\s+", " ", s).strip()
    drop_phrases = [
        "arizona state ", "arizona ", "state ", " department of",
        "department of ", " office of", "office of ", " board of",
        "board of ", " commission on the", "commission on the ",
        ", the", " ,", ",",
    ]
    for d in drop_phrases:
        s = s.replace(d, " ")
    # Drop legalese-tail stop words anywhere.
    # IMPORTANT: do NOT strip "administration" or "administrative" — those
    # are load-bearing identity tokens for the Department of Administration
    # (slug doa) and Office of Administrative Hearings (slug oah).
    s = re.sub(r"\b(shall|may|must|will|submits?|submitted|account|allocate|"
               r"distribute|uses?|used|reports?|reported|transfers?|"
               r"transferred|presents?|presented|does|did|done|lines?|"
               r"budgets?|its|has|have|had|can|could|should|would|is|are|"
               r"was|were|be|been|being|of|in|for|to|from|with|"
               r"subaccounts?|pursuant|enter|laws|on|or|before|losses|"
               r"premiums|reporting|by|require|division|positions|joint|"
               r"as|annual|progress|incurs|legal|expenses|the|and|"
               r"agreements|services|central|bureau|which)\b", " ", s)
    s = re.sub(r"[^\w\s\-']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Acronyms whose normalized form doesn't share tokens with their canonical
# JLBC name (so token-jaccard match misses them). The slug is JLBC's stable
# URL filename — verified against the FY 2027 baseline index.
ACRONYM_TO_SLUG: dict[str, str | None] = {
    # Slugs verified against the JLBC FY27 baseline index (samples).
    "AHCCCS": "axs",
    "ADOT":   "dot",
    "ADHS":   "dhs",
    "DHS":    "dhs",
    "DCS":    "dcs",
    "DES":    "des",
    "ADE":    "ade",
    "ADOA":   "doa",
    "DJC":    "djc",
    "DPS":    "dps",
    "DOR":    "dor",
    "DEMA":   "ema",     # Emergency and Military Affairs
    "DEQ":    "deq",
    "ADC":    "adc",     # Corrections, State Department of
    "ADCRR":  "adc",     # post-rename name still maps to the same dept
    "ADWR":   "wat",
    "ASLD":   "lan",     # Land Department, State
    "NAU":    "uninau",
    "ASU":    "uniasu",
    "UA":     "uniumain",  # University of Arizona main campus (Health Sciences = uniuhsc)
    "ABOR":   "unibor",
    "ASRS":   "ret",
    "PSPRS":  "psp",
    "DEU":    None,
    "AZIVMD": None,
    "DOL":    None,
    "DCSE":   None,
    # Publishers — not agencies in the catalog
    "OSPB":   None,
    "JLBC":   None,
    "AGAO":   None,
    "ADA":    None,
}


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Bounded Levenshtein. Returns cap+1 if exceeds cap (early exit)."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        min_in_row = curr[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            if curr[j] < min_in_row:
                min_in_row = curr[j]
        if min_in_row > cap:
            return cap + 1
        prev = curr
    return prev[-1]


def match_candidate(cand: str, catalog: list[dict]) -> tuple[str | None, str]:
    """Return (canonical_id_or_None, reason). reason is a short tag
    describing how the match was made — useful in audit output."""
    raw = cand.strip().replace("[FOOTER] ", "")

    # Pass 1: hardcoded acronym shortcut for short ALL CAPS candidates.
    if 2 <= len(raw) <= 6 and raw == raw.upper() and raw.isalpha():
        if raw in ACRONYM_TO_SLUG:
            slug = ACRONYM_TO_SLUG[raw]
            if slug is None:
                return None, "non-agency acronym (publisher / Act / ambiguous)"
            for entry in catalog:
                if entry["slug"] == slug:
                    return entry["canonical_id"], f"acronym→slug ({raw}→{slug})"

    cand_norm = normalize(raw)
    cand_tokens = set(cand_norm.split())
    cand_signal = {t for t in cand_tokens if len(t) >= 3}

    # Pass 2: jaccard on normalized signal tokens.
    if cand_signal:
        best: tuple[float, str] | None = None
        for entry in catalog:
            ent_norm = normalize(entry["canonical_name"])
            ent_tokens = set(ent_norm.split())
            ent_signal = {t for t in ent_tokens if len(t) >= 3}
            if not ent_signal:
                continue
            overlap = cand_signal & ent_signal
            if not overlap:
                continue
            score = len(overlap) / len(cand_signal | ent_signal)
            if best is None or score > best[0]:
                best = (score, entry["canonical_id"])
        if best and best[0] >= 0.4:
            return best[1], f"jaccard {best[0]:.2f}"

    # Pass 3: substring fallback. Useful when the candidate has a
    # legalese tail or extra qualifier that survives normalization.
    if cand_norm:
        for entry in catalog:
            ent_norm = normalize(entry["canonical_name"])
            if not ent_norm:
                continue
            if ent_norm in cand_norm and len(ent_norm) >= 6:
                return entry["canonical_id"], f"substring (entry⊂cand)"
            if cand_norm in ent_norm and len(cand_norm) >= 6:
                return entry["canonical_id"], f"substring (cand⊂entry)"

    # Pass 4: edit-distance for short candidates (OCR drift).
    if 4 <= len(cand_norm) <= 30:
        for entry in catalog:
            ent_norm = normalize(entry["canonical_name"])
            if not (4 <= len(ent_norm) <= 35):
                continue
            d = edit_distance(cand_norm, ent_norm, cap=2)
            if d <= 2:
                return entry["canonical_id"], f"edit-distance {d}"

    return None, "unmatched"


# --- Catalog assembly --------------------------------------------------------

def gather_indexes() -> dict[str, dict]:
    """Parse every JLBC agency-index PDF in samples/raw-pdfs/. Group entries
    by slug. Each slug becomes one canonical agency, with cross-year metadata."""
    by_slug: dict[str, dict] = {}

    index_files = sorted(p for p in RAW_PDFS.glob("*-agency-index.pdf")
                         if INDEX_FILE_RE.match(p.name))
    if not index_files:
        return {}

    for path in index_files:
        kind, fy, entries = parse_one_index(path)
        index_tag = f"{kind}-fy{fy}"
        for e in entries:
            slug = e["slug"]
            if slug not in by_slug:
                by_slug[slug] = {
                    "slug": slug,
                    "canonical_id": f"agency:{slug}",
                    "names_observed": defaultdict(list),  # name -> [index_tags]
                    "indexes": {},  # index_tag -> {page, url}
                    "first_seen": index_tag,
                    "last_seen": index_tag,
                }
            agency = by_slug[slug]
            agency["names_observed"][e["name"]].append(index_tag)
            agency["indexes"][index_tag] = {
                "page": e["page_in_doc"],
                "url": e["url"],
            }
            # Update first/last by chronological order. Approps comes after
            # baseline of same FY; baselines lead approps by ~1 fiscal year.
            order = lambda tag: int(tag.split("fy")[1]) * 10 + (
                0 if tag.startswith("baseline") else 1)
            if order(index_tag) < order(agency["first_seen"]):
                agency["first_seen"] = index_tag
            if order(index_tag) > order(agency["last_seen"]):
                agency["last_seen"] = index_tag
    return by_slug


def pick_canonical_name(names_observed: dict[str, list[str]]) -> str:
    """Choose a canonical display name from the observed name set.
    Preference: most recent (last_seen index), then most frequent."""
    if not names_observed:
        return ""
    # Find which name was used in the latest year.
    by_latest_year: dict[str, int] = {}
    for name, tags in names_observed.items():
        latest = max(int(t.split("fy")[1]) * 10 +
                     (0 if t.startswith("baseline") else 1) for t in tags)
        by_latest_year[name] = latest
    # Top by latest year, tie-break by hit count.
    return max(names_observed, key=lambda n: (by_latest_year[n], len(names_observed[n])))


def merge_gov_outline(by_slug: dict[str, dict], gov_entries: list[dict]) -> list[dict]:
    """Attach Gov outline names to slug entries by fuzzy match. Entries in
    Gov but absent from JLBC become non-slug catalog entries (rare)."""
    # Build a slug-keyed catalog list first.
    catalog = []
    for slug, agency in sorted(by_slug.items()):
        canonical_name = pick_canonical_name(agency["names_observed"])
        catalog.append({
            "canonical_name": canonical_name,
            "canonical_id": agency["canonical_id"],
            "slug": agency["slug"],
            "names_observed_jlbc": dict(agency["names_observed"]),
            "indexes": agency["indexes"],
            "first_seen": agency["first_seen"],
            "last_seen": agency["last_seen"],
            "name_gov_alias": None,
            "page_in_gov_fy27": None,
        })

    # Match each Gov entry against the catalog using jaccard.
    matched_gov = set()
    for gov in gov_entries:
        cand_norm = normalize(gov["name"])
        cand_signal = {t for t in cand_norm.split() if len(t) >= 3}
        best: tuple[float, dict] | None = None
        for entry in catalog:
            ent_norm = normalize(entry["canonical_name"])
            ent_signal = {t for t in ent_norm.split() if len(t) >= 3}
            if not (cand_signal and ent_signal):
                continue
            overlap = cand_signal & ent_signal
            if not overlap:
                continue
            score = len(overlap) / len(cand_signal | ent_signal)
            if best is None or score > best[0]:
                best = (score, entry)
        if best and best[0] >= 0.5:
            best[1]["name_gov_alias"] = gov["name"]
            best[1]["page_in_gov_fy27"] = gov["page"]
            matched_gov.add(gov["name"])

    # Gov-only entries (not matched to any slug) become their own catalog rows.
    for gov in gov_entries:
        if gov["name"] in matched_gov:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", gov["name"].lower()).strip("-")
        catalog.append({
            "canonical_name": gov["name"],
            "canonical_id": f"agency:gov:{slug}",
            "slug": None,
            "names_observed_jlbc": {},
            "indexes": {},
            "first_seen": None,
            "last_seen": None,
            "name_gov_alias": gov["name"],
            "page_in_gov_fy27": gov["page"],
        })

    catalog.sort(key=lambda e: e["canonical_name"].lower())
    return catalog


# --- Main --------------------------------------------------------------------

def main(argv: list[str]) -> int:
    by_slug = gather_indexes()
    if not by_slug:
        print("no JLBC agency-index PDFs found", file=sys.stderr)
        return 2

    gov_entries = parse_gov_outline(GOV_DETAIL)
    catalog = merge_gov_outline(by_slug, gov_entries)

    # Match the sweep candidates against the catalog.
    candidates: list[str] = []
    if DRAFT.exists():
        data = yaml.safe_load(DRAFT.read_text(encoding="utf-8"))
        candidates = [a["candidate"] for a in data.get("agencies", [])]

    matches: list[tuple[str, str | None, str]] = []  # (cand, cid, reason)
    for cand in candidates:
        cid, reason = match_candidate(cand, catalog)
        matches.append((cand, cid, reason))

    rev_match: dict[str, list[str]] = defaultdict(list)
    for cand, cid, reason in matches:
        if cid:
            rev_match[cid].append(cand)
    for entry in catalog:
        entry["observed_in_sample"] = rev_match.get(entry["canonical_id"], [])

    matched = [m for m in matches if m[1]]
    unmatched = [m for m in matches if not m[1]]

    out = {
        "_meta": {
            "instructions": (
                "Canonical names + slugs come from publisher data (JLBC "
                "agency-index PDFs across years + Gov outline). "
                "'observed_in_sample' shows sweep-candidate matches. "
                "Unmatched candidates are listed at end with reason — "
                "review them; most are false-positives or ambiguous."
            ),
            "stats": {
                "jlbc_indexes_processed": sum(1 for p in RAW_PDFS.glob("*-agency-index.pdf")
                                              if INDEX_FILE_RE.match(p.name)),
                "unique_jlbc_slugs": len(by_slug),
                "gov_entries": len(gov_entries),
                "merged_unique": len(catalog),
                "with_gov_alias": sum(1 for e in catalog if e["name_gov_alias"]),
                "draft_candidates_total": len(candidates),
                "draft_candidates_matched": len(matched),
                "draft_candidates_unmatched": len(unmatched),
            },
        },
        "agencies": catalog,
        "unmatched_sweep_candidates": [
            {"candidate": c, "reason": r} for c, _, r in unmatched
        ],
    }

    OUT.write_text(yaml.dump(out, sort_keys=False, allow_unicode=True, width=120),
                   encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  JLBC indexes processed: {out['_meta']['stats']['jlbc_indexes_processed']}")
    print(f"  unique JLBC slugs: {len(by_slug)}")
    print(f"  Gov outline entries: {len(gov_entries)}")
    print(f"  merged unique agencies: {len(catalog)}")
    print(f"  with both JLBC + Gov alias: {out['_meta']['stats']['with_gov_alias']}")
    print(f"  candidates matched: {len(matched)}/{len(candidates)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
