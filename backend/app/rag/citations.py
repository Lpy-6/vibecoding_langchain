"""
Citation extraction and validation against retrieved source indices.
"""
from __future__ import annotations

import re

_CITE_RE = re.compile(r"\[(\d{1,2})\]")


def extract_used_indices(answer: str, source_count: int) -> list[int]:
    used: list[int] = []
    seen: set[int] = set()
    for match in _CITE_RE.finditer(answer or ""):
        idx = int(match.group(1))
        if 1 <= idx <= source_count and idx not in seen:
            seen.add(idx)
            used.append(idx)
    return sorted(used)


def citation_coverage(answer: str, source_count: int) -> float:
    if source_count <= 0:
        return 0.0
    return len(extract_used_indices(answer, source_count)) / source_count
