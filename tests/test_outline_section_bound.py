"""Heading inheritance is bounded (chunking/readers/types.py).

Both readers build the outline with a level-stacked walk that had NO
distance limit: a heading stayed on the stack until a same-or-lower-level
heading appeared. A document whose real section breaks the extractor did
not mark as headings inherits one heading for the rest of the book.

Measured on the live corpus 2026-08-16, and it is not hypothetical:
`agao-afr-fy2024`'s appropriations schedule is ~180 consecutive pages of
bare `<table>` blocks, so 121 of its 450 passages claimed "(expressed in
thousands)" over whole-dollar figures -- a 1,000x units error inherited
from a heading four pages earlier that belongs to a DIFFERENT statement.
Corpus-wide, all 24 heading runs longer than 20 pages are wrong, including
"Table of Contents" governing 408 consecutive pages of the FY2027
Governor's budget.

These specs pin the BOUND, not the number: they derive their page offsets
from `MAX_SECTION_PAGES`, so moving the constant moves the tests with it
and only a change of BEHAVIOUR can fail them.
"""
from __future__ import annotations

import pytest

from chunking.readers.types import (
    MAX_SECTION_PAGES,
    Bbox,
    Heading,
    OutlineNode,
    Page,
    Paragraph,
    drop_stale_sections,
)
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.odl_reader import ODLReader

BBOX = Bbox(x0=0.0, y0=0.0, x1=1.0, y1=1.0)


def _heading(text: str, page: int, level: int = 1) -> Heading:
    return Heading(text=text, level=level, page=page, bbox=BBOX)


def _para(text: str, page: int) -> Paragraph:
    return Paragraph(text=text, page=page, bbox=BBOX)


def _pages(blocks) -> list[Page]:
    """One Page per distinct page number, blocks in the order given."""
    by_page: dict[int, list] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)
    return [Page(page_number=p, blocks=by_page[p]) for p in sorted(by_page)]


def _leaf_texts(outline: list[OutlineNode]) -> dict[str, list[str]]:
    """Map heading text -> the body-block texts attached under it."""
    out: dict[str, list[str]] = {}

    def walk(node: OutlineNode) -> None:
        out[node.text] = [getattr(b, "text", "") for b in node.body_blocks]
        for c in node.children:
            walk(c)

    for n in outline:
        walk(n)
    return out


# Both readers share the identical algorithm (the MinerU reader's docstring
# says so). A fix applied to one and not the other would leave the defect
# live on every PDF that reads cleanly on the first rung, which is most of
# the corpus -- so every spec below runs against BOTH.
READERS = [
    pytest.param(MinerUReader, id="mineru"),
    pytest.param(ODLReader, id="opendataloader"),
]


@pytest.mark.parametrize("reader_cls", READERS)
def test_a_block_exactly_at_the_bound_still_inherits(reader_cls):
    """MAX_SECTION_PAGES is how many pages a heading MAY govern, so the
    block exactly that far away is still inside it. An off-by-one here
    silently shortens every section in the corpus by a page."""
    pages = _pages([
        _heading("Capital Projects", page=1),
        _para("still in the section", page=1 + MAX_SECTION_PAGES),
    ])

    outline = reader_cls()._build_outline(pages)

    assert _leaf_texts(outline)["Capital Projects"] == ["still in the section"]


@pytest.mark.parametrize("reader_cls", READERS)
def test_a_block_one_page_past_the_bound_does_not_inherit(reader_cls):
    """The whole point. Without this the block joins a section whose
    heading may name a different statement and a different unit scale."""
    pages = _pages([
        _heading("Capital Projects", page=1),
        _para("a new statement nobody marked", page=2 + MAX_SECTION_PAGES),
    ])

    outline = reader_cls()._build_outline(pages)

    assert _leaf_texts(outline)["Capital Projects"] == []


@pytest.mark.parametrize("reader_cls", READERS)
def test_the_real_shape_a_heading_cannot_govern_a_whole_book(reader_cls):
    """agao-afr-fy2024, reduced: a units-declaring heading, then a long run
    of pages carrying only tables. Before the bound the heading reached the
    last page of the book; now it stops."""
    blocks = [_heading("STATEMENT ... (expressed in thousands)", page=5)]
    blocks += [_para(f"whole-dollar table page {p}", page=p) for p in range(9, 192)]

    outline = reader_cls()._build_outline(_pages(blocks))
    governed = _leaf_texts(outline)["STATEMENT ... (expressed in thousands)"]

    assert governed, "the bound must not orphan the pages right after the heading"
    last = max(int(t.rsplit(" ", 1)[1]) for t in governed)
    assert last == 5 + MAX_SECTION_PAGES
    # The honest half of the claim: this is a BACKSTOP. Pages inside the
    # bound still inherit the wrong heading, and the docstring on
    # MAX_SECTION_PAGES says so rather than overselling the fix.
    assert len(governed) < 183, "it must actually stop somewhere"


@pytest.mark.parametrize("reader_cls", READERS)
def test_a_fresh_child_protects_a_stale_ancestor(reader_cls):
    """Popping from the deepest end only. A heading 1 page back nested under
    one far past the bound is real nesting, not an inheritance accident, and
    dropping the ancestor would corrupt the section PATH of a correctly
    headed chunk."""
    far = 3 + MAX_SECTION_PAGES * 2
    pages = _pages([
        _heading("Part II — Appropriations", page=1, level=1),
        _heading("Department of Administration", page=far, level=2),
        _para("a line item", page=far),
    ])

    outline = reader_cls()._build_outline(pages)

    assert _leaf_texts(outline)["Department of Administration"] == ["a line item"]
    # And the ancestor is still the parent, so the path is two deep.
    assert outline[0].text == "Part II — Appropriations"
    assert [c.text for c in outline[0].children] == ["Department of Administration"]


@pytest.mark.parametrize("reader_cls", READERS)
def test_an_ordinary_multi_page_section_is_untouched(reader_cls):
    """99.1% of real heading runs are MAX_SECTION_PAGES or fewer and 86.5%
    are one page. The bound must be invisible to all of them -- a change
    that improved the AFR by shortening every JLBC agency section would be
    a regression wearing a fix's clothes.

    Derived from the constant, not hardcoded: a section exactly as long as
    the bound allows keeps every one of its pages."""
    first = 40
    last = first + MAX_SECTION_PAGES
    pages = _pages([
        _heading("Red Imported Fire Ant Control", page=first),
        *[_para(f"body {p}", page=p) for p in range(first, last + 1)],
    ])

    outline = reader_cls()._build_outline(pages)

    kept = _leaf_texts(outline)["Red Imported Fire Ant Control"]
    assert len(kept) == MAX_SECTION_PAGES + 1


def test_the_helper_pops_every_stale_ancestor_not_just_one():
    """`while`, not `if`. Two stacked stale sections must both go, or the
    outer one keeps governing and the bound leaks.

    Known EQUIVALENT MUTANT, checked rather than assumed: replacing the
    whole loop with `stack.clear()` passes every spec in this file, and it
    is genuinely equivalent, not a coverage gap. Headings are pushed in
    document order, so the stack is non-decreasing in page number -- if the
    deepest section is stale, every ancestor is older and therefore stale
    too. Verified on the real `agao-afr-fy2024` outline: 0 nodes anywhere in
    the tree have an ancestor on a later page. The loop is kept because it
    states the intent ("drop what is stale") rather than relying on that
    invariant holding forever.
    """
    stack = [
        OutlineNode(text="outer", level=1, page=1),
        OutlineNode(text="inner", level=2, page=2),
    ]

    drop_stale_sections(stack, page=3 + MAX_SECTION_PAGES)

    assert stack == []


def test_the_helper_leaves_a_live_section_alone():
    stack = [OutlineNode(text="live", level=1, page=10)]

    drop_stale_sections(stack, page=10 + MAX_SECTION_PAGES)

    assert [n.text for n in stack] == ["live"]
