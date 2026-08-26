"""People: who is running this process, and the shared roster of everyone
who has opened the app (spec 2026-08-25-central-user-roster-design.md).

`whoami.py` is a LEAF — stdlib only — so `ingest/` can import it without
importing `app/` (the dependency runs app → ingest; reversing it would be
circular). `registry.py` reads and writes files and must never be admitted
to the harness import allowlist wholesale (Invariant 7).
"""
