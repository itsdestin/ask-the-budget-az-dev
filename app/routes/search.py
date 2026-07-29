"""Placeholder search router — real /api/search lands in Task 4.

Exists now only so app.main's import resolves; an empty APIRouter adds
no routes, so the SPA catch-all still owns every path.
"""
from fastapi import APIRouter

router = APIRouter()
