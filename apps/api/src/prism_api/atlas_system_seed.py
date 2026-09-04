"""System Seed Corpus V1 -- a durable, immutable, hand-authored SFT source.

The first real training-dataset build produced zero eligible examples: this
runtime simply does not yet contain enough completed, evidence-backed Atlas
runs or real user corrections to train from
(``.prism/checkpoints/phase-10-evolution-activation.md``). Rather than block
on that indefinitely, this module introduces an explicit, clearly-labelled
``SYSTEM_SEED`` source: reviewed teaching examples covering the specific weak
areas the first real AtlasBench baseline (71/90) showed room to improve.

This is structurally never confused with real data:

- ``AtlasSystemSeedExample.source_kind`` is always the literal
  ``"system_seed"``, distinct from ``AtlasTrainingExampleSource.ATLAS_RUN``
  (real Atlas runs) and ``AtlasPreferencePairSource`` (real corrections).
- A seed example is never registered as, or exported alongside, a real run
  or correction inside the same record -- callers combining sources keep
  separate counts (see ``build_system_seed_corpus`` callers in
  ``atlas_foundry_routes.py``), never merge them into one indistinguishable
  pool.
- ``check_atlasbench_leakage`` programmatically verifies -- not just by
  author intent -- that no seed example's text overlaps AtlasBench's real
  task prompts, choices, or rationale. Corpus construction fails closed if
  it finds suspicious overlap.

Versioning: a released ``seed_version``'s content is immutable. A content
change is a new ``seed_version`` (bump ``SEED_VERSION`` below) and a new
manifest -- ``DurableAtlasSystemSeedStore`` never overwrites a prior
version's persisted examples or manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from prism_api_contracts import (
    AtlasSystemSeedDomain,
    AtlasSystemSeedDomainCount,
    AtlasSystemSeedExample,
    AtlasSystemSeedManifest,
    AtlasSystemSeedReviewStatus,
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

from .atlas_bench_corpus import all_tasks
from .atlas_system_seed_content import RAW_SEED_EXAMPLES
from .durable_registry import history_database_url

SEED_VERSION = "system-seed-v1"


class AtlasSystemSeedLeakageError(RuntimeError):
    """Raised when a seed example's text overlaps a real AtlasBench task.

    Fails closed: corpus construction never silently proceeds with a
    suspected leak, and AtlasBench remains evaluator-only.
    """


def _content_hash(domain: str, topic: str, user_request: str, final_answer: str, uncertainty: Optional[str]) -> str:
    canonical = json.dumps(
        {
            "seed_version": SEED_VERSION,
            "domain": domain,
            "topic": topic,
            "user_request": user_request,
            "final_answer": final_answer,
            "uncertainty": uncertainty,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_system_seed_corpus() -> list[AtlasSystemSeedExample]:
    """Build the immutable V1 corpus from reviewed raw content.

    Deterministic: rebuilding from the same ``RAW_SEED_EXAMPLES`` and
    ``SEED_VERSION`` always produces the same ``seed_example_id`` and
    ``content_hash`` for every example.
    """
    now = datetime.now(timezone.utc)
    examples: list[AtlasSystemSeedExample] = []
    seen_ids: set[str] = set()
    for domain, topic, user_request, final_answer, uncertainty in RAW_SEED_EXAMPLES:
        content_hash = _content_hash(domain, topic, user_request, final_answer, uncertainty)
        example = AtlasSystemSeedExample(
            seed_example_id=f"seed_{content_hash[:24]}",
            seed_version=SEED_VERSION,
            domain=AtlasSystemSeedDomain(domain),
            topic=topic,
            user_request=user_request,
            final_answer=final_answer,
            uncertainty=uncertainty,
            review_status=AtlasSystemSeedReviewStatus.REVIEWED,
            content_hash=content_hash,
            created_at=now,
        )
        if example.seed_example_id in seen_ids:
            # Two raw entries hashed identically -- a real authoring bug
            # (accidental duplicate), not something to silently drop.
            raise ValueError(f"Duplicate system-seed content detected for topic {topic!r} in domain {domain!r}.")
        seen_ids.add(example.seed_example_id)
        examples.append(example)
    return examples


# --- AtlasBench leakage guard ------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_SHINGLE_SIZE = 8


def _normalize_words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _shingles(text: str) -> frozenset[str]:
    """Overlapping word-shingles, a simple but real fingerprint: two texts
    that share an 8-word shingle share a specific, non-generic phrase, not
    just common short terms like "confidence interval"."""
    words = _normalize_words(text)
    if len(words) < _SHINGLE_SIZE:
        joined = " ".join(words)
        return frozenset({joined}) if joined else frozenset()
    return frozenset(
        " ".join(words[i : i + _SHINGLE_SIZE]) for i in range(len(words) - _SHINGLE_SIZE + 1)
    )


def check_atlasbench_leakage(examples: list[AtlasSystemSeedExample]) -> list[str]:
    """Real, programmatic overlap check against the actual AtlasBench corpus.

    Compares each example's text against every task's prompt, every choice,
    and its rationale -- the exact fields AtlasBench must never leak into
    training data. Returns a human-readable finding per detected overlap;
    an empty list means the guard found nothing suspicious.
    """
    bench_shingles: list[tuple[str, frozenset[str]]] = []
    for task in all_tasks():
        fields: list[tuple[str, str]] = [("prompt", task.prompt), ("rationale", task.rationale)]
        fields.extend(("choice", choice) for choice in task.choices)
        for label, text in fields:
            shingles = _shingles(text)
            if shingles:
                bench_shingles.append((f"{task.task_id}:{label}", shingles))

    findings: list[str] = []
    for example in examples:
        example_text = f"{example.user_request} {example.final_answer}"
        example_shingles = _shingles(example_text)
        if not example_shingles:
            continue
        for source, shingles in bench_shingles:
            overlap = example_shingles & shingles
            if overlap:
                sample = sorted(overlap)[0]
                findings.append(
                    f"{example.seed_example_id} ({example.topic}) overlaps AtlasBench {source}: {sample!r}"
                )
    return findings


def build_verified_system_seed_corpus() -> list[AtlasSystemSeedExample]:
    """Build the corpus and enforce the leakage guard -- fail closed.

    This is the function callers (the training-dataset combiner, the
    durable store's ``release``) should use; ``build_system_seed_corpus``
    alone is exposed separately for tests that want to inspect a corpus
    without also depending on the live AtlasBench corpus module.
    """
    examples = build_system_seed_corpus()
    findings = check_atlasbench_leakage(examples)
    if findings:
        raise AtlasSystemSeedLeakageError(
            "System seed corpus construction refused: possible AtlasBench leakage detected -- "
            + "; ".join(findings[:10])
        )
    return examples


def manifest_content_hash(examples: list[AtlasSystemSeedExample]) -> str:
    canonical = json.dumps(sorted(example.content_hash for example in examples), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_manifest(examples: list[AtlasSystemSeedExample], *, leakage_guard_passed: bool) -> AtlasSystemSeedManifest:
    counts = Counter(example.domain for example in examples)
    return AtlasSystemSeedManifest(
        seed_version=SEED_VERSION,
        created_at=datetime.now(timezone.utc),
        example_count=len(examples),
        domain_counts=[
            AtlasSystemSeedDomainCount(domain=domain, example_count=count)
            for domain, count in sorted(counts.items(), key=lambda item: item[0].value)
        ],
        aggregate_content_hash=manifest_content_hash(examples),
        leakage_guard_passed=leakage_guard_passed,
    )


# --- durable, immutable persistence -----------------------------------------

_metadata = MetaData()
_manifests = Table(
    "prism_atlas_system_seed_manifests",
    _metadata,
    Column("seed_version", String(40), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("example_count", Integer, nullable=False),
    Column("aggregate_content_hash", String(64), nullable=False),
    Column("leakage_guard_passed", Integer, nullable=False),
    Column("domain_counts_payload", Text, nullable=False),
)
_examples_table = Table(
    "prism_atlas_system_seed_examples",
    _metadata,
    Column("seed_version", String(40), primary_key=True),
    Column("seed_example_id", String(120), primary_key=True),
    Column("domain", String(40), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class DurableAtlasSystemSeedStore:
    """Immutable-per-version persistence: releasing the same seed_version
    twice is idempotent (never a second, possibly-different copy); a new
    version is always a brand-new set of rows, never an edit of an old one.
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

    def release(
        self, examples: list[AtlasSystemSeedExample], manifest: AtlasSystemSeedManifest
    ) -> AtlasSystemSeedManifest:
        existing = self.get_manifest(manifest.seed_version)
        if existing is not None:
            return existing
        with self.engine.begin() as connection:
            connection.execute(
                insert(_manifests).values(
                    seed_version=manifest.seed_version,
                    created_at=manifest.created_at,
                    example_count=manifest.example_count,
                    aggregate_content_hash=manifest.aggregate_content_hash,
                    leakage_guard_passed=int(manifest.leakage_guard_passed),
                    domain_counts_payload=json.dumps(
                        [item.model_dump(mode="json") for item in manifest.domain_counts], sort_keys=True
                    ),
                )
            )
            for example in examples:
                connection.execute(
                    insert(_examples_table).values(
                        seed_version=example.seed_version,
                        seed_example_id=example.seed_example_id,
                        domain=example.domain.value,
                        payload=json.dumps(example.model_dump(mode="json"), sort_keys=True),
                        created_at=example.created_at,
                    )
                )
        return manifest

    def get_manifest(self, seed_version: str) -> Optional[AtlasSystemSeedManifest]:
        row = (
            self.engine.connect()
            .execute(select(_manifests).where(_manifests.c.seed_version == seed_version))
            .mappings()
            .first()
        )
        if row is None:
            return None
        domain_counts = [
            AtlasSystemSeedDomainCount.model_validate(item) for item in json.loads(row["domain_counts_payload"])
        ]
        return AtlasSystemSeedManifest(
            seed_version=row["seed_version"],
            created_at=row["created_at"],
            example_count=row["example_count"],
            domain_counts=domain_counts,
            aggregate_content_hash=row["aggregate_content_hash"],
            leakage_guard_passed=bool(row["leakage_guard_passed"]),
        )

    def list_manifests(self, *, limit: int = 50) -> list[AtlasSystemSeedManifest]:
        statement = select(_manifests.c.seed_version).order_by(_manifests.c.created_at.desc()).limit(limit)
        versions = self.engine.connect().execute(statement).scalars().all()
        manifests = [self.get_manifest(version) for version in versions]
        return [manifest for manifest in manifests if manifest is not None]

    def examples(self, seed_version: str, *, limit: int = 1_000) -> list[AtlasSystemSeedExample]:
        statement = (
            select(_examples_table.c.payload)
            .where(_examples_table.c.seed_version == seed_version)
            .order_by(_examples_table.c.seed_example_id)
            .limit(limit)
        )
        rows = self.engine.connect().execute(statement).scalars().all()
        return [AtlasSystemSeedExample.model_validate(json.loads(row)) for row in rows]
