from __future__ import annotations

from prism_api import atlas_bench_policy
from prism_api.atlas_bench_live import AtlasProviderBenchSubject
from prism_api.atlas_bench_policy import compute_evaluation_policy_id
from prism_api_contracts import AtlasModelProviderName


def _base_kwargs() -> dict:
    return {
        "prompt_schema_version": "atlasbench-choice-v3-string",
        "temperature": 0,
        "num_predict": 256,
        "context_tokens": 4096,
        "timeout_seconds": 20.0,
        "provider": "ollama",
        "corpus_version": "atlasbench-v1",
        "corpus_hash_value": "a" * 64,
    }


def test_policy_id_is_deterministic() -> None:
    first = compute_evaluation_policy_id(**_base_kwargs())
    second = compute_evaluation_policy_id(**_base_kwargs())
    assert first == second
    assert len(first) == 64


def test_policy_id_changes_when_context_tokens_changes() -> None:
    """This is the exact real-world failure the physical Arena tournament
    hit: an unset ~40,960-token default context nearly exhausted system RAM,
    while the trusted run used 4096. Two different context windows must
    never produce the same policy id."""
    baseline = compute_evaluation_policy_id(**_base_kwargs())
    changed = compute_evaluation_policy_id(**{**_base_kwargs(), "context_tokens": 40_960})
    assert baseline != changed


def test_policy_id_records_the_critical_item_allowance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    baseline = compute_evaluation_policy_id(**_base_kwargs())
    monkeypatch.setattr(atlas_bench_policy, "CRITICAL_REGRESSION_ALLOWANCE_ITEMS", 0)
    assert compute_evaluation_policy_id(**_base_kwargs()) != baseline


def test_policy_id_changes_with_each_material_field() -> None:
    baseline = compute_evaluation_policy_id(**_base_kwargs())
    for field, value in [
        ("temperature", 0.7),
        ("num_predict", 128),
        ("timeout_seconds", 30.0),
        ("provider", "deterministic"),
        ("prompt_schema_version", "atlasbench-choice-v4"),
        ("shuffle_seed", "another-seed"),
        ("shuffle_seed", None),
        ("corpus_version", "atlasbench-v2-holdout-wave1"),
        ("corpus_hash_value", "b" * 64),
    ]:
        variant = compute_evaluation_policy_id(**{**_base_kwargs(), field: value})
        assert variant != baseline, f"expected a different policy id when {field} changes"


def test_subject_pins_default_context_when_env_is_unset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.delenv("PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS", raising=False)
    monkeypatch.setattr(AtlasProviderBenchSubject, "_probe_model_digest", lambda self: "test-digest")

    subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA, model_override="test-model")
    assert subject.context_tokens == 4096
    assert subject.evaluation_policy_id(corpus_version="atlasbench-v1", corpus_hash_value="a" * 64) is not None


def test_subject_has_a_policy_id_when_context_is_pinned(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS", "4096")
    monkeypatch.setattr(AtlasProviderBenchSubject, "_probe_model_digest", lambda self: "test-digest")

    subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA, model_override="test-model")
    policy_id = subject.evaluation_policy_id(corpus_version="atlasbench-v1", corpus_hash_value="a" * 64)
    assert policy_id is not None
    assert len(policy_id) == 64

    # Two subjects (e.g. production and a challenger) under the identical
    # pinned policy must agree exactly -- that agreement is the whole point.
    other = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA, model_override="another-model")
    assert other.evaluation_policy_id(corpus_version="atlasbench-v1", corpus_hash_value="a" * 64) == policy_id
