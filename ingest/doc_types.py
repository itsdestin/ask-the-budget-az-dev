"""The document-type registry: loader for `data/document-types.yaml`.

WHY a data file rather than a dict in Python: the office that runs this app
has no maintainer. Adding a document type must be an edit to a readable file,
not a code change, a rebuild and a redeploy.

WHY a malformed file RAISES instead of falling back to defaults (unlike
harness/settings.py, which degrades): settings.json is written by an admin at
runtime and a bad one should not stop the app. This file ships in the repo, so
a parse failure means the build is broken -- and an app that has silently
forgotten how to route documents is worse than one that will not start.

The mtime cache mirrors harness/settings.py's (path, mtime, size) stamp so an
edited registry is picked up without a restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "document-types.yaml"


@dataclass(frozen=True)
class DocType:
    key: str
    label: str
    group: str
    order: int
    formats: tuple[str, ...]
    extractors: dict[str, str]
    publisher: str | None
    one_per_year: bool
    where_published: str
    which_file: str
    upload_row: bool = False
    stage_field: bool = False
    redirect: dict[str, str] | None = None


_cache: tuple[DocType, ...] | None = None
_stamp: tuple[str, float, int] | None = None


def reset_cache() -> None:
    """Drop the cache. Tests that write their own registry call this."""
    global _cache, _stamp
    _cache, _stamp = None, None


def _load(path: Path | None = None) -> tuple[DocType, ...]:
    global _cache, _stamp
    target = path or REGISTRY_PATH
    st = target.stat()
    stamp = (str(target), st.st_mtime, st.st_size)
    if stamp == _stamp and _cache is not None:
        return _cache

    raw: Any = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        raise ValueError(f"{target} must be a mapping with a 'types' list.")

    rows = []
    for entry in raw["types"]:
        rows.append(DocType(
            key=entry["key"],
            label=entry["label"],
            group=entry["group"],
            order=int(entry["order"]),
            formats=tuple(entry["formats"]),
            extractors=dict(entry.get("extractors") or {}),
            publisher=entry.get("publisher"),
            one_per_year=bool(entry["one_per_year"]),
            where_published=entry.get("where_published", ""),
            which_file=entry.get("which_file", ""),
            upload_row=bool(entry.get("upload_row", False)),
            stage_field=bool(entry.get("stage_field", False)),
            redirect=entry.get("redirect"),
        ))

    keys = [r.key for r in rows]
    if len(keys) != len(set(keys)):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        raise ValueError(f"{target} has duplicate keys: {dupes}")

    _cache = tuple(sorted(rows, key=lambda r: r.order))
    _stamp = stamp
    return _cache


def all_types(path: Path | None = None) -> list[DocType]:
    return list(_load(path))


def get(key: str, path: Path | None = None) -> DocType | None:
    for row in _load(path):
        if row.key == key:
            return row
    return None


def extractor_for(key: str, fmt: str, path: Path | None = None) -> str | None:
    """`fmt` is dotted, e.g. '.pdf'."""
    row = get(key, path)
    return None if row is None else row.extractors.get(fmt)


def upload_rows(path: Path | None = None) -> list[DocType]:
    return [r for r in _load(path) if r.upload_row]


def is_one_per_year(key: str, path: Path | None = None) -> bool:
    """Unknown types default to False -- the SAFE direction.

    A wrong `True` silently overwrites documents; a wrong `False` produces a
    longer id. Only one of those loses data.
    """
    row = get(key, path)
    return bool(row and row.one_per_year)
