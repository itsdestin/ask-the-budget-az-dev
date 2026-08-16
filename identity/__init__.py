"""Document and agency identity — one validator, one composer, one resolver.

Spec: docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md

Deliberately import-free: several tasks under this package are implemented
concurrently by independent agents in the same worktree, each owning its own
submodule. A re-export here (`from identity.validator import ...`) would put
every one of those agents' commits on this one file and turn a set of
disjoint edits into constant merge conflicts. Import from the submodule you
need directly, e.g. `from identity.validator import validate_name`. Do not
"helpfully" add re-exports back — that is the mistake this comment exists to
prevent.
"""
