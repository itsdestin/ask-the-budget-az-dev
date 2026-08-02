"""Draft candidate acronym aliases for the 157-agency canonical catalog.

WHY THIS EXISTS. `chunking/agency_catalog.py` gives every agency its JLBC slug
as an alias for free (`adc`, `axs`, `dot`), because the publisher's own URLs
already abbreviate it that way. What the catalog does NOT have is the shorthand
an analyst says out loud — "DOC", "DEMA", "ADOA". 103 of the 157 agencies carry
nothing but their canonical name, so a question phrased in shorthand has no way
to reach them.

WHY THIS ONLY DRAFTS. An approved alias may become a HARD retrieval filter. A
missing alias merely fails to help; a WRONG alias sends a question confidently
to the wrong agency, which is far harder to notice than getting no answer. So
this script proposes and a human disposes: it writes a review checklist to
stdout and touches nothing else. Applying the approved list to
`samples/entity-catalog.yaml` is a separate, human-gated step.

Usage:

    .venv/bin/python scripts/draft_agency_aliases.py \\
        > docs/superpowers/investigations/2026-08-02-agency-alias-review.md
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Run as `python scripts/draft_agency_aliases.py` from the repo root — the repo
# root is not on sys.path in that case, so `chunking` would not import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chunking.agency_catalog import AgencyEntry, load_agency_catalog  # noqa: E402

# The date is a CONSTANT, not today(). The generated document must be
# byte-identical between runs so a reviewer can diff a fresh draft against the
# one they already approved; a moving date would make every re-run look changed.
DRAFT_DATE = "2026-08-02"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

_CONFIDENCE_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

# Words that never contribute an initial. "and" is dropped even though it sits
# mid-name, because the one alias a human actually chose for this catalog —
# DEMA, from "Department of Emergency and Military Affairs" — drops it.
CORE_STOPWORDS = frozenset(
    {"and", "the", "for", "on", "in", "at", "to", "a", "an", "&"}
)

# Dropped by default but kept in one variant, because "Arizona State
# University" is ASU and dropping both leaves a single letter.
GEO_STOPWORDS = frozenset({"arizona", "state"})

# Acronyms shorter than this are too weak to be a filter; longer than the max
# nobody types as shorthand.
MIN_ALIAS_LEN = 2
MAX_ALIAS_LEN = 5

MAX_PROPOSALS_PER_AGENCY = 3

# Aliases that are also ordinary English words. Under a HARD filter these are
# actively dangerous: "the arts budget" or "tax collections" would pin the
# query to one agency. They are not banned outright — the reviewer may still
# want them — but an approved one MUST also go into `AMBIGUOUS_ALIASES` in
# `retrieval/query_agency.py` so it only ever boosts, never filters.
ORDINARY_ENGLISH_WORDS = frozenset(
    {
        # The list the task brief named explicitly.
        "doc", "ar", "afr", "des", "pp", "ada", "ace", "air", "art", "aid",
        "was", "has", "gas", "sea", "law", "tax", "act", "age", "arm", "ash",
        # Short words that fall out of this catalog's own name shapes.
        "ab", "ad", "ah", "am", "an", "as", "at", "ate", "aw", "ax", "be",
        "bad", "bag", "ban", "bar", "bat", "bed", "bee", "bet", "bid", "big",
        "bit", "boa", "bob", "bog", "boo", "bow", "box", "boy", "bra", "bud",
        "bug", "bun", "bus", "but", "buy", "cab", "cap", "car", "cat", "cop", "cot",
        "cow", "cry", "cub", "cue", "cup", "cut", "dab", "dam", "day", "den",
        "dew", "did", "die", "dig", "dim", "dip", "doe", "dog", "don", "dot",
        "dry", "dub", "due", "dug", "duo", "dye", "ear", "eat", "ebb", "eel",
        "egg", "ego", "elf", "elk", "elm", "end", "eve", "eye", "fan", "far",
        "fat", "fax", "fed", "fee", "few", "fig", "fin", "fir", "fit", "fix",
        "flu", "fly", "foe", "fog", "for", "fox", "fry", "fun", "fur", "gag",
        "gap", "gem", "get", "gig", "gin", "god", "got", "gum", "gun", "gut",
        "guy", "gym", "had", "hat", "hay", "hem", "hen", "her", "hid", "him",
        "hip", "his", "hit", "hoe", "hog", "hop", "hot", "how", "hub", "hue",
        "hug", "hum", "hut", "ice", "icy", "ill", "imp", "ink", "inn", "ion",
        "ire", "irk", "its", "ivy", "jab", "jam", "jar", "jaw", "jet", "job",
        "jog", "jot", "joy", "jug", "key", "kid", "kin", "kit", "lab", "lad",
        "lag", "lap", "led", "leg", "let", "lid", "lie", "lip", "lit", "log",
        "lot", "low", "mad", "man", "map", "mat", "may", "men", "met", "mix",
        "mob", "mop", "mud", "mug", "nab", "nag", "nap", "net", "new", "nod",
        "nor", "not", "now", "nut", "oak", "oar", "oat", "odd", "ode", "off",
        "oil", "old", "one", "opt", "orb", "ore", "our", "out", "owe", "owl",
        "own", "pad", "pan", "par", "pat", "paw", "pay", "pea", "peg", "pen",
        "per", "pet", "pie", "pig", "pin", "pit", "ply", "pod", "pot", "pro",
        "pub", "pun", "pup", "put", "rag", "ram", "ran", "rap", "rat", "raw",
        "ray", "red", "rib", "rid", "rig", "rim", "rip", "rob", "rod", "rot",
        "row", "rub", "rug", "rum", "run", "rut", "sad", "sag", "sap", "sat",
        "saw", "say", "set", "sew", "she", "shy", "sin", "sip", "sir", "sit",
        "six", "ski", "sky", "sly", "sob", "son", "sow", "soy", "spa", "spy",
        "sty", "sub", "sue", "sum", "sun", "tab", "tag", "tan", "tap", "tar",
        "tea", "ten", "the", "tie", "tin", "tip", "toe", "ton", "too", "top",
        "tow", "toy", "try", "tub", "tug", "two", "urn", "use", "van", "vat",
        "vet", "via", "vie", "vow", "wag", "war", "wax", "way", "web", "wed",
        "wet", "who", "why", "wig", "win", "wit", "woe", "wok", "won", "woo",
        "wry", "yak", "yam", "yap", "yes", "yet", "you", "zip", "zoo",
        # Four-letter words this catalog can actually produce.
        "aces", "acre", "aide", "aids", "arts", "bail", "bald", "base",
        "cost", "dare", "dart", "dear", "dose", "east", "gate", "hand",
        "head", "heat", "hope", "idea", "lace", "land", "lead", "lose",
        "mode", "moth", "note", "pace", "pact", "page", "part", "past",
        "path", "peak", "pest", "plan", "pole", "post", "rate", "read",
        "real", "rest", "ride", "road", "rose", "safe", "sale", "salt",
        "sand", "seat", "site", "star", "task", "team", "test", "tide",
        "tile", "tone", "tool", "trap", "wave", "west", "wide", "wise",
    }
)

# Nouns that mark a trailing comma-segment as an inverted qualifier rather than
# a place name — "Corrections, State Department of" is inverted,
# "Historical Society of Arizona, Prescott" is not.
_QUALIFIER_NOUNS = frozenset(
    {
        "department", "board", "office", "commission", "authority", "agency",
        "council", "committee", "division", "schools", "school", "system",
        "court", "bureau", "institute", "society", "fund", "examiners",
        "bd.", "dept.",
    }
)

_QUALIFIER_TAILS = frozenset({"of", "for", "on", "the", "in", "of.", "on."})

# Derivation kinds — carried through to the review document so the reviewer can
# see WHERE an acronym came from, not just what it is.
PRIMARY = "primary"
ARIZONA_PREFIXED = "arizona-prefixed"
KEEP_GEO = "keeps Arizona/State"
FIRST_SEGMENT = "parent-organisation segment"


@dataclass(frozen=True)
class Candidate:
    """One acronym proposal before collision resolution.

    `ceiling` is the best confidence this derivation may ever be awarded.
    Some shapes are plausible but structurally weaker — an acronym read
    straight across the dash of "Attorney General - Department of Law" gives
    AGDL, which is mechanically correct and something nobody has ever said.
    """

    alias: str
    kind: str
    words: tuple[str, ...]
    source_name: str
    ceiling: str = HIGH
    ceiling_reason: str | None = None


@dataclass(frozen=True)
class Proposal:
    """One surviving acronym, as the reviewer sees it."""

    alias: str
    kind: str
    confidence: str
    ordinary_word: bool
    derivation: str
    warnings: tuple[str, ...] = ()


@dataclass
class AgencyDraft:
    """Everything the review document says about one agency."""

    canonical_id: str
    canonical_name: str
    slug: str | None
    existing_aliases: list[str]
    proposals: list[Proposal] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)
    shadow_note: str | None = None

    @property
    def best_confidence(self) -> str:
        if not self.proposals:
            return LOW
        return min((p.confidence for p in self.proposals), key=_CONFIDENCE_ORDER.get)


# --------------------------------------------------------------------------
# Name handling
# --------------------------------------------------------------------------


def name_is_contaminated(name: str) -> bool:
    """True when the canonical name carries PDF table-of-contents wreckage.

    A handful of catalog names were harvested straight out of an index page and
    still contain the page number and dot leaders — e.g. "Nursing Care
    Institution Administrators and Assisted Living   338  Facility Managers,
    Board of Examiners of ....". An acronym read off that text is garbage, so
    the generator declines rather than inventing one.
    """
    return bool(re.search(r"\d", name)) or "..." in name


def uninvert(name: str) -> str:
    """Put an inverted index name back into reading order.

    JLBC prints agency names inverted so they alphabetise by subject —
    "Corrections, State Department of". Reading initials off that literally
    gives "CSD"; reading them off "State Department of Corrections" gives the
    real "DOC". Splits on the LAST comma, because some names have two
    ("Fire, Building and Life Safety, Department of").
    """
    cleaned = name.strip().rstrip(".").strip()
    if "," not in cleaned:
        return cleaned
    head, _, tail = cleaned.rpartition(",")
    tail_words = tail.strip().lower().rstrip(".").split()
    if not tail_words:
        return cleaned
    looks_like_qualifier = (
        tail_words[-1] in _QUALIFIER_TAILS
        or bool(set(tail_words) & _QUALIFIER_NOUNS)
    )
    # A trailing place name ("…, Prescott") is part of the name, not an
    # inversion — flipping it would produce a worse acronym, not a better one.
    if not looks_like_qualifier or len(tail_words) > 6:
        return cleaned
    return f"{tail.strip()} {head.strip()}".strip()


def _tokenize(name: str) -> list[str]:
    """Words of a name, with punctuation and segment dashes removed.

    The possessive is stripped BEFORE splitting: without it "Governor's Office
    of Highway Safety" tokenizes to Governor / s / Office / … and produces
    "GSOHS" instead of the real "GOHS" — a lone possessive 's' silently
    corrupting every Governor's-office acronym in the catalog.
    """
    without_possessive = re.sub(r"['’]s\b", "", name)
    return [w for w in re.split(r"[^A-Za-z]+", without_possessive) if w]


def _initials(words: list[str], *, keep_geo: bool, keep_of: bool) -> tuple[str, tuple[str, ...]]:
    """Build an acronym from the words that count, returning it and them."""
    used: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered == "of":
            if keep_of:
                used.append(word)
            continue
        if lowered in CORE_STOPWORDS:
            continue
        if lowered in GEO_STOPWORDS and not keep_geo:
            continue
        used.append(word)
    return "".join(w[0].upper() for w in used), tuple(used)


def candidate_acronyms(entry: AgencyEntry) -> list[Candidate]:
    """Every acronym worth offering for one agency, in preference order.

    Deliberately narrow. Four mechanical variants exist (Arizona in or out,
    "of" in or out) but offering all four per agency would bury the reviewer in
    near-identical junk, so the rules below encode what JLBC usage actually
    looks like:

    * The "of" initial is only kept when dropping it leaves fewer than three
      letters. That is the difference between DOT/DOA/DOC (kept) and
      DES/DEQ/DPS/DEMA (dropped) — and it reproduces both of the aliases a
      human has actually approved for this catalog.
    * More than one "of" initial is always junk ("Department of State Secretary
      of State" → "DOSO"), so that variant is refused outright.
    * The Arizona-prefixed form is only offered when the name really says
      Arizona or State, because "ADOA vs DOA" is a real inconsistency in JLBC
      usage but inventing an A out of nothing is not.
    * The Arizona/State-keeping form is refused when the geographic word is the
      LAST word of the name. A trailing "…, Arizona" is JLBC's alphabetisation
      artifact, not part of how the organisation names itself: keeping it gives
      "GSA" for the Geological Survey. Keeping an interior one gives "NAU".
    """
    name = entry.canonical_name or ""
    if not name.strip() or name_is_contaminated(name):
        return []

    reading_order = uninvert(name)
    out: list[Candidate] = []
    seen: set[str] = set()

    # "Attorney General - Department of Law" fuses two organisations. An
    # acronym read straight across the dash is mechanically fine and real
    # nobody-says-that junk, so nothing derived from the whole name may be
    # marked high confidence.
    compound = " - " in name
    ceiling = MEDIUM if compound else HIGH
    ceiling_reason = (
        "read across the “ - ” that joins two organisation names" if compound else None
    )

    def add(
        alias: str,
        kind: str,
        words: tuple[str, ...],
        source: str,
        *,
        cap: str = HIGH,
        cap_reason: str | None = None,
    ) -> None:
        if not (MIN_ALIAS_LEN <= len(alias) <= MAX_ALIAS_LEN):
            return
        if alias.upper() in seen:
            return
        # A doubled leading O is the "of" fallback misfiring on an Office-of-X
        # name ("Office of Tourism" → OOT). Readable as a typo, not shorthand.
        if alias.upper().startswith("OO"):
            cap, cap_reason = MEDIUM, "doubled leading O from the “of” initial"
        seen.add(alias.upper())
        out.append(
            Candidate(
                alias=alias.upper(),
                kind=kind,
                words=words,
                source_name=source,
                # The MORE restrictive of the two ceilings wins — a bigger
                # _CONFIDENCE_ORDER value is a worse confidence.
                ceiling=max((cap, ceiling), key=_CONFIDENCE_ORDER.get),
                ceiling_reason=cap_reason or ceiling_reason,
            )
        )

    def primary_for(
        text: str, kind: str, *, cap: str = HIGH, cap_reason: str | None = None
    ) -> str | None:
        words = _tokenize(text)
        if not words:
            return None
        bare, used = _initials(words, keep_geo=False, keep_of=False)
        if len(bare) >= 3:
            add(bare, kind, used, text, cap=cap, cap_reason=cap_reason)
            return bare
        of_count = sum(1 for w in words if w.lower() == "of")
        if of_count == 1:
            with_of, used_of = _initials(words, keep_geo=False, keep_of=True)
            if len(with_of) >= MIN_ALIAS_LEN:
                add(with_of, kind, used_of, text, cap=cap, cap_reason=cap_reason)
                return with_of
        if len(bare) >= MIN_ALIAS_LEN:
            add(bare, kind, used, text, cap=cap, cap_reason=cap_reason)
            return bare
        return None

    primary = primary_for(reading_order, PRIMARY)

    name_words = [w.lower() for w in _tokenize(name)]
    mentions_arizona = bool(set(name_words) & GEO_STOPWORDS)
    if primary and mentions_arizona and not primary.startswith("A"):
        add("A" + primary, ARIZONA_PREFIXED, (), reading_order, cap=MEDIUM)

    reading_words = [w.lower() for w in _tokenize(reading_order)]
    geo_is_trailing = bool(reading_words) and reading_words[-1] in GEO_STOPWORDS
    if mentions_arizona and not geo_is_trailing:
        keep_geo, used_geo = _initials(
            _tokenize(reading_order), keep_geo=True, keep_of=False
        )
        add(keep_geo, KEEP_GEO, used_geo, reading_order, cap=MEDIUM)

    # "ADOA - School Facilities Division" / "Attorney General - Department of
    # Law": the segment before the dash names the parent organisation, and that
    # is the part anyone abbreviates.
    if compound:
        primary_for(
            uninvert(name.split(" - ")[0]),
            FIRST_SEGMENT,
            cap=MEDIUM,
            cap_reason="read off only the parent half of the name, ignoring the "
            "part after the “ - ”",
        )

    return out


# --------------------------------------------------------------------------
# Collision resolution
# --------------------------------------------------------------------------


def _reserved_index(catalog: dict[str, AgencyEntry]) -> dict[str, list[str]]:
    """`{alias_lower: [owning canonical_id, ...]}` for slugs + approved aliases."""
    reserved: dict[str, list[str]] = {}
    for canonical_id, entry in catalog.items():
        for alias in {a.lower() for a in entry.aliases} | (
            {entry.slug.lower()} if entry.slug else set()
        ):
            reserved.setdefault(alias, []).append(canonical_id)
    return {alias: sorted(set(ids)) for alias, ids in reserved.items()}


def _name_word_index(catalog: dict[str, AgencyEntry]) -> dict[str, list[str]]:
    """`{word_lower: [canonical_id, ...]}` over every printed agency name.

    Catches the sharpest wrong-agency hazard in this catalog: the Governor's
    outline lists "Arizona Health Care Cost Containment System", whose initials
    are AHCCCS — which is the printed NAME of a different catalog entry
    (`agency:axs`). Proposing AHCCCS for the outline entry would point every
    AHCCCS question at the wrong id.
    """
    index: dict[str, list[str]] = {}
    for canonical_id, entry in catalog.items():
        names = [entry.canonical_name, *entry.name_variants]
        for word in {w.lower() for name in names for w in _tokenize(name or "")}:
            index.setdefault(word, []).append(canonical_id)
    return {word: sorted(set(ids)) for word, ids in index.items()}


def draft_all(catalog: dict[str, AgencyEntry]) -> list[AgencyDraft]:
    """Propose aliases for every agency and resolve all collisions.

    Returns one draft per catalog entry, always — an agency with no viable
    acronym is still listed, with the reason. Silence would read as "nothing to
    do here" when the truth may be "every candidate collided".
    """
    reserved = _reserved_index(catalog)
    name_words = _name_word_index(catalog)

    # A canonical name shared by two entries (three "Department of Child
    # Safety" rows, two "Arizona State University") means any acronym is
    # genuinely ambiguous between them.
    name_counts: dict[str, int] = {}
    for entry in catalog.values():
        key = (entry.canonical_name or "").strip().lower()
        name_counts[key] = name_counts.get(key, 0) + 1

    raw: dict[str, list[Candidate]] = {
        canonical_id: candidate_acronyms(entry)
        for canonical_id, entry in catalog.items()
    }

    # Who else wants each acronym.
    wanted: dict[str, list[str]] = {}
    for canonical_id, candidates in raw.items():
        for candidate in candidates:
            wanted.setdefault(candidate.alias.lower(), []).append(canonical_id)

    drafts: list[AgencyDraft] = []
    for canonical_id, entry in catalog.items():
        draft = AgencyDraft(
            canonical_id=canonical_id,
            canonical_name=entry.canonical_name,
            slug=entry.slug,
            existing_aliases=list(entry.aliases),
        )
        name_key = (entry.canonical_name or "").strip().lower()
        duplicate_name = name_counts.get(name_key, 0) > 1
        if duplicate_name:
            draft.shadow_note = (
                "another catalog entry carries this exact canonical name — any "
                "acronym is ambiguous between them"
            )
        elif entry.slug is None:
            draft.shadow_note = (
                "Governor's-outline entry with no JLBC slug — check it is not a "
                "duplicate of a slugged agency before approving"
            )

        if not raw[canonical_id]:
            if not (entry.canonical_name or "").strip():
                draft.skipped_reasons.append("no canonical name recorded")
            elif name_is_contaminated(entry.canonical_name):
                draft.skipped_reasons.append(
                    "canonical name contains index wreckage (page numbers / dot "
                    "leaders) — an acronym read off it would be garbage"
                )
            else:
                draft.skipped_reasons.append(
                    "no acronym of usable length falls out of the name"
                )
            drafts.append(draft)
            continue

        own = {a.lower() for a in entry.aliases} | (
            {entry.slug.lower()} if entry.slug else set()
        )
        for candidate in raw[canonical_id]:
            key = candidate.alias.lower()
            if key in own:
                draft.already_present.append(candidate.alias)
                continue
            owners = [cid for cid in reserved.get(key, []) if cid != canonical_id]
            if owners:
                draft.dropped.append(
                    (candidate.alias, f"already the slug/alias of {', '.join(owners)}")
                )
                continue
            rivals = [cid for cid in wanted.get(key, []) if cid != canonical_id]
            if rivals:
                draft.dropped.append(
                    (candidate.alias, f"also proposed for {', '.join(rivals)}")
                )
                continue
            # Only for 3+ letters. At two letters this fires on noise — "ld"
            # and "mi" appear inside index-page wreckage in other agencies'
            # recorded names, and reporting that as the reason a candidate was
            # dropped would be a lie.
            word_owners = (
                [cid for cid in name_words.get(key, []) if cid != canonical_id]
                if len(key) >= 3
                else []
            )
            if word_owners:
                draft.dropped.append(
                    (
                        candidate.alias,
                        "is a word printed in the name of "
                        f"{', '.join(word_owners)}",
                    )
                )
                continue
            draft.proposals.append(
                _score(candidate, entry, reserved, wanted, canonical_id, draft.shadow_note)
            )

        # Cap the review load. Proposals are already in preference order, so
        # the ones dropped here are the weakest variants of an agency that
        # already has better options on the page.
        if len(draft.proposals) > MAX_PROPOSALS_PER_AGENCY:
            for extra in draft.proposals[MAX_PROPOSALS_PER_AGENCY:]:
                draft.dropped.append(
                    (extra.alias, "weaker variant, trimmed to keep the review short")
                )
            draft.proposals = draft.proposals[:MAX_PROPOSALS_PER_AGENCY]

        drafts.append(draft)

    return drafts


def _score(
    candidate: Candidate,
    entry: AgencyEntry,
    reserved: dict[str, list[str]],
    wanted: dict[str, list[str]],
    canonical_id: str,
    shadow_note: str | None,
) -> Proposal:
    alias = candidate.alias
    lowered = alias.lower()
    ordinary = lowered in ORDINARY_ENGLISH_WORDS
    warnings: list[str] = []

    if ordinary:
        warnings.append(
            "ordinary English word — approve only with a stoplist entry"
        )

    # Two letters is short enough to appear inside ordinary budget prose and
    # inside other abbreviations, so it carries the same wrong-agency hazard as
    # an ordinary word even when it is not one.
    too_short = len(alias) < 3
    if too_short:
        warnings.append(
            "only two letters — short enough to turn up in ordinary text"
        )

    # ADOA vs DOA: one leading A apart from something already taken is a real
    # confusability hazard even though it is not a literal collision.
    neighbours = {("A" + alias).lower()}
    if alias.startswith("A"):
        neighbours.add(alias[1:].lower())
    near = sorted(
        {
            cid
            for n in neighbours
            for cid in reserved.get(n, []) + wanted.get(n, [])
            if cid != canonical_id
        }
    )
    if near:
        warnings.append(f"one leading 'A' away from {', '.join(near)}")

    if shadow_note:
        warnings.append(shadow_note)
    if candidate.ceiling_reason and candidate.ceiling != HIGH:
        warnings.append(candidate.ceiling_reason)

    # LOW is reserved for a WRONG-AGENCY hazard, not for weakness. An
    # over-long acronym that nobody says costs nothing when it is never typed;
    # an ordinary English word, or an acronym for a catalog entry that may be a
    # duplicate of another, can pull a question into the wrong documents.
    if ordinary or shadow_note or too_short:
        confidence = LOW
    elif near or candidate.kind != PRIMARY or not (3 <= len(alias) <= 4):
        confidence = MEDIUM
    else:
        confidence = HIGH
    # Never award more than the derivation's own ceiling.
    confidence = max((confidence, candidate.ceiling), key=_CONFIDENCE_ORDER.get)

    if candidate.words:
        derivation = (
            f"initials of {' / '.join(candidate.words)} — from "
            f"“{candidate.source_name}”"
        )
    else:
        derivation = (
            f"the Arizona-prefixed form of {alias[1:]} — from "
            f"“{candidate.source_name}”"
        )

    return Proposal(
        alias=alias,
        kind=candidate.kind,
        confidence=confidence,
        ordinary_word=ordinary,
        derivation=derivation,
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_HEADER = f"""# Agency alias review — {DRAFT_DATE}

**Machine-drafted. Not authoritative. Nothing here is in use yet.**

Generated by `scripts/draft_agency_aliases.py` from the canonical names in
`samples/entity-catalog.yaml`. No alias below has been added to anything.

## What an alias is, and why this list needs a human

An **alias** is a short name the search system will accept as meaning one
particular agency. The catalog already knows each agency's full name and the
short code JLBC itself uses in its web addresses (`adc`, `axs`, `dot`). It does
**not** know the shorthand people actually say — "DOC", "DEMA", "ADOA". Without
those, a question typed in shorthand has no way to reach the right agency.

**An approved alias may become a HARD filter.** That means: when the system
recognises the alias in a question, it can throw away every document belonging
to any other agency before it even starts ranking. When the alias is right,
that is exactly what you want. When it is **wrong**, the system answers
confidently out of the wrong agency's documents — and nothing on screen says
anything went wrong. That failure is much harder to notice than getting no
answer at all.

So the rule for this review is:

> **If you are not sure, strike it out. Do not guess.**
>
> A missing alias costs a little convenience. A wrong one costs trust.

## How to review

1. Work down the list. Tick `- [x]` for each alias you are **confident** means
   that agency and nothing else.
2. Leave the box unticked, or delete the line, for anything you are not sure
   about. Unticked means rejected.
3. Pay particular attention to anything marked **⚠ ordinary English word** —
   see below.
4. Save the file. That ticked file is the approved list.

### The three confidence markers

| marker | what it means |
|---|---|
| **high** | 3–4 letters, read straight off the agency's own name, nothing else in the catalog is close to it. Most of these should be quick yes/no calls. |
| **medium** | Still plausible, but weaker: an invented leading "A", a longer code, a code read across two organisation names joined by a dash, or one letter away from another agency's code. Read each one. |
| **low** | Something can go wrong here — an ordinary English word, a two-letter code short enough to appear in ordinary text, or an agency whose catalog entry may itself be a duplicate of another. **Assume no unless you know otherwise.** |

### ⚠ Ordinary English words

Some acronyms are also normal words — `art`, `law`, `tax`, `des`, `doc`, `age`.
If one of these becomes a hard filter, then an innocent question ("what is the
state of the art in…") gets pinned to one agency. If you want to approve one
anyway, it must **also** be added to the `AMBIGUOUS_ALIASES` stoplist in
`retrieval/query_agency.py`, which lets it nudge ranking without ever filtering.

_(That file did not exist yet when this draft was generated — it is being
written alongside it. If the stoplist is still missing when the approved list
is applied, the ordinary-word aliases must wait for it rather than going in
without it.)_

## What to do once this is approved

1. For each ticked alias, add it under that agency's `aliases:` key in
   `samples/entity-catalog.yaml`:

   ```yaml
   - canonical_name: Corrections, State Department of
     canonical_id: agency:adc
     slug: adc
     aliases:
     - doc
     - adoc          # ← newly approved entries go here
   ```

2. Add every approved alias that is an ordinary English word to
   `AMBIGUOUS_ALIASES` in `retrieval/query_agency.py`.
3. Commit those two changes separately from this document, so the diff shows
   exactly which aliases went live.

---
"""


def _agency_line(draft: AgencyDraft) -> list[str]:
    slug = f"`{draft.slug}`" if draft.slug else "_no JLBC slug_"
    existing = ", ".join(f"`{a}`" for a in draft.existing_aliases) or "—"
    lines = [
        f"**{draft.canonical_name}**  ",
        f"`{draft.canonical_id}` · slug {slug} · already has: {existing}",
        "",
    ]
    for proposal in draft.proposals:
        flags = " ".join(
            f"⚠ {w}" for w in proposal.warnings
        )
        suffix = f"  \n  {flags}" if flags else ""
        lines.append(
            f"- [ ] **`{proposal.alias.lower()}`** — _{proposal.confidence}_ — "
            f"{proposal.derivation}{suffix}"
        )
    if draft.already_present:
        lines.append(
            "- _nothing to do — the generator also proposed "
            + ", ".join(f"`{a.lower()}`" for a in draft.already_present)
            + ", which this agency already has_"
        )
    for alias, reason in draft.dropped:
        lines.append(f"- _not offered: `{alias.lower()}` — {reason}_")
    for reason in draft.skipped_reasons:
        lines.append(f"- _no proposal — {reason}_")
    lines.append("")
    return lines


def render_markdown(drafts: list[AgencyDraft]) -> str:
    """The review document. Deterministic: sorted, and dated by constant."""
    with_proposals = [d for d in drafts if d.proposals]
    without = [d for d in drafts if not d.proposals]

    total_proposals = sum(len(d.proposals) for d in with_proposals)
    ordinary = sum(
        1 for d in drafts for p in d.proposals if p.ordinary_word
    )
    dropped = sum(len(d.dropped) for d in drafts)

    parts: list[str] = [_HEADER]
    parts.append("## At a glance\n")
    parts.append(
        "| | count |\n|---|---|\n"
        f"| agencies in the catalog | {len(drafts)} |\n"
        f"| agencies with at least one proposal | {len(with_proposals)} |\n"
        f"| agencies with no viable proposal | {len(without)} |\n"
        f"| proposals to review | {total_proposals} |\n"
        f"| of those, ordinary English words | {ordinary} |\n"
        f"| candidates dropped before you see them | {dropped} |\n"
    )

    sections = [
        (
            HIGH,
            "High confidence — the skimmable bulk",
            "Read the acronym, read the agency name, tick or don't.",
        ),
        (
            MEDIUM,
            "Medium confidence — read each one",
            "Weaker derivations: two-letter codes, invented leading “A”s, "
            "and codes one letter away from another agency.",
        ),
        (
            LOW,
            "Low confidence — assume no",
            "Ordinary English words, long codes, and agencies whose catalog entry "
            "may itself be a duplicate. These are the ones that can send a "
            "question to the wrong agency.",
        ),
    ]
    for level, title, blurb in sections:
        bucket = sorted(
            (d for d in with_proposals if d.best_confidence == level),
            key=lambda d: (d.canonical_name.lower(), d.canonical_id),
        )
        parts.append(f"\n## {title} ({len(bucket)} agencies)\n")
        parts.append(f"{blurb}\n")
        if not bucket:
            parts.append("_None._\n")
            continue
        for d in bucket:
            parts.extend(_agency_line(d))

    parts.append(f"\n## No proposal — nothing to review ({len(without)} agencies)\n")
    parts.append(
        "Listed so the document accounts for all "
        f"{len(drafts)} agencies. An agency missing from a review list reads as "
        "“nothing to do” when the truth may be “every candidate "
        "collided”.\n"
    )
    for d in sorted(without, key=lambda d: (d.canonical_name.lower(), d.canonical_id)):
        parts.extend(_agency_line(d))

    parts.append(_slug_word_appendix())
    return "\n".join(parts).rstrip() + "\n"


def _slug_word_appendix() -> str:
    """Existing slugs that are ordinary English words.

    Not proposals — these are already aliases today, because `_aliases()` adds
    every slug unconditionally. They carry exactly the hard-filter hazard this
    review exists to catch, so the reviewer should see them even though there
    is nothing to approve.
    """
    catalog = load_agency_catalog()
    rows = sorted(
        (entry.slug.lower(), canonical_id, entry.canonical_name)
        for canonical_id, entry in catalog.items()
        if entry.slug and entry.slug.lower() in ORDINARY_ENGLISH_WORDS
    )
    lines = [
        "\n## Appendix — aliases that are ALREADY live and are ordinary words\n",
        "Nothing to approve here; this is a warning. Every agency's JLBC slug is",
        "already treated as an alias, and some of those slugs are ordinary English",
        "words. They carry the same hard-filter hazard as anything above, so they",
        "belong in `AMBIGUOUS_ALIASES` whether or not any new alias is approved.\n",
    ]
    if not rows:
        lines.append("_None found._\n")
        return "\n".join(lines)
    lines.append("| slug | agency |")
    lines.append("|---|---|")
    for slug, canonical_id, name in rows:
        # canonical_id is deliberately NOT wrapped in backticks here — the
        # document promises exactly one `agency:x` mention per agency, and that
        # mention belongs to the agency's own review row above.
        lines.append(f"| `{slug}` | {name} ({canonical_id}) |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--catalog",
        default=None,
        help="path to entity-catalog.yaml (defaults to the repo's own copy)",
    )
    args = parser.parse_args(argv)
    catalog = load_agency_catalog(args.catalog)
    sys.stdout.write(render_markdown(draft_all(catalog)))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
