"""Candidate Artifact Trust Registry.

A registered ``AtlasCandidateArtifact`` (10M-3) records only the fact that a
training job produced *some* adapter output at some path -- it is not
evidence the artifact is intact, unmodified, matches the recipe that
supposedly produced it, or safe to load. This module adds that evidence: a
real inspection pass over the files actually on disk, persisted as a
durable, append-only verification record.

Server-side callers (``compute_promotion_decision``, ``promote_candidate`` in
``atlas_foundry_routes.py``) require the candidate's *latest* verification to
be ``VERIFIED`` before a candidate may enter AtlasBench promotion evaluation
or be promoted -- a client cannot bypass this by skipping a UI step, because
the check lives in the route handler, not a frontend guard.

Verification never silently passes a suspicious artifact and never silently
overwrites a prior verification's evidence: every call to ``verify_candidate``
appends one new record, VERIFIED or REJECTED with a concrete reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from prism_api_contracts import (
    AtlasCandidateArtifact,
    AtlasCandidateArtifactFile,
    AtlasCandidateVerification,
    AtlasCandidateVerificationState,
    AtlasTrainingRecipe,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .durable_registry import history_database_url

# Adapter output is LoRA/QLoRA weights and their small companion metadata --
# never an executable, script, or arbitrary blob. A file outside this list
# fails verification rather than being silently included or silently
# skipped -- an allowlist, not a denylist, so a novel unexpected type is
# rejected by default rather than trusted by default.
_ALLOWED_SUFFIXES = frozenset(
    {".safetensors", ".json", ".bin", ".txt", ".md", ".model", ".vocab", ".yaml", ".yml"}
)
_MAX_FILES = 10_000
_HASH_CHUNK_BYTES = 1024 * 1024


def _recipe_hash(recipe: AtlasTrainingRecipe) -> str:
    canonical = json.dumps(recipe.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(files: list[AtlasCandidateArtifactFile]) -> str:
    canonical = json.dumps(
        sorted([(item.relative_path, item.sha256) for item in files]), sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _rejected(
    *,
    candidate: AtlasCandidateArtifact,
    recipe: AtlasTrainingRecipe,
    reason: str,
    adapter_files: Optional[list[AtlasCandidateArtifactFile]] = None,
) -> AtlasCandidateVerification:
    now = datetime.now(timezone.utc)
    files = adapter_files or []
    return AtlasCandidateVerification(
        verification_id=f"candverify_{uuid.uuid4().hex}",
        candidate_id=candidate.candidate_id,
        training_job_id=candidate.job_id,
        recipe_id=candidate.recipe_id,
        base_model=candidate.base_model,
        dataset_version_id=candidate.dataset_version_id,
        recipe_hash=_recipe_hash(recipe),
        adapter_files=files,
        aggregate_candidate_fingerprint=_fingerprint(files) if files else None,
        verification_state=AtlasCandidateVerificationState.REJECTED,
        verification_failure_reason=reason[:1_000],
        created_at=now,
        verified_at=None,
    )


def verify_candidate(
    candidate: AtlasCandidateArtifact, recipe: AtlasTrainingRecipe
) -> AtlasCandidateVerification:
    """Real, non-mutating inspection of a candidate's adapter workspace.

    Requires ``recipe.recipe_id == candidate.recipe_id`` and
    ``recipe.base_model == candidate.base_model`` and
    ``recipe.dataset_version_id == candidate.dataset_version_id`` -- these
    are the caller's declared cross-checks that the candidate really came
    from the recipe it claims, not a value this function infers.
    """
    if recipe.recipe_id != candidate.recipe_id:
        return _rejected(
            candidate=candidate, recipe=recipe,
            reason=f"recipe mismatch: candidate.recipe_id={candidate.recipe_id!r} != recipe.recipe_id={recipe.recipe_id!r}",
        )
    if recipe.base_model != candidate.base_model:
        return _rejected(
            candidate=candidate, recipe=recipe,
            reason=f"base-model mismatch: candidate.base_model={candidate.base_model!r} != recipe.base_model={recipe.base_model!r}",
        )
    if recipe.dataset_version_id != candidate.dataset_version_id:
        return _rejected(
            candidate=candidate, recipe=recipe,
            reason=(
                f"dataset mismatch: candidate.dataset_version_id={candidate.dataset_version_id!r} "
                f"!= recipe.dataset_version_id={recipe.dataset_version_id!r}"
            ),
        )

    try:
        workspace = Path(candidate.adapter_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return _rejected(candidate=candidate, recipe=recipe, reason=f"adapter path does not exist: {candidate.adapter_path!r}")
    if not workspace.is_dir():
        return _rejected(candidate=candidate, recipe=recipe, reason=f"adapter path is not a directory: {candidate.adapter_path!r}")

    try:
        entries = sorted(workspace.rglob("*"))
    except OSError as error:
        return _rejected(candidate=candidate, recipe=recipe, reason=f"could not list adapter workspace: {error}")

    adapter_files: list[AtlasCandidateArtifactFile] = []
    saw_any_weight_file = False
    for entry in entries:
        if entry.is_dir():
            continue
        if len(adapter_files) >= _MAX_FILES:
            return _rejected(
                candidate=candidate, recipe=recipe, reason=f"adapter workspace has more than {_MAX_FILES} files",
                adapter_files=adapter_files,
            )
        try:
            resolved = entry.resolve(strict=True)
        except (OSError, RuntimeError):
            return _rejected(candidate=candidate, recipe=recipe, reason=f"unreadable adapter file: {entry}", adapter_files=adapter_files)
        # A path-traversal / symlink-escape guard: every real file must stay
        # inside the candidate's own resolved workspace, never anywhere else
        # on disk regardless of what a symlink or ".." component claims.
        if not str(resolved).startswith(str(workspace) + os.sep):
            return _rejected(
                candidate=candidate, recipe=recipe,
                reason=f"adapter file escapes its candidate workspace: {entry}",
                adapter_files=adapter_files,
            )
        if entry.is_symlink():
            return _rejected(
                candidate=candidate, recipe=recipe, reason=f"adapter workspace contains a symlink, which is never trusted: {entry}",
                adapter_files=adapter_files,
            )
        suffix = entry.suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            return _rejected(
                candidate=candidate, recipe=recipe,
                reason=f"adapter workspace contains an unexpected file type {suffix!r}: {entry.relative_to(workspace)}",
                adapter_files=adapter_files,
            )
        if os.access(entry, os.X_OK):
            return _rejected(
                candidate=candidate, recipe=recipe,
                reason=f"adapter workspace contains an executable file: {entry.relative_to(workspace)}",
                adapter_files=adapter_files,
            )
        if suffix in {".safetensors", ".bin"}:
            saw_any_weight_file = True
        stat = entry.stat()
        adapter_files.append(
            AtlasCandidateArtifactFile(
                relative_path=str(entry.relative_to(workspace)),
                sha256=_sha256_file(entry),
                size_bytes=stat.st_size,
                file_type=suffix.lstrip("."),
            )
        )

    if not adapter_files:
        return _rejected(candidate=candidate, recipe=recipe, reason="adapter workspace contains no files")
    if not saw_any_weight_file:
        return _rejected(
            candidate=candidate, recipe=recipe,
            reason="adapter workspace contains no .safetensors/.bin weight file -- metadata alone is not a trained candidate",
            adapter_files=adapter_files,
        )

    now = datetime.now(timezone.utc)
    return AtlasCandidateVerification(
        verification_id=f"candverify_{uuid.uuid4().hex}",
        candidate_id=candidate.candidate_id,
        training_job_id=candidate.job_id,
        recipe_id=candidate.recipe_id,
        base_model=candidate.base_model,
        dataset_version_id=candidate.dataset_version_id,
        recipe_hash=_recipe_hash(recipe),
        adapter_files=adapter_files,
        aggregate_candidate_fingerprint=_fingerprint(adapter_files),
        verification_state=AtlasCandidateVerificationState.VERIFIED,
        verification_failure_reason=None,
        created_at=now,
        verified_at=now,
    )


# --- durable, append-only persistence ---------------------------------------

_metadata = MetaData()
_verifications = Table(
    "prism_atlas_candidate_verifications",
    _metadata,
    Column("verification_id", String(120), primary_key=True),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasCandidateVerificationStore:
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

    def save(self, verification: AtlasCandidateVerification) -> AtlasCandidateVerification:
        with self.engine.begin() as connection:
            connection.execute(
                insert(_verifications).values(
                    verification_id=verification.verification_id,
                    candidate_id=verification.candidate_id,
                    payload=json.dumps(verification.model_dump(mode="json"), sort_keys=True),
                    created_at=verification.created_at,
                )
            )
        return verification

    def latest(self, candidate_id: str) -> Optional[AtlasCandidateVerification]:
        row = (
            self.engine.connect()
            .execute(
                select(_verifications.c.payload)
                .where(_verifications.c.candidate_id == candidate_id)
                .order_by(_verifications.c.created_at.desc())
                .limit(1)
            )
            .scalar_one_or_none()
        )
        return None if row is None else AtlasCandidateVerification.model_validate(json.loads(row))

    def history(self, candidate_id: str, *, limit: int = 50) -> list[AtlasCandidateVerification]:
        statement = (
            select(_verifications.c.payload)
            .where(_verifications.c.candidate_id == candidate_id)
            .order_by(_verifications.c.created_at.desc())
            .limit(limit)
        )
        rows = self.engine.connect().execute(statement).scalars().all()
        return [AtlasCandidateVerification.model_validate(json.loads(row)) for row in rows]


def is_verified(store: DurableAtlasCandidateVerificationStore, candidate_id: str) -> bool:
    """True only if the candidate's *latest* verification is VERIFIED.

    A REJECTED verification never becomes VERIFIED by being superseded with
    nothing -- a genuinely fixed candidate needs a fresh, real verify call
    that itself passes and becomes the new latest record.
    """
    latest = store.latest(candidate_id)
    return latest is not None and latest.verification_state is AtlasCandidateVerificationState.VERIFIED
