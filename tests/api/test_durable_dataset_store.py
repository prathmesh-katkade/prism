"""Regression coverage for the cross-dataset "latest" tiebreaker.

MySQL's DATETIME column truncates to whole-second precision by default, so
two uploads within the same second make ``ORDER BY activated_at DESC`` alone
non-deterministic - this was a real, previously unverified bug (not just a
flaky test): SQL Lab's "Source" connection list, AI Analyst, and Clean's
dataset routing all resolve the active dataset through
``DurableDatasetStore.latest()``. These tests force that exact tie directly
(no reliance on real wall-clock timing, so they fail reliably against the
pre-fix code and pass reliably against the fix, on SQLite as well as MySQL)
and confirm the ``sequence`` tiebreaker - not timestamp precision - decides
ties.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from prism_api.durable_dataset_store import DurableDatasetStore, _revisions
from sqlalchemy import update


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3]})


def _force_tied_activated_at(store: DurableDatasetStore, dataset_ids: list[str]) -> None:
    """Simulate MySQL's one-second DATETIME truncation colliding two uploads."""
    tied = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with store.engine.begin() as connection:
        for dataset_id in dataset_ids:
            connection.execute(update(_revisions).where(_revisions.c.dataset_id == dataset_id).values(activated_at=tied))


def test_latest_breaks_a_true_activated_at_tie_by_upload_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableDatasetStore(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    first = store.put(_frame(), "first.csv", "fp-first-0000000000000000")
    second = store.put(_frame(), "second.csv", "fp-second-0000000000000000")
    _force_tied_activated_at(store, [first.dataset_id, second.dataset_id])

    latest = store.latest()
    assert latest is not None
    assert latest.dataset.dataset_id == second.dataset_id, (
        "With activated_at tied (the real MySQL failure mode), latest() must still "
        "resolve to the dataset uploaded second via the sequence tiebreaker, not "
        "whatever order the database happens to return tied rows in."
    )


def test_latest_without_any_tie_still_returns_the_real_most_recent_upload(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableDatasetStore(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    store.put(_frame(), "first.csv", "fp-first-0000000000000000")
    second = store.put(_frame(), "second.csv", "fp-second-0000000000000000")

    latest = store.latest()
    assert latest is not None
    assert latest.dataset.dataset_id == second.dataset_id


def test_add_revision_makes_the_new_revision_win_latest_over_a_tied_rival(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableDatasetStore(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    first = store.put(_frame(), "first.csv", "fp-first-0000000000000000")
    second = store.put(_frame(), "second.csv", "fp-second-0000000000000000")
    _force_tied_activated_at(store, [first.dataset_id, second.dataset_id])
    assert store.latest().dataset.dataset_id == second.dataset_id  # sanity: second currently wins

    store.add_revision(first.dataset_id, _frame(), "fp-first-rev1-0000000000")

    latest = store.latest()
    assert latest is not None
    assert latest.dataset.dataset_id == first.dataset_id, (
        "Applying a change to the older dataset must make it the new latest, "
        "even though its original upload lost the earlier tie."
    )


def test_revert_makes_the_reactivated_dataset_win_latest_again(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableDatasetStore(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    first = store.put(_frame(), "first.csv", "fp-first-0000000000000000")
    store.add_revision(first.dataset_id, _frame(), "fp-first-rev1-0000000000")
    second = store.put(_frame(), "second.csv", "fp-second-0000000000000000")
    assert store.latest().dataset.dataset_id == second.dataset_id  # sanity: second is latest

    store.revert(first.dataset_id, 0)

    latest = store.latest()
    assert latest is not None
    assert latest.dataset.dataset_id == first.dataset_id, (
        "Reverting a dataset reactivates it as that dataset's current head, which "
        "should also make it win cross-dataset latest() again, not keep losing to "
        "a dataset uploaded before the revert."
    )
    assert latest.dataset.revision == 0


def test_list_current_orders_a_tie_by_upload_order_too(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableDatasetStore(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    first = store.put(_frame(), "first.csv", "fp-first-0000000000000000")
    second = store.put(_frame(), "second.csv", "fp-second-0000000000000000")
    _force_tied_activated_at(store, [first.dataset_id, second.dataset_id])

    current = store.list_current()
    assert [item.dataset_id for item in current[:2]] == [second.dataset_id, first.dataset_id]


def test_migrating_a_pre_existing_database_without_the_sequence_column_still_works(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A database created before this fix has no `sequence` column at all -
    create_all() only creates missing tables, not missing columns on an
    existing one, so the store must migrate it on startup rather than assume
    a fresh schema."""
    database_url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    pre_fix_store = DurableDatasetStore(database_url)
    with pre_fix_store.engine.begin() as connection:
        connection.execute(update(_revisions).values(sequence=None))  # simulate rows written before this column existed

    migrated_store = DurableDatasetStore(database_url)
    uploaded = migrated_store.put(_frame(), "after-migration.csv", "fp-after-0000000000000000")
    latest = migrated_store.latest()
    assert latest is not None
    assert latest.dataset.dataset_id == uploaded.dataset_id
