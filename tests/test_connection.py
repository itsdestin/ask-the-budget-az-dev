"""Phase 1b WS1, Task 1.3 connection round-trip test.

Skips the test suite when DATABASE_URL is unset OR the database is
unreachable. The Docker compose stack must be up + migrations applied
for these tests to run; CI will need that wiring before this lands on
master.
"""

from __future__ import annotations

import os

import pytest

# Attempt the import lazily so test collection works when psycopg isn't installed
# yet (e.g. someone running a different test file before `uv sync`).
psycopg = pytest.importorskip("psycopg")

from db.connection import close_pool, get_connection


def _has_database() -> bool:
    """True when DATABASE_URL is set AND the DB is reachable on a 1s timeout."""
    if not os.environ.get("DATABASE_URL"):
        return False
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=1):
            return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _has_database(),
    reason="DATABASE_URL unset or local Postgres not running. Start with `cd db && docker compose up -d`.",
)


@pytest.fixture(autouse=True)
def _reset_pool_between_tests():
    yield
    close_pool()


@needs_db
def test_connection_round_trip():
    with get_connection() as conn:
        result = conn.execute("SELECT 1 AS x").fetchone()
        assert result is not None
        assert result["x"] == 1


@needs_db
def test_extensions_present():
    """Sanity check: 0001_initial_schema.sql installed vector + pg_search."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_search', 'pgcrypto')"
        ).fetchall()
        names = {r["extname"] for r in rows}
        assert {"vector", "pg_search", "pgcrypto"}.issubset(names), (
            f"Expected vector + pg_search + pgcrypto, got {names}. "
            "Did you apply db/migrations/0001_initial_schema.sql?"
        )


@needs_db
def test_seed_catalogs_loaded():
    """0003_seed_catalogs.sql populates ~157 agencies and ~227 funds."""
    with get_connection() as conn:
        agency_count = conn.execute("SELECT COUNT(*)::INT AS n FROM agencies").fetchone()
        fund_count = conn.execute("SELECT COUNT(*)::INT AS n FROM funds").fetchone()
        assert agency_count is not None
        assert fund_count is not None
        # Pin to current catalog sizes; bump these if the YAMLs grow.
        assert agency_count["n"] == 157, f"agencies count drifted: {agency_count['n']}"
        assert fund_count["n"] == 227, f"funds count drifted: {fund_count['n']}"


@needs_db
def test_known_agency_present():
    """Spot-check: ADC (Department of Corrections) is in the seeded catalog."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT canonical_name FROM agencies WHERE agency_id = 'agency:adc'"
        ).fetchone()
        assert row is not None
        assert "Corrections" in row["canonical_name"]


@needs_db
def test_known_fund_present():
    """Spot-check: AHCCCS Fund is in the seeded catalog and tagged as present in s18.

    Note: the spec/plan named 'Aviation Fund' as an example query target, but it
    isn't a separate entry in fund-catalog.yaml — the s18 cross-cut PDF rolls
    aviation-related amounts under fund:advanced-air-mobility and other slugs.
    Pivoting the test to AHCCCS, which IS a distinct fund and a canonical
    cross-cut hit.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT canonical_name, present_in FROM funds WHERE fund_id = 'fund:ahcccs'"
        ).fetchone()
        assert row is not None
        assert "AHCCCS" in row["canonical_name"]
        assert "jlbc-s18" in row["present_in"]
