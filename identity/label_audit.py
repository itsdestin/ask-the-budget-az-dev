"""Per-agency label error rate, and a no-write simulator for calibrating fixes.

This is the instrument the label fix (Tasks 2-4) is calibrated against. The
alternative is to change the matcher, rewrite all 83,016 `budget_chunks`
rows, and only THEN find out whether it helped -- so this module exists to
answer that question for free, before any write happens.

WHY PER-AGENCY, NOT JUST A CORPUS TOTAL: a single number cannot distinguish
"fixed the osteopathic defect" from "unlabelled half of Corrections", and
those two outcomes have opposite value. `LabelAudit.per_agency` is the whole
point of this module; `.total_unmentioned` is a convenience roll-up, never
the number a fix is judged on.

WHY PER DOCUMENT, NOT PER CHUNK: a per-chunk error metric counts a correctly
labelled document's own `FOOTNOTES` page as an error, so it can never reach
zero and its target would be a lie. A document is an error only when NONE of
its chunks corroborate the label it was stamped with.

WHY GATE ON THE ERROR RATE, NEVER ON HOW MANY LABELS EXIST: the number of
labels produced rises under any rule change, looser or stricter alike, and
mistaking that rise for improvement is the exact mistake that produced the
osteopathic defect in the first place (CLAUDE.md, "measure the error rate,
not the production rate").

CURRENT BASELINE (measured against the live corpus before any matcher
change; see `eval/results/label-audit-baseline.json` once Step 5 runs):
1,072 documents total carry a label none of their own chunks mention.
`agency:ost` (Osteopathic Examiners) accounts for 732 of those alone --
by far the largest single contributor. The next largest are `agency:rac`
38, `agency:lan` 38, `agency:pod` 29, `agency:den` 27, `agency:art` 25.
Four large agencies sit at a 0% error rate today: `agency:tre` (Treasurer),
`agency:gam` (Gaming), `agency:adc` (Corrections), `agency:axs` (AHCCCS) --
proof the defect is concentrated, not corpus-wide, which is exactly what a
per-agency instrument is needed to see and a corpus total would hide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

# The corroboration rule is a PARAMETER, not an import. A sibling task is
# about to recalibrate `identity.validator.mentions_agency`, and this module
# has to be able to compare candidate rules against each other and against
# today's shipped rule -- importing one fixed rule would make that
# impossible. Callers pass `identity.validator.mentions_agency` (or a
# candidate) explicitly; the tests pass a deliberately dumb substring double
# so the specs measure the AUDIT logic, not whichever rule happens to be
# live.
MentionsFn = Callable[[str, str], bool]

# A resolver takes the same keyword shape as a `budget_chunks` row (minus
# `vector`, which this module never requests -- see `load_live`) and returns
# the list of canonical agency ids it WOULD assign. Task 3's candidate
# matcher and the shipped `chunking.entity_stamper` resolver both fit this
# shape, which is what lets `simulate` compare them without writing to the
# corpus.
Resolver = Callable[..., list[str]]


@dataclass(frozen=True)
class AgencyError:
    """One agency's error rate: how many of ITS documents carry a label none
    of their own chunks corroborate, out of how many documents it labels."""

    documents: int
    unmentioned: int

    @property
    def rate(self) -> float:
        # `documents` is guaranteed > 0 by construction (see audit_labels --
        # an agency with 0 documents is omitted, never recorded with rate
        # 0/0), so this never divides by zero.
        return self.unmentioned / self.documents


@dataclass
class LabelAudit:
    per_agency: dict[str, AgencyError] = field(default_factory=dict)
    total_unmentioned: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_unmentioned": self.total_unmentioned,
            "per_agency": {
                agency_id: {
                    "documents": err.documents,
                    "unmentioned": err.unmentioned,
                    "rate": err.rate,
                }
                for agency_id, err in self.per_agency.items()
            },
        }


def audit_labels(
    *,
    chunks_by_doc: Mapping[str, Iterable[str]],
    stamps_by_doc: Mapping[str, Iterable[str]],
    agency_names: Mapping[str, str],
    mentions: MentionsFn,
) -> LabelAudit:
    """Per-agency label error rate: how many of each agency's documents carry
    that label without a single chunk of the document corroborating it.

    Pure function of already-loaded data -- no DB, no model -- so the suite
    drives it with plain dicts. `mentions` is the corroboration rule under
    test; pass `identity.validator.mentions_agency` for the shipped rule or
    a candidate for calibration (see the module docstring for why this is a
    parameter rather than an import).
    """
    # documents_by_agency[agency_id] -> count of documents stamped with it
    # unmentioned_by_agency[agency_id] -> count of those where NO chunk
    #   corroborates the stamp
    documents_by_agency: dict[str, int] = {}
    unmentioned_by_agency: dict[str, int] = {}
    total_unmentioned = 0

    for doc_id, stamps in stamps_by_doc.items():
        # Whole-document text, joined once per document -- corroboration is
        # per DOCUMENT over ALL its chunks, never per chunk (see module
        # docstring: a per-chunk check flags a correct document's own
        # boilerplate page and can never reach zero).
        text = "\n".join(chunks_by_doc.get(doc_id, []))

        for agency_id in stamps:
            name = agency_names.get(agency_id)
            if not name:
                # Not in the catalog handed to us -- nothing to corroborate
                # against, so this stamp contributes to no agency's count.
                continue

            documents_by_agency[agency_id] = documents_by_agency.get(agency_id, 0) + 1

            if not mentions(text, name):
                unmentioned_by_agency[agency_id] = (
                    unmentioned_by_agency.get(agency_id, 0) + 1
                )
                total_unmentioned += 1

    per_agency = {
        agency_id: AgencyError(
            documents=count,
            unmentioned=unmentioned_by_agency.get(agency_id, 0),
        )
        # An agency with zero documents is OMITTED entirely, not recorded at
        # rate 0/0 -- "no error observed" and "nothing to observe" are
        # different facts and conflating them would let a fix's report claim
        # a clean rate for an agency it never touched.
        for agency_id, count in documents_by_agency.items()
    }

    return LabelAudit(per_agency=per_agency, total_unmentioned=total_unmentioned)


def simulate(
    *,
    rows: Iterable[Mapping[str, Any]],
    agency_names: Mapping[str, str],
    resolver: Resolver,
) -> dict[str, list[str]]:
    """Report what a candidate `resolver` WOULD label each chunk, writing
    nothing -- to either the corpus or the `rows` passed in.

    Calibration must be free and reversible: this is what lets Task 3 (or
    anyone) compare a candidate matcher against the shipped one, and feed
    the result straight into `audit_labels`, without a single row of
    `budget_chunks` ever being touched. `agency_names` is accepted (rather
    than left for the resolver to import) so a resolver can be a pure
    function of its inputs too, and so this signature mirrors the shape
    `audit_labels` expects its own corroboration rule to take.
    """
    result: dict[str, list[str]] = {}
    for row in rows:
        # Pass a COPY of the row's own fields as keywords -- the resolver
        # must not be handed the live row object, and nothing here writes
        # back into `row` or `rows` afterward. `agency_names` rides along so
        # a resolver can look up display names without a second corpus read.
        kwargs = dict(row)
        kwargs["agency_names"] = agency_names
        chunk_id = kwargs["chunk_id"]
        result[chunk_id] = list(resolver(**kwargs))
    return result


def load_live(data_dir: Any = None) -> LabelAudit:
    """Assemble the arguments from the real corpus and run `audit_labels`
    with the shipped corroboration rule. Not unit-tested -- this is I/O; the
    pure function it feeds is what the tests drive.

    `scan` never requests the `vector` column: this module only reads for
    auditing, never writes, so it has no use for the 768-float embedding,
    and pulling it across all 83,016 rows costs minutes for nothing.
    """
    from collections import defaultdict

    from chunking.agency_catalog import id_to_name
    from identity.validator import mentions_agency
    from store.chunk_store import ChunkStore

    store = ChunkStore()
    chunks_by_doc: dict[str, list[str]] = defaultdict(list)
    stamps_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in store.scan(
        "budget_chunks", ["doc_id", "text", "agency_canonical_ids"]
    ):
        chunks_by_doc[row["doc_id"]].append(row.get("text") or "")
        for agency_id in row.get("agency_canonical_ids") or []:
            stamps_by_doc[row["doc_id"]].add(agency_id)

    return audit_labels(
        chunks_by_doc=chunks_by_doc,
        stamps_by_doc=stamps_by_doc,
        agency_names=id_to_name(),
        mentions=mentions_agency,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: run the live audit and print/write the per-agency error rates.

    Usage: uv run python -m identity.label_audit [--json PATH]
    """
    import argparse
    import json as _json
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    audit = load_live()
    payload = audit.as_dict()

    print(f"total_unmentioned: {payload['total_unmentioned']}")
    for agency_id, err in sorted(
        payload["per_agency"].items(), key=lambda kv: -kv[1]["unmentioned"]
    ):
        print(
            f"  {agency_id}: {err['unmentioned']}/{err['documents']} "
            f"({err['rate']:.1%})"
        )

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.json.with_suffix(args.json.suffix + ".tmp")
        tmp.write_text(_json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(args.json)
        print(f"written to {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
