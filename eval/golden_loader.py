"""
eval/golden_loader.py
----------------------------------
Dynamically loads and validates golden-set files at runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GoldenEntry:
    id: str
    level: str
    question: str
    answer: str
    metadata: dict[str, Any]
    expected_chunk_id: str | None = None
    contains_exact_token: bool | None = None
    is_negative_case: bool = False
    expected_behavior: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GoldenEntry:
        meta = d.get("metadata", {})
        return cls(
            id=d["id"],
            level=d["level"],
            question=d["question"],
            answer=d["answer"],
            metadata=meta,
            expected_chunk_id=d.get("expected_chunk_id"),
            contains_exact_token=d.get("contains_exact_token"),
            is_negative_case=meta.get("is_negative_case", False),
            expected_behavior=meta.get("expected_behavior"),
        )


@dataclass
class GoldenSet:
    level: str
    entries: list[GoldenEntry] = field(default_factory=list)


def load_golden_set(file_path: Path) -> GoldenSet:
    """Load a single golden-set JSON file and validate its structure."""
    if not file_path.exists():
        raise FileNotFoundError(f"Golden set file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError(f"Golden set must be a JSON array, got {type(raw).__name__}")

    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"Each entry must be a dict, got {type(item).__name__}")
        for required_key in ("id", "level", "question", "answer"):
            if required_key not in item:
                raise ValueError(f"Missing required key '{required_key}' in entry: {item.get('id', '?')}")
        entries.append(GoldenEntry.from_dict(item))

    level = entries[0].level if entries else "Unknown"
    return GoldenSet(level=level, entries=entries)


def load_all_golden_sets(golden_dir: Path) -> dict[str, GoldenSet]:
    """Load all three golden-set files from the given directory."""
    sets = {}
    for filename in ("gs_easy.json", "gs_medium.json", "gs_hard.json"):
        file_path = golden_dir / filename
        gs = load_golden_set(file_path)
        sets[filename] = gs
    return sets


def get_all_entries(sets: dict[str, GoldenSet]) -> list[GoldenEntry]:
    """Flatten all golden-set entries into a single list."""
    entries = []
    for gs in sets.values():
        entries.extend(gs.entries)
    return entries