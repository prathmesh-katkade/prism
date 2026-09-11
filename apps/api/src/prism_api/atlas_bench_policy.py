"""Immutable evaluation-policy identity for AtlasBench live-provider runs.

The physical Phase 10 Arena tournament exposed a real comparability failure:
an unset (model-default) Ollama context window allocated roughly 9.35 GB and
drove system RAM to 95%, while the trusted tournament that actually produced
comparable evidence used an explicit ``PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS
=4096``. A raw pass/fail score does not carry that difference -- two runs
that used materially different inference policies could otherwise be
compared as if they were equivalent, silently corrupting a promotion
decision. This module gives every live-provider run a deterministic identity
over exactly the settings that make two runs comparable, so a promotion
decision can fail closed on a mismatch instead of assuming one.

An unset/ambiguous setting -- most importantly a context window the operator
never pinned -- never receives a policy id at all (see
``atlas_bench_live.AtlasProviderBenchSubject.evaluation_policy_id``). Such a
run is legacy/unqualified evidence, not a policy that could coincidentally
compare equal to another ambiguous run just because both are ``None``.
"""

from __future__ import annotations

import hashlib
import json

EVALUATION_POLICY_VERSION = "atlasbench-eval-policy-v1"


def compute_evaluation_policy_id(
    *,
    prompt_schema_version: str,
    temperature: float,
    num_predict: int,
    context_tokens: int,
    timeout_seconds: float,
    provider: str,
    corpus_version: str,
    corpus_hash_value: str,
) -> str:
    """Deterministic sha256 identity over one exact, comparable-run policy.

    ``context_tokens`` is a required ``int`` here, deliberately not
    ``Optional``: a caller that has not decided on an explicit context
    window must not compute an id at all rather than pass ``None`` through
    to a hash that would make two different ambiguous runs look identical.
    Including ``corpus_version``/``corpus_hash_value`` means a policy id
    also changes if the underlying corpus changes, even if every inference
    setting stayed the same -- defense in depth alongside the promotion
    route's separate, explicit corpus-identity check.
    """
    canonical = json.dumps(
        {
            "policy_version": EVALUATION_POLICY_VERSION,
            "prompt_schema_version": prompt_schema_version,
            "temperature": temperature,
            "num_predict": num_predict,
            "context_tokens": context_tokens,
            "timeout_seconds": timeout_seconds,
            "provider": provider,
            "corpus_version": corpus_version,
            "corpus_hash": corpus_hash_value,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
