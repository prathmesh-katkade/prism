"""Verified Base Model Trust Registry.

``atlas_candidate_trust`` verifies *trained* Foundry output: it requires a
real adapter workspace on disk with at least one ``.safetensors``/``.bin``
weight file. That is the right model for a candidate this project actually
trained. It is the wrong model for a legitimate, untouched, off-the-shelf
model -- rejecting one for having no adapter path would be correct behavior
being applied to the wrong kind of candidate, not a bug to route around by
faking a training job, recipe, dataset, or adapter path.

This module is the parallel trust path for that second, equally legitimate
kind of candidate: ``AtlasVerifiedBaseModelCandidate``
(``AtlasCandidateKind.VERIFIED_BASE_MODEL``). It never invents Foundry
provenance and never trusts a client-supplied ``VERIFIED`` flag -- the
server itself probes the live local Ollama daemon for the model's exact
digest and manifest before a verification record can read VERIFIED.

Both candidate kinds converge on exactly the same downstream machinery:
``atlas_candidate_runtime`` (runtime binding, keyed by the same opaque
``candidate_id`` string regardless of kind), ``atlas_bench_live``
(candidate AtlasBench evaluation), and ``atlas_promotion``/
``atlas_foundry_routes`` (promotion decision, production pointer, rollback).
There is no second promotion system here -- only a second, honest way for a
candidate_id to earn the same trust gate.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from prism_api_contracts import (
    AtlasBaseModelVerification,
    AtlasCandidateKind,
    AtlasCandidateVerificationState,
    AtlasVerifiedBaseModelCandidate,
)
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .atlas_event_identity import ordered_event_id
from .durable_registry import history_database_url

# Conservative allowlist of permissive open-weight licenses this project has
# actually reviewed. An allowlist, not a denylist: an unrecognized license
# string fails closed rather than being trusted by default. Extend this only
# after reviewing a new license's terms, never merely because a model the
# team wants happens to use it.
APPROVED_MODEL_LICENSES: frozenset[str] = frozenset({"Apache-2.0", "MIT", "BSD-3-Clause"})

_HUGGING_FACE_PREFIX = "https://huggingface.co/"


def _verification_id() -> str:
    """Lexically time-ordered append-only verification identity.

    Mirrors ``atlas_candidate_trust._verification_id``: database timestamps
    can tie under rapid writes, so the identifier itself carries a
    nanosecond ordering tie-breaker rather than letting ``latest`` resolve
    nondeterministically.
    """
    return ordered_event_id("basemodelverify")


def compute_base_model_candidate_id(
    *, upstream_model_id: str, upstream_revision: str, runtime_model: str
) -> str:
    """Deterministic candidate_id so re-declaring the same real model
    identity is idempotent rather than accumulating duplicate rows -- and so
    it can never collide with a Foundry-trained ``candidate_foundryjob_*``
    id sharing the same runtime binding / promotion tables.
    """
    identity = f"{upstream_model_id}:{upstream_revision}:{runtime_model}"
    return f"basemodel_{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


def probe_live_ollama_digest(runtime_model: str) -> Optional[str]:
    """Query the local Ollama daemon's ``/api/tags`` for this exact model.

    Returns ``None`` if Ollama is unreachable or the model is not present --
    verification fails closed in that case rather than trusting a client's
    declared digest. Mirrors ``atlas_bench_live.AtlasProviderBenchSubject.
    _probe_model_digest``.
    """
    base_url = os.environ.get("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    try:
        response = httpx.get(tags_url, timeout=3.0)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        for item in models:
            if not isinstance(item, dict):
                continue
            if runtime_model in {str(item.get("name", "")), str(item.get("model", ""))}:
                digest = str(item.get("digest", "")).strip()
                return digest or None
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    return None


def probe_live_ollama_manifest(runtime_model: str) -> Optional[dict[str, Any]]:
    """Query the local Ollama daemon's ``/api/show`` for this exact model.

    Returns the raw JSON payload (including whatever manifest/detail fields
    the installed Ollama version exposes) or ``None`` if unreachable/absent.
    This is the strongest live manifest inspection the server can do without
    a reference Ollama installation available in this environment; it is not
    a claim that every possible substitution vector is covered.
    """
    base_url = os.environ.get("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    show_url = f"{base_url.rstrip('/')}/api/show"
    try:
        response = httpx.post(show_url, json={"name": runtime_model}, timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def _manifest_digest(manifest: dict[str, Any]) -> Optional[str]:
    """Canonical hash over whatever stable identity fields a live manifest
    exposes. Never invents a digest when the manifest carries none."""
    digest = manifest.get("digest")
    if isinstance(digest, str) and digest.strip():
        return digest.strip()
    details = manifest.get("details")
    if isinstance(details, dict) and details:
        canonical = json.dumps(details, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
    return None


def _fingerprint(
    *,
    upstream_model_id: str,
    upstream_revision: str,
    runtime_model: str,
    live_runtime_digest: str,
    live_manifest_digest: Optional[str],
    quantization: Optional[str],
) -> str:
    canonical = json.dumps(
        {
            "upstream_model_id": upstream_model_id,
            "upstream_revision": upstream_revision,
            "runtime_model": runtime_model,
            "live_runtime_digest": live_runtime_digest,
            "live_manifest_digest": live_manifest_digest,
            "quantization": quantization,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _rejected(
    candidate: AtlasVerifiedBaseModelCandidate,
    reason: str,
    *,
    live_runtime_digest: Optional[str] = None,
    live_manifest_digest: Optional[str] = None,
) -> AtlasBaseModelVerification:
    now = datetime.now(timezone.utc)
    return AtlasBaseModelVerification(
        verification_id=_verification_id(),
        candidate_id=candidate.candidate_id,
        upstream_model_id=candidate.upstream_model_id,
        upstream_revision=candidate.upstream_revision,
        license=candidate.license,
        runtime_model=candidate.runtime_model,
        live_runtime_digest=live_runtime_digest,
        live_manifest_digest=live_manifest_digest,
        aggregate_candidate_fingerprint=None,
        verification_state=AtlasCandidateVerificationState.REJECTED,
        verification_failure_reason=reason[:1_000],
        created_at=now,
        verified_at=None,
    )


def verify_base_model_candidate(
    candidate: AtlasVerifiedBaseModelCandidate,
    *,
    resolve_live_digest: Callable[[str], Optional[str]] = probe_live_ollama_digest,
    resolve_manifest: Callable[[str], Optional[dict[str, Any]]] = probe_live_ollama_manifest,
) -> AtlasBaseModelVerification:
    """Real, server-side inspection of a declared off-the-shelf model.

    Never trusts a client-supplied digest, manifest, or ``VERIFIED`` claim:
    every fact this function relies on either comes from the live Ollama
    daemon (via the injectable probes, real HTTP calls by default) or is a
    cheap, deterministic consistency check on the candidate's own declared
    fields (license allowlist, official-source/model-id agreement).

    Does not perform a live fetch of the upstream registry (e.g. an actual
    HTTPS request to huggingface.co) -- that would make verification depend
    on third-party network reachability and content, which conflicts with
    deterministic, fail-closed, offline-testable verification. It instead
    checks that the *declared* official source is the canonical Hugging Face
    URL for the *declared* model id, which catches a copy-paste/typo
    mismatch, not a claim that the page was actually fetched.
    """
    if candidate.candidate_kind is not AtlasCandidateKind.VERIFIED_BASE_MODEL:
        return _rejected(candidate, f"candidate_kind must be verified_base_model, got {candidate.candidate_kind!r}")
    if candidate.license not in APPROVED_MODEL_LICENSES:
        return _rejected(
            candidate,
            f"license {candidate.license!r} is not on the approved allowlist {sorted(APPROVED_MODEL_LICENSES)!r}",
        )
    expected_source = _HUGGING_FACE_PREFIX + candidate.upstream_model_id
    if candidate.official_source.rstrip("/") != expected_source.rstrip("/"):
        return _rejected(
            candidate,
            f"official_source {candidate.official_source!r} does not match the canonical source for "
            f"upstream_model_id {candidate.upstream_model_id!r} ({expected_source!r})",
        )

    live_runtime_digest = resolve_live_digest(candidate.runtime_model)
    if live_runtime_digest is None:
        return _rejected(
            candidate,
            f"local Ollama model {candidate.runtime_model!r} was not found or the daemon was unreachable; "
            "refusing to trust a client-declared digest with no live confirmation",
        )
    if live_runtime_digest != candidate.declared_runtime_digest:
        return _rejected(
            candidate,
            f"declared runtime digest {candidate.declared_runtime_digest!r} does not match the live Ollama "
            f"digest {live_runtime_digest!r} -- possible identity substitution",
            live_runtime_digest=live_runtime_digest,
        )

    manifest = resolve_manifest(candidate.runtime_model)
    if manifest is None:
        return _rejected(
            candidate,
            f"could not retrieve a live manifest for {candidate.runtime_model!r} from the local Ollama daemon",
            live_runtime_digest=live_runtime_digest,
        )
    live_manifest_digest = _manifest_digest(manifest)
    if (
        candidate.declared_manifest_digest is not None
        and live_manifest_digest is not None
        and candidate.declared_manifest_digest != live_manifest_digest
    ):
        return _rejected(
            candidate,
            f"declared manifest digest {candidate.declared_manifest_digest!r} does not match the live "
            f"manifest digest {live_manifest_digest!r}",
            live_runtime_digest=live_runtime_digest,
            live_manifest_digest=live_manifest_digest,
        )

    now = datetime.now(timezone.utc)
    return AtlasBaseModelVerification(
        verification_id=_verification_id(),
        candidate_id=candidate.candidate_id,
        upstream_model_id=candidate.upstream_model_id,
        upstream_revision=candidate.upstream_revision,
        license=candidate.license,
        runtime_model=candidate.runtime_model,
        live_runtime_digest=live_runtime_digest,
        live_manifest_digest=live_manifest_digest,
        aggregate_candidate_fingerprint=_fingerprint(
            upstream_model_id=candidate.upstream_model_id,
            upstream_revision=candidate.upstream_revision,
            runtime_model=candidate.runtime_model,
            live_runtime_digest=live_runtime_digest,
            live_manifest_digest=live_manifest_digest,
            quantization=candidate.quantization,
        ),
        verification_state=AtlasCandidateVerificationState.VERIFIED,
        verification_failure_reason=None,
        created_at=now,
        verified_at=now,
    )


# --- durable, append-only persistence ---------------------------------------

_metadata = MetaData()
_base_model_candidates = Table(
    "prism_atlas_verified_base_model_candidates",
    _metadata,
    Column("candidate_id", String(120), primary_key=True),
    Column("upstream_model_id", String(300), nullable=False),
    Column("upstream_revision", String(200), nullable=False),
    Column("license", String(100), nullable=False),
    Column("official_source", String(2_000), nullable=False),
    Column("runtime_model", String(300), nullable=False),
    Column("declared_runtime_digest", String(200), nullable=False),
    Column("quantization", String(64), nullable=True),
    Column("declared_manifest_digest", String(200), nullable=True),
    Column("declared_blob_digests_payload", Text, nullable=False),
    Column("parameter_count", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)
_base_model_verifications = Table(
    "prism_atlas_base_model_verifications",
    _metadata,
    Column("verification_id", String(120), primary_key=True),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasVerifiedBaseModelRegistry:
    """Append-only registry of declared off-the-shelf base-model candidates.

    Registering never verifies anything -- it only durably records the
    candidate's declared identity, exactly as ``DurableAtlasCandidateRegistry``
    records a trained candidate's declared job/recipe/adapter identity.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def register(self, candidate: AtlasVerifiedBaseModelCandidate) -> AtlasVerifiedBaseModelCandidate:
        existing = self.get(candidate.candidate_id)
        if existing is not None:
            return existing  # idempotent: declaring the same identity twice is a no-op
        with self.engine.begin() as connection:
            connection.execute(
                insert(_base_model_candidates).values(
                    candidate_id=candidate.candidate_id,
                    upstream_model_id=candidate.upstream_model_id,
                    upstream_revision=candidate.upstream_revision,
                    license=candidate.license,
                    official_source=candidate.official_source,
                    runtime_model=candidate.runtime_model,
                    declared_runtime_digest=candidate.declared_runtime_digest,
                    quantization=candidate.quantization,
                    declared_manifest_digest=candidate.declared_manifest_digest,
                    declared_blob_digests_payload=json.dumps(candidate.declared_blob_digests, sort_keys=True),
                    parameter_count=candidate.parameter_count,
                    created_at=candidate.created_at,
                )
            )
        return candidate

    @staticmethod
    def _record(row: object) -> AtlasVerifiedBaseModelCandidate:
        return AtlasVerifiedBaseModelCandidate(
            candidate_id=row["candidate_id"],  # type: ignore[index]
            upstream_model_id=row["upstream_model_id"],  # type: ignore[index]
            upstream_revision=row["upstream_revision"],  # type: ignore[index]
            license=row["license"],  # type: ignore[index]
            official_source=row["official_source"],  # type: ignore[index]
            runtime_model=row["runtime_model"],  # type: ignore[index]
            declared_runtime_digest=row["declared_runtime_digest"],  # type: ignore[index]
            quantization=row["quantization"],  # type: ignore[index]
            declared_manifest_digest=row["declared_manifest_digest"],  # type: ignore[index]
            declared_blob_digests=json.loads(row["declared_blob_digests_payload"]),  # type: ignore[index]
            parameter_count=row["parameter_count"],  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
        )

    def get(self, candidate_id: str) -> Optional[AtlasVerifiedBaseModelCandidate]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(_base_model_candidates).where(_base_model_candidates.c.candidate_id == candidate_id)
                )
                .mappings()
                .first()
            )
        return None if row is None else self._record(row)

    def list(self, *, limit: int = 100) -> list[AtlasVerifiedBaseModelCandidate]:
        statement = select(_base_model_candidates).order_by(_base_model_candidates.c.created_at.desc()).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record(row) for row in rows]


class DurableAtlasBaseModelVerificationStore:
    """Append-only verification history -- never edited, only added to."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def save(self, verification: AtlasBaseModelVerification) -> AtlasBaseModelVerification:
        with self.engine.begin() as connection:
            connection.execute(
                insert(_base_model_verifications).values(
                    verification_id=verification.verification_id,
                    candidate_id=verification.candidate_id,
                    payload=json.dumps(verification.model_dump(mode="json"), sort_keys=True),
                    created_at=verification.created_at,
                )
            )
        return verification

    def latest(self, candidate_id: str) -> Optional[AtlasBaseModelVerification]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(_base_model_verifications.c.payload)
                .where(_base_model_verifications.c.candidate_id == candidate_id)
                .order_by(
                    _base_model_verifications.c.created_at.desc(),
                    _base_model_verifications.c.verification_id.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
        return None if row is None else AtlasBaseModelVerification.model_validate(json.loads(row))

    def history(self, candidate_id: str, *, limit: int = 50) -> list[AtlasBaseModelVerification]:
        statement = (
            select(_base_model_verifications.c.payload)
            .where(_base_model_verifications.c.candidate_id == candidate_id)
            .order_by(
                _base_model_verifications.c.created_at.desc(),
                _base_model_verifications.c.verification_id.desc(),
            )
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).scalars().all()
        return [AtlasBaseModelVerification.model_validate(json.loads(row)) for row in rows]


def is_base_model_verified(store: DurableAtlasBaseModelVerificationStore, candidate_id: str) -> bool:
    """True only if the candidate's *latest* verification is VERIFIED.

    Mirrors ``atlas_candidate_trust.is_verified``: a REJECTED verification
    never becomes VERIFIED by being superseded with nothing -- a genuinely
    fixed declaration needs a fresh, real ``verify_base_model_candidate``
    call that itself passes and becomes the new latest record.
    """
    latest = store.latest(candidate_id)
    return (
        latest is not None and latest.verification_state is AtlasCandidateVerificationState.VERIFIED
    )
