"""Stable AtlasBench presentation order, separate from the frozen corpus."""

from __future__ import annotations

import hashlib
from typing import Optional

DEFAULT_SHUFFLE_SEED = "atlasbench-shuffle-v1"


def choice_permutation(task_id: str, choice_count: int, shuffle_seed: Optional[str]) -> tuple[int, ...]:
    """Map each presented position to its original corpus choice index."""
    if choice_count < 2:
        raise ValueError(f"{task_id}: at least two choices are required")
    if shuffle_seed is None:
        return tuple(range(choice_count))
    return tuple(sorted(
        range(choice_count),
        key=lambda index: hashlib.sha256(f"{shuffle_seed}:{task_id}:{index}".encode()).digest(),
    ))
