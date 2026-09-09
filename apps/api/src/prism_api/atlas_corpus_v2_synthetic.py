"""Corpus V2's synthetic-teacher source -- Wave 1.

The 131-example combined corpus proved the physical Foundry pipeline but is
far too small to teach a weak base model senior-DS-quality behavior. This
module adds a new, clearly-labelled ``synthetic_teacher`` source: examples
generated directly against ``AtlasSyntheticTeacherSkillArea`` specifications
(never against AtlasBench questions, choices, or rationales -- skill area
plus topic is the only generation input, which cannot encode a specific
benchmark item by construction).

Structurally never confused with real data, mirroring the same separation
``atlas_system_seed.py`` already enforces for ``system_seed``:

- ``AtlasSyntheticTeacherExample.source_kind`` is always the literal
  ``"synthetic_teacher"``, distinct from ``"system_seed"`` and
  ``"atlas_run"``.
- Every example carries real generation provenance (teacher model/revision,
  generation-policy version, skill taxonomy, license, validation status) --
  never presented as human-authored or as real user/product data.
- Two independent, programmatic leakage guards -- against AtlasBench V1
  *and* AtlasBench V2 -- verify no example's text overlaps either frozen
  benchmark corpus, using the same word-shingle technique
  ``atlas_system_seed.py`` already uses and already proved catches real
  overlaps, not just exact copies.
- An intra-corpus near-duplicate guard catches accidental repetition within
  this wave itself, independent of the cross-corpus leakage guards.

Versioning: a released ``generation_policy_version``'s content is immutable,
exactly like ``SEED_VERSION`` in ``atlas_system_seed.py``. A content change
is a new version and a new manifest -- ``DurableAtlasSyntheticTeacherStore``
never overwrites a prior version's persisted examples or manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from prism_api_contracts import (
    AtlasSyntheticTeacherExample,
    AtlasSyntheticTeacherManifest,
    AtlasSyntheticTeacherSkillArea,
    AtlasSyntheticTeacherSkillAreaCount,
    AtlasSyntheticTeacherValidationStatus,
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
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine

from .atlas_bench_corpus import all_tasks as all_v1_tasks
from .atlas_bench_corpus_v2 import all_tasks as all_v2_tasks
from .atlas_corpus_v2_synthetic_content import RAW_SYNTHETIC_TEACHER_EXAMPLES
from .atlas_system_seed import _shingles
from .durable_atlas_store import redact_atlas_payload
from .durable_registry import history_database_url

# Same credential-shaped-content boundary used by Atlas memory/retrieval/
# feedback: a teaching example is not a place to durably store a pasted API
# key or password, even by accident.
_CREDENTIAL = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}|password\s*[:=])", re.I
)

GENERATION_POLICY_VERSION = "synthetic-teacher-v1"
# The actual model configured for this session at generation time (see the
# session's own model-identity note); no finer-grained build/revision string
# is exposed by the runtime beyond this configured identifier, so none is
# fabricated here.
TEACHER_MODEL = "claude-sonnet-5"
TEACHER_REVISION = "session-configured-2026-09"
# Every entry in this wave was generated directly from an
# AtlasSyntheticTeacherSkillArea + topic specification, never from an
# AtlasBench question/choice/rationale, and never adapted from another
# party's copyrighted text -- "internal-generated" reflects that this
# content has no external license to track, unlike a properly licensed
# public dataset would.
DEFAULT_LICENSE = "internal-generated"
# Every value an example's ``license`` field may legitimately carry. A wave
# that ever mixes in properly licensed public examples adds its real license
# identifier here explicitly -- an unrecognized value fails closed rather
# than being silently trusted.
ALLOWED_LICENSES = frozenset({DEFAULT_LICENSE})


class AtlasSyntheticTeacherLeakageError(RuntimeError):
    """Raised when an example's text overlaps a real benchmark task
    (AtlasBench V1 or V2). Fails closed: corpus construction never silently
    proceeds with a suspected leak into a frozen evaluation corpus."""


class AtlasSyntheticTeacherDuplicateError(RuntimeError):
    """Raised on an accidental exact or near-duplicate within this wave."""


class AtlasSyntheticTeacherLicenseError(RuntimeError):
    """Raised when an example declares a license outside ``ALLOWED_LICENSES``."""


class AtlasSyntheticTeacherSecretError(RuntimeError):
    """Raised when an example's text looks like it contains a credential or
    other secret-shaped value -- the same boundary already enforced for
    Atlas memory, retrieval, and feedback content."""


def _content_hash(
    skill_area: str, topic: str, instruction: str, input_text: str, output: str, uncertainty: Optional[str]
) -> str:
    canonical = json.dumps(
        {
            "generation_policy_version": GENERATION_POLICY_VERSION,
            "skill_area": skill_area,
            "topic": topic,
            "instruction": instruction,
            "input": input_text,
            "output": output,
            "uncertainty": uncertainty,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_synthetic_teacher_corpus() -> list[AtlasSyntheticTeacherExample]:
    """Build the immutable wave-1 corpus from reviewed raw content.

    Deterministic: rebuilding from the same raw content and
    ``GENERATION_POLICY_VERSION`` always produces the same
    ``teacher_example_id`` and ``content_hash`` for every example.
    """
    now = datetime.now(timezone.utc)
    examples: list[AtlasSyntheticTeacherExample] = []
    seen_ids: set[str] = set()
    for (
        skill_area,
        topic,
        instruction,
        input_text,
        output,
        uncertainty,
        validation_status,
        validation_note,
    ) in RAW_SYNTHETIC_TEACHER_EXAMPLES:
        content_hash = _content_hash(skill_area, topic, instruction, input_text, output, uncertainty)
        example = AtlasSyntheticTeacherExample(
            teacher_example_id=f"synthteach_{content_hash[:24]}",
            generation_policy_version=GENERATION_POLICY_VERSION,
            teacher_model=TEACHER_MODEL,
            teacher_revision=TEACHER_REVISION,
            skill_area=AtlasSyntheticTeacherSkillArea(skill_area),
            topic=topic,
            license=DEFAULT_LICENSE,
            instruction=instruction,
            input=input_text,
            output=output,
            uncertainty=uncertainty,
            validation_status=AtlasSyntheticTeacherValidationStatus(validation_status),
            validation_note=validation_note,
            content_hash=content_hash,
            created_at=now,
        )
        if example.teacher_example_id in seen_ids:
            raise AtlasSyntheticTeacherDuplicateError(
                f"Duplicate synthetic-teacher content detected for topic {topic!r} in skill area {skill_area!r}."
            )
        seen_ids.add(example.teacher_example_id)
        examples.append(example)
    return examples


# --- AtlasBench V1/V2 leakage guards -----------------------------------------


def _bench_shingles(tasks: object) -> list[tuple[str, frozenset[str]]]:
    result: list[tuple[str, frozenset[str]]] = []
    for task in tasks:  # type: ignore[attr-defined]
        fields: list[tuple[str, str]] = [("prompt", task.prompt), ("rationale", task.rationale)]
        fields.extend(("choice", choice) for choice in task.choices)
        for label, field_text in fields:
            shingles = _shingles(field_text)
            if shingles:
                result.append((f"{task.task_id}:{label}", shingles))
    return result


def _check_leakage(
    examples: list[AtlasSyntheticTeacherExample], bench_shingles: list[tuple[str, frozenset[str]]]
) -> list[str]:
    findings: list[str] = []
    for example in examples:
        example_text = f"{example.instruction} {example.input} {example.output}"
        example_shingles = _shingles(example_text)
        if not example_shingles:
            continue
        for source, shingles in bench_shingles:
            overlap = example_shingles & shingles
            if overlap:
                sample = sorted(overlap)[0]
                findings.append(f"{example.teacher_example_id} ({example.topic}) overlaps {source}: {sample!r}")
    return findings


def check_atlasbench_v1_leakage(examples: list[AtlasSyntheticTeacherExample]) -> list[str]:
    """Real, programmatic overlap check against the frozen AtlasBench V1 corpus."""
    return _check_leakage(examples, _bench_shingles(all_v1_tasks()))


def check_atlasbench_v2_leakage(examples: list[AtlasSyntheticTeacherExample]) -> list[str]:
    """Real, programmatic overlap check against the frozen AtlasBench V2 holdout.

    V2 is a holdout that must never become training data; this guard is the
    programmatic enforcement of that rule for the synthetic-teacher source,
    the same way ``check_atlasbench_v1_leakage`` enforces it for V1.
    """
    return _check_leakage(examples, _bench_shingles(all_v2_tasks()))


def check_intra_corpus_near_duplicates(examples: list[AtlasSyntheticTeacherExample]) -> list[str]:
    """Catch accidental near-duplicate examples within this wave itself,
    independent of (and in addition to) the exact-content-hash check in
    ``build_synthetic_teacher_corpus``."""
    findings: list[str] = []
    seen_shingles: dict[str, str] = {}
    for example in sorted(examples, key=lambda item: item.teacher_example_id):
        text = f"{example.instruction} {example.output}"
        for shingle in _shingles(text):
            prior = seen_shingles.get(shingle)
            if prior is not None and prior != example.teacher_example_id:
                findings.append(f"{example.teacher_example_id} near-duplicates {prior} (shared phrase {shingle!r})")
                break
            seen_shingles[shingle] = example.teacher_example_id
    return findings


def check_license_validation(examples: list[AtlasSyntheticTeacherExample]) -> list[str]:
    """Every example's declared license must be one this codebase actually
    recognizes -- an unrecognized value is refused rather than silently
    trusted, the same fail-closed posture as the leakage guards."""
    return [
        f"{example.teacher_example_id} declares unrecognized license {example.license!r}"
        for example in examples
        if example.license not in ALLOWED_LICENSES
    ]


def check_secret_scan(examples: list[AtlasSyntheticTeacherExample]) -> list[str]:
    """Real, programmatic scan for credential/secret-shaped content, reusing
    the exact boundary already enforced for Atlas memory, retrieval, and
    feedback content -- a teaching example is not exempt from it."""
    findings: list[str] = []
    for example in examples:
        text = f"{example.instruction} {example.input} {example.output}"
        if _CREDENTIAL.search(text) or redact_atlas_payload(text) != text:
            findings.append(f"{example.teacher_example_id} ({example.topic}) contains secret-shaped content")
    return findings


def build_verified_synthetic_teacher_corpus() -> list[AtlasSyntheticTeacherExample]:
    """Build the corpus and enforce every quality gate -- fail closed.

    Callers (the combined-SFT builder, the durable store's ``release``)
    should use this function; ``build_synthetic_teacher_corpus`` alone is
    exposed separately for tests that want to inspect a corpus without also
    depending on the live AtlasBench V1/V2 corpus modules.
    """
    examples = build_synthetic_teacher_corpus()
    v1_findings = check_atlasbench_v1_leakage(examples)
    if v1_findings:
        raise AtlasSyntheticTeacherLeakageError(
            "Synthetic-teacher corpus refused: possible AtlasBench V1 leakage detected -- "
            + "; ".join(v1_findings[:10])
        )
    v2_findings = check_atlasbench_v2_leakage(examples)
    if v2_findings:
        raise AtlasSyntheticTeacherLeakageError(
            "Synthetic-teacher corpus refused: possible AtlasBench V2 leakage detected -- "
            + "; ".join(v2_findings[:10])
        )
    duplicate_findings = check_intra_corpus_near_duplicates(examples)
    if duplicate_findings:
        raise AtlasSyntheticTeacherDuplicateError(
            "Synthetic-teacher corpus refused: near-duplicate examples detected -- "
            + "; ".join(duplicate_findings[:10])
        )
    license_findings = check_license_validation(examples)
    if license_findings:
        raise AtlasSyntheticTeacherLicenseError(
            "Synthetic-teacher corpus refused: unrecognized license declared -- "
            + "; ".join(license_findings[:10])
        )
    secret_findings = check_secret_scan(examples)
    if secret_findings:
        raise AtlasSyntheticTeacherSecretError(
            "Synthetic-teacher corpus refused: secret-shaped content detected -- "
            + "; ".join(secret_findings[:10])
        )
    return examples


def manifest_content_hash(examples: list[AtlasSyntheticTeacherExample]) -> str:
    canonical = json.dumps(sorted(example.content_hash for example in examples), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_manifest(
    examples: list[AtlasSyntheticTeacherExample],
    *,
    v1_leakage_guard_passed: bool,
    v2_leakage_guard_passed: bool,
    duplicate_guard_passed: bool,
    license_validation_passed: bool = True,
    secret_scan_passed: bool = True,
) -> AtlasSyntheticTeacherManifest:
    counts = Counter(example.skill_area for example in examples)
    return AtlasSyntheticTeacherManifest(
        generation_policy_version=GENERATION_POLICY_VERSION,
        created_at=datetime.now(timezone.utc),
        example_count=len(examples),
        skill_area_counts=[
            AtlasSyntheticTeacherSkillAreaCount(skill_area=area, example_count=count)
            for area, count in sorted(counts.items(), key=lambda item: item[0].value)
        ],
        aggregate_content_hash=manifest_content_hash(examples),
        atlasbench_v1_leakage_guard_passed=v1_leakage_guard_passed,
        atlasbench_v2_leakage_guard_passed=v2_leakage_guard_passed,
        intra_corpus_duplicate_guard_passed=duplicate_guard_passed,
        license_validation_passed=license_validation_passed,
        secret_scan_passed=secret_scan_passed,
    )


# --- durable, immutable persistence -----------------------------------------

_metadata = MetaData()
_manifests = Table(
    "prism_atlas_synthetic_teacher_manifests",
    _metadata,
    Column("generation_policy_version", String(40), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("example_count", Integer, nullable=False),
    Column("aggregate_content_hash", String(64), nullable=False),
    Column("atlasbench_v1_leakage_guard_passed", Integer, nullable=False),
    Column("atlasbench_v2_leakage_guard_passed", Integer, nullable=False),
    Column("intra_corpus_duplicate_guard_passed", Integer, nullable=False),
    Column("license_validation_passed", Integer, nullable=False, server_default="1"),
    Column("secret_scan_passed", Integer, nullable=False, server_default="1"),
    Column("skill_area_counts_payload", Text, nullable=False),
)
_examples_table = Table(
    "prism_atlas_synthetic_teacher_examples",
    _metadata,
    Column("generation_policy_version", String(40), primary_key=True),
    Column("teacher_example_id", String(120), primary_key=True),
    Column("skill_area", String(40), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class DurableAtlasSyntheticTeacherStore:
    """Immutable-per-version persistence, mirroring ``DurableAtlasSystemSeedStore``:
    releasing the same ``generation_policy_version`` twice is idempotent; a
    new version is always a brand-new set of rows, never an edit of an old one.
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
        with self.engine.begin() as connection:
            # create_all only creates missing tables, never alters an
            # existing one -- a manifest column added after this table
            # already exists (as it did once here) needs the same explicit
            # backfill atlas_bench_store.py already established.
            existing = {
                str(item["name"])
                for item in inspect(connection).get_columns("prism_atlas_synthetic_teacher_manifests")
            }
            additions = {
                "license_validation_passed": "INTEGER NOT NULL DEFAULT 1",
                "secret_scan_passed": "INTEGER NOT NULL DEFAULT 1",
            }
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE prism_atlas_synthetic_teacher_manifests ADD COLUMN {name} {definition}"))

    def release(
        self, examples: list[AtlasSyntheticTeacherExample], manifest: AtlasSyntheticTeacherManifest
    ) -> AtlasSyntheticTeacherManifest:
        existing = self.get_manifest(manifest.generation_policy_version)
        if existing is not None:
            return existing
        with self.engine.begin() as connection:
            connection.execute(
                insert(_manifests).values(
                    generation_policy_version=manifest.generation_policy_version,
                    created_at=manifest.created_at,
                    example_count=manifest.example_count,
                    aggregate_content_hash=manifest.aggregate_content_hash,
                    atlasbench_v1_leakage_guard_passed=int(manifest.atlasbench_v1_leakage_guard_passed),
                    atlasbench_v2_leakage_guard_passed=int(manifest.atlasbench_v2_leakage_guard_passed),
                    intra_corpus_duplicate_guard_passed=int(manifest.intra_corpus_duplicate_guard_passed),
                    license_validation_passed=int(manifest.license_validation_passed),
                    secret_scan_passed=int(manifest.secret_scan_passed),
                    skill_area_counts_payload=json.dumps(
                        [item.model_dump(mode="json") for item in manifest.skill_area_counts], sort_keys=True
                    ),
                )
            )
            for example in examples:
                connection.execute(
                    insert(_examples_table).values(
                        generation_policy_version=example.generation_policy_version,
                        teacher_example_id=example.teacher_example_id,
                        skill_area=example.skill_area.value,
                        payload=json.dumps(example.model_dump(mode="json"), sort_keys=True),
                        created_at=example.created_at,
                    )
                )
        return manifest

    def get_manifest(self, generation_policy_version: str) -> Optional[AtlasSyntheticTeacherManifest]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(_manifests).where(_manifests.c.generation_policy_version == generation_policy_version)
            ).mappings().first()
        if row is None:
            return None
        skill_area_counts = [
            AtlasSyntheticTeacherSkillAreaCount.model_validate(item)
            for item in json.loads(row["skill_area_counts_payload"])
        ]
        return AtlasSyntheticTeacherManifest(
            generation_policy_version=row["generation_policy_version"],
            created_at=row["created_at"],
            example_count=row["example_count"],
            skill_area_counts=skill_area_counts,
            aggregate_content_hash=row["aggregate_content_hash"],
            atlasbench_v1_leakage_guard_passed=bool(row["atlasbench_v1_leakage_guard_passed"]),
            atlasbench_v2_leakage_guard_passed=bool(row["atlasbench_v2_leakage_guard_passed"]),
            intra_corpus_duplicate_guard_passed=bool(row["intra_corpus_duplicate_guard_passed"]),
            license_validation_passed=bool(row["license_validation_passed"]),
            secret_scan_passed=bool(row["secret_scan_passed"]),
        )

    def list_manifests(self, *, limit: int = 50) -> list[AtlasSyntheticTeacherManifest]:
        statement = (
            select(_manifests.c.generation_policy_version)
            .order_by(_manifests.c.created_at.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            versions = connection.execute(statement).scalars().all()
        manifests = [self.get_manifest(version) for version in versions]
        return [manifest for manifest in manifests if manifest is not None]

    def examples(self, generation_policy_version: str, *, limit: int = 2_000) -> list[AtlasSyntheticTeacherExample]:
        statement = (
            select(_examples_table.c.payload)
            .where(_examples_table.c.generation_policy_version == generation_policy_version)
            .order_by(_examples_table.c.teacher_example_id)
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).scalars().all()
        return [AtlasSyntheticTeacherExample.model_validate(json.loads(row)) for row in rows]
