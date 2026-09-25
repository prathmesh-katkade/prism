# ADR 0016: AtlasBench choice order and string answers

Status: Accepted, 2026-09-25

## Context

The frozen AtlasBench V1 corpus has 90 items. Correct answers occur at authored
indices 0, 1, 2, and 3 respectively 8, 81, 1, and 0 times. A subject that
ignores every question and always selects index 1 therefore scores 81/90. The
old arena rounds rewarded this positional bias and cannot be compared to runs
under this policy.

## Decision

The corpus content and hash stay unchanged. The trusted runner computes a
per-task choice permutation by sorting each original index by a SHA-256 digest
of the shuffle seed, task ID, and index. It presents choices in that order,
then maps the selected presented position to the original corpus index before
scoring. The default seed is `atlasbench-shuffle-v1`; the seed is included in
the evaluation policy ID and the run record, and the permutation is stored for
each task result. A null seed is permitted only for explicit historical
controls.

The Ollama subject requests one exact choice string under a decoder JSON
Schema enum built from the presented choices. It maps the returned string to
the presented index. Duplicate choice text, including collisions after the
request length limit, aborts the task with its ID instead of guessing.
Non-model constant-position subjects remain test controls and have no
candidate registration or promotion path.

## Evidence and consequences

Under the unchanged V1 corpus hash, the shuffled correct-position counts are
23, 24, 20, and 23. A constant index-1 subject scores 81/90 unshuffled and
24/90 shuffled. Old policy IDs differ from the new version, preventing
accidental run comparison. The authored 81/90 skew remains a corpus defect;
rebalance it only in a separately versioned corpus with a full new baseline.
