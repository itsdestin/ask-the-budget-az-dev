"""Resolve Arizona agencies named in a natural-language query (spec Q1, Q2).

An analyst types `doc baseline`, `dema ar` or `ahcccs 27ar`. Retrieval already
supports an `agency_canonical_id` filter and always has — nothing was ever
filling it in from the question, so `dema ar` searched the whole corpus by
similarity and came back full of Attorney General pages.

This module is the query-side half of agency resolution. `chunking/
entity_stamper.py` is the corpus-side half, and the two MUST agree: a chunk is
stamped `agency:ema` by matching the printed name against the catalog, so a
query has to reach `agency:ema` by the same route or the filter matches
nothing. That is why this module imports the stamper's own normalizer, its
fuzzy processor, and its ≥85 `token_set_ratio` floor rather than growing a
second dialect of "close enough".

Every result carries a `Confidence` (see `retrieval/query_match.py`), because
the two outcomes are not equally safe. An EXACT match may become a HARD filter,
which deletes every other agency from the result set — wonderful when right,
a blank page when wrong. A WEAK match only earns a ranking boost. When in
doubt this module returns WEAK: a boost that was not deserved costs the analyst
a little ranking quality, where a filter that was not deserved costs them the
whole answer.

Resolution order, most confident first. Later tiers only add agencies the
earlier ones did not already find, and tier 4 runs ONLY if tiers 1-3 found
nothing at all — the same "fuzzy is a fallback, never a supplement" shape the
stamper uses.

  1. A full catalog name — canonical name, an inverted "Department of X" form,
     or a publisher-observed `name_variant` — appearing in the query. EXACT.
  2. The catalog name's HEAD, the part before the first comma: "Corrections",
     "Emergency and Military Affairs". EXACT when it identifies exactly one
     agency. See `_name_phrases` for why the head rather than single words.
  3. An alias — the JLBC URL slug, or a reviewed acronym from the catalog.
     EXACT when it identifies exactly one agency and is not stoplisted.
  4. rapidfuzz `token_set_ratio` >= 85 against catalog names. Always WEAK.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from chunking.agency_catalog import load_agency_catalog

# Imported, not re-implemented. Query-side and corpus-side resolution have to
# normalize identically or they resolve the same words to different agencies —
# spec Q1's whole point. `_FUZZY_THRESHOLD` is the stamper's 85 floor for the
# same reason: two floors would drift apart at the first tuning session.
from chunking.entity_stamper import (
    _FUZZY_THRESHOLD,
    _MIN_SCAN_NAME_LEN,
    _fuzzy_processor,
    _invert_comma_form,
    _normalize_for_match,
)
from retrieval.query_match import Confidence, Match

# Aliases that are also ordinary English words, or another agency's everyday
# shorthand. They still MATCH — "doc baseline" must find Corrections — but they
# are demoted to WEAK so they earn a ranking boost instead of a hard filter.
#
# HAND-MAINTAINED, deliberately. Ambiguity WITHIN the catalog is detected
# automatically — an alias two agencies share comes out WEAK without being
# listed here. This list covers ambiguity against everything OUTSIDE the
# catalog, which the catalog cannot see. Re-read it whenever aliases are added
# to samples/entity-catalog.yaml.
#
# The first five are the plan's seed: `doc` collides with "document", `ar` with
# "Appropriations Report", `afr` with the Annual Financial Report document
# type, `des` with the French article that shows up in pasted text, `pp` with
# the "pp." page abbreviation.
#
# `for`, `per`, `tax` and `gov` were added after MEASURING, not by intuition,
# and they matter more than the seed because they are live JLBC slugs — Task 1
# puts every slug into `aliases` unconditionally, so each was resolving EXACT
# and hard-filtering. Counting how often each of the 157 aliases appears as an
# ordinary word in 247,607 tokens of real Arizona budget English (the three
# eval query sets plus the website index's document titles) separates them
# cleanly from the rest:
#
#     gov 5944 · per 3993 · tax 541 · for 474 · then a floor at ~190
#
# The floor is where slugs merely appear inside source URLs (/26AR/adc.pdf), so
# everything at or below it is noise. Nothing else clears it. `for` alone
# hard-filtered 13 of the 47 eval queries onto Forestry and Fire Management.
#
# Demoting a slug costs almost nothing: the agency's real NAME is a separate,
# higher tier, so "forestry and fire management" still resolves EXACT. Only the
# bare three-letter shorthand loses the right to empty the page.
#
# Re-derive with the recipe above whenever the catalog gains aliases.
AMBIGUOUS_ALIASES: frozenset[str] = frozenset(
    {"doc", "ar", "afr", "des", "pp", "for", "per", "tax", "gov"}
)

# Shortest catalog phrase the substring scan will trust — the SAME floor
# `chunking/entity_stamper.py` uses for its corpus-side name scan, and imported
# from there rather than re-picked so the two sides cannot drift.
#
# The catalog contains one-character debris heads ('g', 'j' — PDF-extraction
# leftovers) that would fire inside half the queries ever typed. Four would
# have been enough to drop those, and it was the first choice here; five is
# what shipped, because at four the only two survivors are 'arts' and 'fire',
# and 'fire' hard-filtered "what general appropriations were made from the
# Prison Construction and Operations Fund... Fire and Life Safety Upgrades?"
# onto the Department of Fire, Building and Life Safety. The query does say
# "Fire", so the match is not wrong — it is just far too thin to justify
# deleting every other agency from the answer.
#
# The cost is that 'arts' and 'fire' alone no longer resolve their agencies;
# both still resolve from their full names. That is the trade this whole module
# prefers: a missed match costs ranking, a wrong hard filter costs the page.
_MIN_PHRASE_LEN = _MIN_SCAN_NAME_LEN

# An alias shorter than this is WEAK even when the catalog says it is unique.
# Two letters is not enough signal to delete every other agency from a result
# set — 'cs' and 'cf' are real catalog slugs and also appear in ordinary text.
_MIN_EXACT_ALIAS_LEN = 3

# Fuzzy matching runs on multi-word windows only, never on a single word.
# WHY: `token_set_ratio` scores 100 whenever one string's tokens are a SUBSET
# of the other's, so the single word "corrections" scores a perfect 100 against
# every catalog name containing it. That is a substring rule wearing a fuzzy
# mask, and it reports certainty it has not earned. Tier 2 already handles the
# single-word case properly, with an ambiguity check tier 4 cannot do.
_MIN_FUZZY_WINDOW_TOKENS = 2
_MAX_FUZZY_WINDOW_TOKENS = 6

# Below this many characters a window carries too little signal to fuzzy-match
# at all: at 2-3 characters "ar" scores above the floor against a large slice
# of a 157-agency catalog, and would resolve "dema ar" to Agriculture.
_MIN_FUZZY_CHARS = 4

# A fuzzy window must be at least this fraction of the name it matched, counted
# in tokens. This is the second half of the subset defence above, and it was
# added after a measured false positive: "how much did the state spend on
# homelessness" resolved to the Arizona State Schools for the Deaf and the
# Blind, because the window "the state" is a token SUBSET of that agency's
# nine-token name and `token_set_ratio` scores a subset 100. Two shared
# function words are not evidence about an agency. Requiring the window to
# cover half the name makes a real typo ("emergancy and military affairs" —
# four tokens of a six-token name) still pass while stopword overlap cannot.
_MIN_FUZZY_NAME_COVERAGE = 0.5

# How many candidate names to inspect per window. `extractOne` returns only the
# single best score, and the best-scoring name is frequently one the coverage
# rule then rejects — checking a few runners-up keeps a genuine typo match that
# a stopword-subset name would otherwise have hidden.
_FUZZY_CANDIDATES = 5

# Words that describe what KIND of body an agency is, plus the grammar holding
# a name together. A phrase built from nothing else is not an agency name.
#
# WHY this exists: the catalog carries PDF-extraction debris. `agency:ost` has
# a literal `name_variant` of "Board of" — the tail of a table-of-contents line
# that wrapped — which would index "board of" as an exact name for the Board of
# Osteopathic Examiners and hard-filter the query "board of regents" onto it.
# That is the same class of debris Task 1 removed for `agency:des`, found by
# reading the index rather than by hitting it.
#
# Deliberately NARROW. "State", "Arizona" and "System" are NOT here: the State
# Boards Office (`agency:sbo`) is a real agency whose entire name is made of
# words that feel generic, and a wider list would delete it from the index.
_ORG_TYPE_WORDS = frozenset(
    {
        "board", "boards", "commission", "commissions", "department",
        "departments", "office", "offices", "council", "councils",
        "authority", "authorities", "agency", "agencies", "division",
        "divisions", "bureau", "bureaus", "committee", "committees",
    }
)
_FUNCTION_WORDS = frozenset({"of", "the", "and", "for", "in", "on", "to", "a", "an"})


def parse_query_agencies(
    query: str, *, catalog_path: Path | str | None = None
) -> list[Match]:
    """Agencies named in `query`, most confident first.

    Returns `[]` when the query names none — the signal callers use to mean
    "no agency filter, this question is agency-agnostic". Never raises on
    junk input; an unparseable query is simply a query that named no agency.

    `catalog_path` exists for tests that want a fixture catalog; production
    callers pass nothing and get the workspace catalog.
    """
    if not query or not query.strip():
        return []

    index = _index(str(Path(catalog_path)) if catalog_path is not None else None)
    normalized = _normalize_for_match(query)
    if not normalized:
        return []

    matches: list[Match] = []
    seen: set[str] = set()

    def _add(canonical_id: str, confidence: Confidence, matched_text: str) -> None:
        # First tier to name an agency owns it. Tiers run most-confident-first,
        # so a later, weaker sighting of the same agency must not downgrade a
        # confident one — nor add a duplicate the filter/boost would count twice.
        if canonical_id in seen:
            return
        seen.add(canonical_id)
        matches.append(Match(canonical_id, confidence, matched_text))

    # --- Tiers 1 + 2: catalog names and their heads -------------------------
    # One scan, because a head is always shorter than the full name it came
    # from and the scan is longest-first: the full name claims its span before
    # its own head can match inside it, which IS the tier ordering.
    for phrase in _scan_phrases(normalized, index.phrases_longest_first):
        ids = index.phrase_to_ids[phrase]
        # Ambiguity is decided by the catalog, not by a hand-written list: two
        # agencies really are called "Education", so neither one may hard-filter.
        confidence = Confidence.EXACT if len(ids) == 1 else Confidence.WEAK
        for canonical_id in ids:
            _add(canonical_id, confidence, phrase)

    # --- Tier 3: slugs and reviewed acronyms --------------------------------
    for alias in _scan_phrases(normalized, index.aliases_longest_first):
        ids = index.alias_to_ids[alias]
        exact = (
            len(ids) == 1
            and alias not in AMBIGUOUS_ALIASES
            and len(alias) >= _MIN_EXACT_ALIAS_LEN
        )
        confidence = Confidence.EXACT if exact else Confidence.WEAK
        for canonical_id in ids:
            _add(canonical_id, confidence, alias)

    # --- Tier 4: fuzzy fallback ---------------------------------------------
    # Only when nothing else matched. A fuzzy hit ALONGSIDE a confident one is
    # noise that would drag an otherwise-filterable match set down to WEAK, and
    # a query that already named an agency exactly does not need guessing.
    if not matches:
        fuzzy = _fuzzy_match(normalized, index)
        if fuzzy is not None:
            canonical_id, matched_text = fuzzy
            _add(canonical_id, Confidence.WEAK, matched_text)

    return matches


# --- index -------------------------------------------------------------------


class _AgencyIndex:
    """Query-matching indexes derived from the catalog.

    Built once per catalog path and cached. `load_agency_catalog()` is itself
    cached, but rebuilding these tables costs a pass over 157 agencies and
    several hundred name strings, and `parse_query_agencies` runs on the hot
    path of every single retrieval — once per query would be a real cost for a
    table that cannot change while the process is alive.
    """

    __slots__ = (
        "phrase_to_ids",
        "phrases_longest_first",
        "alias_to_ids",
        "aliases_longest_first",
        "fuzzy_names",
        "fuzzy_name_to_ids",
    )

    def __init__(self, catalog_path: str | None) -> None:
        phrase_to_ids: dict[str, set[str]] = {}
        alias_to_ids: dict[str, set[str]] = {}
        fuzzy_name_to_ids: dict[str, set[str]] = {}
        fuzzy_names: list[str] = []

        for entry in load_agency_catalog(catalog_path).values():
            for phrase in _name_phrases(entry.canonical_name, entry.name_variants):
                phrase_to_ids.setdefault(phrase, set()).add(entry.canonical_id)

            for alias in entry.aliases:
                key = _normalize_for_match(alias)
                if key:
                    alias_to_ids.setdefault(key, set()).add(entry.canonical_id)

            # The fuzzy tier matches whole printed names only. Heads are left
            # out on purpose: they are already handled exactly, and a fuzzy
            # match on a fragment is a guess built on a guess.
            for name in [entry.canonical_name, *entry.name_variants]:
                if not name:
                    continue
                key = _normalize_for_match(name)
                if not key:
                    continue
                if key not in fuzzy_name_to_ids:
                    fuzzy_names.append(name)
                fuzzy_name_to_ids.setdefault(key, set()).add(entry.canonical_id)

        self.phrase_to_ids = phrase_to_ids
        self.alias_to_ids = alias_to_ids
        self.fuzzy_name_to_ids = fuzzy_name_to_ids
        self.fuzzy_names = fuzzy_names
        # Longest-first is what makes overlapping names behave: "juvenile
        # corrections" claims its span before "corrections" can match inside it.
        # Same rationale as `_scan_for_names` in chunking/entity_stamper.py.
        self.phrases_longest_first = sorted(phrase_to_ids, key=len, reverse=True)
        self.aliases_longest_first = sorted(alias_to_ids, key=len, reverse=True)


@lru_cache(maxsize=None)
def _index(catalog_path: str | None) -> _AgencyIndex:
    return _AgencyIndex(catalog_path)


def _name_phrases(canonical_name: str, name_variants: list[str]) -> set[str]:
    """Every normalized phrase that should resolve to one agency by name.

    Two kinds, and the difference is the whole of tiers 1 and 2:

    FULL NAMES — the canonical name, each publisher-observed variant, and the
    inverted comma form, because the catalog files agencies as "Corrections,
    State Department of" while an analyst types "Department of Corrections".

    HEADS — the part before the first comma. This is the agency's actual
    subject: "Corrections", "Emergency and Military Affairs". The plan called
    this "a distinctive single word", but a single word is the wrong unit here.
    Split "Juvenile Corrections, Department of" into words and `corrections`
    belongs to two agencies, so `corrections baseline` — an unambiguous
    question — would resolve to nothing. Kept whole, "corrections" and
    "juvenile corrections" are two different heads, each naming exactly one
    agency, and the longest-first scan picks the right one.
    """
    phrases: set[str] = set()
    for name in [canonical_name, *name_variants]:
        if not name:
            continue
        for form in (name, _invert_comma_form(name)):
            if not form:
                continue
            phrases.add(_normalize_for_match(form))
        phrases.add(_normalize_for_match(name.split(",", 1)[0]))
    return {p for p in phrases if _is_usable_phrase(p)}


def _is_usable_phrase(phrase: str) -> bool:
    """Is this normalized phrase specific enough to name an agency?

    Two rejections, both of catalog debris rather than of real names: anything
    too short to carry meaning, and anything built entirely from org-type and
    grammar words (see `_ORG_TYPE_WORDS` for the "Board of" case that prompted
    this).
    """
    if len(phrase) < _MIN_PHRASE_LEN:
        return False
    tokens = phrase.split()
    return any(t not in _ORG_TYPE_WORDS and t not in _FUNCTION_WORDS for t in tokens)


# --- scanning ----------------------------------------------------------------


def _scan_phrases(normalized_query: str, phrases_longest_first: list[str]) -> list[str]:
    """Catalog phrases appearing in the query, in first-mention order.

    Adapted from `_scan_for_names` in chunking/entity_stamper.py — same
    longest-first walk, same span claiming — with two query-side differences:
    it returns the PHRASES rather than resolved ids (the caller needs to know
    whether a phrase was ambiguous), and it matches on whole-word boundaries.

    Boundaries matter more here than in the stamper. A chunk is a page of
    prose where a stray substring hit is one weak signal among many; a query is
    four words, and one of them silently matching inside another word decides
    the entire result set.
    """
    # Padding the query with spaces turns "does this phrase appear" into a
    # whole-word test with a plain `find` — no regex compiled per phrase.
    padded = f" {normalized_query} "
    hits: list[tuple[int, str]] = []
    consumed: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in consumed)

    for phrase in phrases_longest_first:
        needle = f" {phrase} "
        offset = 0
        while True:
            idx = padded.find(needle, offset)
            if idx == -1:
                break
            # Claim the phrase itself, NOT its padding: consecutive phrases
            # share the single space between them, and claiming the pad would
            # make "corrections baseline" reject its own second word.
            start, end = idx + 1, idx + len(needle) - 1
            if not _overlaps(start, end):
                hits.append((start, phrase))
                consumed.append((start, end))
            offset = end
    hits.sort(key=lambda pair: pair[0])
    return [phrase for _, phrase in hits]


def _fuzzy_match(
    normalized_query: str, index: _AgencyIndex
) -> tuple[str, str] | None:
    """Best `(canonical_id, matched_window)` above the stamper's 85 floor.

    Walks multi-word windows of the query longest-first and returns the first
    that clears both the score floor and `_MIN_FUZZY_NAME_COVERAGE`, mirroring
    the stamper's `extract` fallback. This tier exists for typos and word-order
    drift ("emergancy and military affairs"), which the exact tiers cannot
    forgive; it is never EXACT, so a wrong guess costs ranking rather than the
    page.
    """
    # One-character tokens are dropped before windowing. They are punctuation
    # debris, not words: normalization turns "Tucson's General Fund" into
    # "tucson s general fund", and the orphaned "s" formed the window
    # "s general", which scored above the floor against "Auditor General" and
    # resolved a City of Tucson question to the Auditor General. No agency name
    # contains a one-letter word, so nothing real is lost.
    tokens = [t for t in normalized_query.split() if len(t) > 1]
    if not tokens:
        return None

    widest = min(_MAX_FUZZY_WINDOW_TOKENS, len(tokens))
    for size in range(widest, _MIN_FUZZY_WINDOW_TOKENS - 1, -1):
        for start in range(0, len(tokens) - size + 1):
            window = " ".join(tokens[start : start + size])
            # `_is_usable_phrase` is applied to the QUERY side here for the
            # same reason it is applied to the catalog side: "did the state
            # spend on" carries no agency signal, so scoring it can only
            # produce a false positive. It also removes most of the windows a
            # long question generates, which is where this tier's cost lives.
            if len(window) < _MIN_FUZZY_CHARS or not _is_usable_phrase(window):
                continue
            for name, _score, _idx in process.extract(
                window,
                index.fuzzy_names,
                scorer=fuzz.token_set_ratio,
                processor=_fuzzy_processor,
                score_cutoff=_FUZZY_THRESHOLD,
                limit=_FUZZY_CANDIDATES,
            ):
                key = _normalize_for_match(name)
                ids = index.fuzzy_name_to_ids.get(key)
                if not ids:
                    continue
                if size < len(key.split()) * _MIN_FUZZY_NAME_COVERAGE:
                    continue
                # Sorted so a name two agencies share resolves deterministically
                # rather than on set-iteration order; it is WEAK either way.
                return sorted(ids)[0], window
    return None
