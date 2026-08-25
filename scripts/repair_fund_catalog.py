"""Repair data/fund-catalog.yaml in place — the 2026-08-23 fund-identity pass.

Spec: docs/superpowers/specs/2026-08-23-fund-identity-repair-design.md.
Every rename below carries its measured evidence there; do not add rows
without measuring. Run from the repo root:

    uv run python scripts/repair_fund_catalog.py            # prints the plan
    uv run python scripts/repair_fund_catalog.py --apply    # rewrites the YAML

ORDER MATTERS (review amendment 3): renames run BEFORE the delete rule, or
the rule deletes the truncated Game & Fish entry it is about to repair.

The delete rule is `funds.names._looks_like_a_fund_name` — the same
allowlist the display path uses — so the catalog and the display can never
disagree about what a fund name is. Two ids are hand-pinned for deletion
because no shape rule can reach them (amendment 1): `fund:block-grant`
(two words with a "grant" tail PASSES the allowlist, but the fragment is a
severed tail that stamped 1,299 chunks across 93 agencies) and
`fund:species` (passes as "Species Fund", but 16 of its 18 chunks print the
full "Game, Non-Game, Fish and Endangered Species Fund" — it is that fund's
tail, not a fund).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from funds.names import _looks_like_a_fund_name  # noqa: E402

CATALOG = Path(__file__).resolve().parent.parent / "data" / "fund-catalog.yaml"

# id -> (new canonical_name, [name_variants to add])
RENAMES: dict[str, tuple[str, list[str]]] = {
    "fund:nursing-care-institution-resident-protection":
        ("Nursing Care Institution Resident Protection Revolving Fund", []),
    "fund:department-of-education-empowerment":
        ("Department of Education Empowerment Scholarship Account", []),
    "fund:nursing-care-institution-administrators-licensing-and-assisted-living-facility":
        ("Nursing Care Institution Administrators' Licensing and Assisted "
         "Living Facility Managers' Certification Fund", []),
    "fund:board-for-private-postsecondary-education":
        ("Board for Private Postsecondary Education Fund", []),
    "fund:special-employee-health-insurance":
        ("Special Employee Health Insurance Trust Fund", []),
    "fund:environmental-laboratory-licensure":
        ("Environmental Laboratory Licensure Revolving Fund", []),
    "fund:board-of-osteopathic-examiners-in-medicine":
        ("Board of Osteopathic Examiners in Medicine and Surgery Fund", []),
    "fund:child-support-enforcement-administration":
        ("Child Support Enforcement Administration Fund",
         ["Child Support Enforcement Administration (CSEA) Fund"]),
    "fund:giitem-border-security-and-law":
        ("GIITEM Border Security and Law Enforcement Subaccount", []),
    "fund:court-appointed-special-advocate-and":
        ("Court Appointed Special Advocate and Vulnerable Persons Fund", []),
    "fund:investment-management-regulatory-and":
        ("Investment Management Regulatory and Enforcement Fund", []),
    "fund:children-and-family-services-training":
        ("Children and Family Services Training Program Fund", []),
    "fund:state-charitable-penal-and-reformatory":
        ("State Charitable, Penal and Reformatory Institutions Land Fund", []),
    "fund:motor-vehicle-liability-insurance":
        ("Motor Vehicle Liability Insurance Enforcement Fund", []),
    # Amendment 5: current books print the bare form 62:24; the Board form
    # is a full name (not a truncated prefix) so it is safe as a variant.
    "fund:barbering-and-cosmetology-board":
        ("Barbering and Cosmetology Fund", ["Barbering and Cosmetology Board Fund"]),
    "fund:federal-temporary-assistance-for-needy":
        ("Federal Temporary Assistance for Needy Families Block Grant",
         ["Federal Temporary Assistance for Needy Families (TANF) Block Grant"]),
    # The statutory name; the hyphenated form is what JLBC's books print.
    "fund:game-nongame-fish-and-endangered":
        ("Game, Nongame, Fish and Endangered Species Fund",
         ["Game, Non-Game, Fish and Endangered Species Fund"]),
}

PINNED_DELETES = {"fund:block-grant", "fund:species"}


def plan(raw: dict) -> tuple[list[dict], list[dict], list[str]]:
    funds = raw.get("funds") or []
    by_id = {f["canonical_id"]: f for f in funds}
    missing = [i for i in RENAMES if i not in by_id]
    if missing:
        raise SystemExit(f"rename target(s) not in catalog: {missing}")

    for fid, (name, variants) in RENAMES.items():
        entry = by_id[fid]
        entry["canonical_name"] = name
        if variants:
            existing = list(entry.get("name_variants") or [])
            entry["name_variants"] = existing + [v for v in variants if v not in existing]

    kept, deleted = [], []
    for f in funds:
        fid = f["canonical_id"]
        if fid in PINNED_DELETES or not _looks_like_a_fund_name(f["canonical_name"]):
            deleted.append(f)
        else:
            kept.append(f)
    return kept, deleted, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="rewrite the catalog")
    args = ap.parse_args(argv)

    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    before = len(raw["funds"])
    kept, deleted, _ = plan(raw)

    print(f"catalog entries: {before} -> {len(kept)} kept, {len(deleted)} deleted")
    print(f"renamed: {len(RENAMES)}")
    print("DELETE list (read every line before --apply):")
    for f in deleted:
        why = "pinned" if f["canonical_id"] in PINNED_DELETES else "fails fund-name shape"
        print(f"  {f['canonical_id']:60s} {f['canonical_name']!r}  [{why}]")
    if not args.apply:
        print("\n(dry run — pass --apply to rewrite data/fund-catalog.yaml)")
        return 0

    raw["funds"] = kept
    raw["_meta"]["unique_funds"] = len(kept)
    raw["_meta"]["repaired"] = (
        "2026-08-23: 17 truncated names restored from corpus evidence and "
        f"{len(deleted)} non-fund rows (schedule totals, agency names, budget "
        "adjustment lines, severed fragments) removed. See "
        "docs/superpowers/specs/2026-08-23-fund-identity-repair-design.md. "
        "Regenerating from source PDFs with scripts/build_fund_catalog.py "
        "would LOSE the renames — merge this file's renames back in first."
    )
    CATALOG.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    print(f"\nwrote {CATALOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
