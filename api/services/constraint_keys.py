"""Canonical constraint-key construction and display parsing."""
from __future__ import annotations


def normalize_constraint_key(constraint_name: str, contingency_name: str) -> str:
    """Return the artifact key for a constraint and contingency pair."""
    return f"{str(constraint_name).strip()}|{str(contingency_name).strip()}"


def split_constraint_key(key: str) -> tuple[str, str | None]:
    """Split a canonical key while preserving a bare constraint name."""
    name, separator, contingency = str(key).partition("|")
    return name, contingency if separator else None
