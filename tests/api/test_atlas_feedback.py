from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from prism_api.atlas_feedback import DurableAtlasFeedbackStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasEvidenceReference,
    AtlasFeedbackEvent,
    AtlasFeedbackKind,
    AtlasFeedbackWriteRequest,
)
from pydantic import ValidationError


def _store(tmp_path):  # type: ignore[no-untyped-def]
    return DurableAtlasFeedbackStore(f"sqlite:///{(tmp_path / 'feedback.sqlite').as_posix()}")


def _evidence() -> list[AtlasEvidenceReference]:
    return [
        AtlasEvidenceReference(
            evidence_id="ev_1", kind="analytical_object", summary="Forecast object used for this answer.",
        )
    ]


def test_binary_feedback_round_trips_with_evidence_and_project(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    request = AtlasFeedbackWriteRequest(
        run_id="run_1", project_id="proj_1", kind=AtlasFeedbackKind.HELPFUL,
        answer="Revenue grew 12% quarter over quarter.", evidence=_evidence(),
    )

    event = store.record(request)

    assert isinstance(event, AtlasFeedbackEvent)
    assert event.correction is None
    assert event.run_id == "run_1" and event.project_id == "proj_1"
    [reread] = store.list_for_run("run_1")
    assert reread.feedback_id == event.feedback_id
    assert reread.evidence[0].evidence_id == "ev_1"
    [by_project] = store.list_for_project("proj_1")
    assert by_project.feedback_id == event.feedback_id


def test_corrected_feedback_requires_a_correction() -> None:
    with pytest.raises(ValidationError):
        AtlasFeedbackWriteRequest(run_id="run_1", kind=AtlasFeedbackKind.CORRECTED, answer="Wrong answer.")


def test_non_corrected_feedback_rejects_a_correction() -> None:
    with pytest.raises(ValidationError):
        AtlasFeedbackWriteRequest(
            run_id="run_1", kind=AtlasFeedbackKind.HELPFUL, answer="Fine.", correction="Should not be set.",
        )


def test_corrected_feedback_is_the_dpo_substrate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    request = AtlasFeedbackWriteRequest(
        run_id="run_2", kind=AtlasFeedbackKind.CORRECTED,
        answer="SELECT * FROM sales", correction="SELECT id, region, revenue FROM sales",
    )

    event = store.record(request)

    assert event.correction == "SELECT id, region, revenue FROM sales"
    [dpo_pair] = store.list_by_kind(AtlasFeedbackKind.CORRECTED)
    assert dpo_pair.answer == "SELECT * FROM sales"
    assert dpo_pair.correction == "SELECT id, region, revenue FROM sales"


def test_feedback_is_append_only_never_edited(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    store.record(AtlasFeedbackWriteRequest(run_id="run_3", kind=AtlasFeedbackKind.HELPFUL, answer="First take."))
    store.record(AtlasFeedbackWriteRequest(run_id="run_3", kind=AtlasFeedbackKind.NOT_HELPFUL, answer="First take."))

    events = store.list_for_run("run_3")

    assert len(events) == 2
    assert {event.kind for event in events} == {AtlasFeedbackKind.HELPFUL, AtlasFeedbackKind.NOT_HELPFUL}


def test_feedback_rejects_secret_shaped_answers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    request = AtlasFeedbackWriteRequest(
        run_id="run_4", kind=AtlasFeedbackKind.NOT_HELPFUL,
        answer="Use this key: sk-abcdefghijklmnopqrstuvwx to authenticate.",
    )

    with pytest.raises(HTTPException) as excinfo:
        store.record(request)
    assert excinfo.value.status_code == 422


def test_rejected_and_accepted_are_valid_binary_kinds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    store.record(AtlasFeedbackWriteRequest(run_id="run_5", kind=AtlasFeedbackKind.ACCEPTED, answer="Plan accepted."))
    store.record(AtlasFeedbackWriteRequest(run_id="run_5", kind=AtlasFeedbackKind.REJECTED, answer="Plan accepted."))

    kinds = {event.kind for event in store.list_for_run("run_5")}

    assert kinds == {AtlasFeedbackKind.ACCEPTED, AtlasFeedbackKind.REJECTED}


def test_list_recent_spans_every_run_and_project_newest_first(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The system-level Memory panel's Corrections discovery path: no
    run_id or project_id required up front, unlike list_for_run/
    list_for_project."""
    store = _store(tmp_path)
    first = store.record(AtlasFeedbackWriteRequest(run_id="run_a", project_id="proj_a", kind=AtlasFeedbackKind.HELPFUL, answer="First."))
    second = store.record(AtlasFeedbackWriteRequest(run_id="run_b", kind=AtlasFeedbackKind.CORRECTED, answer="Wrong.", correction="Right."))

    recent = store.list_recent()

    assert [event.feedback_id for event in recent] == [second.feedback_id, first.feedback_id]
    assert recent[0].correction == "Right."

    bounded = store.list_recent(limit=1)
    assert [event.feedback_id for event in bounded] == [second.feedback_id]


def test_recent_feedback_route_surfaces_a_posted_event_without_a_run_or_project_id() -> None:
    client = TestClient(create_app())
    posted = client.post(
        "/api/v1/atlas/feedback",
        json={"run_id": f"run_recent_route_{uuid.uuid4().hex}", "kind": "helpful", "answer": "Route-level recent feedback check."},
    )
    assert posted.status_code == 201
    feedback_id = posted.json()["feedback_id"]

    response = client.get("/api/v1/atlas/feedback/recent", params={"limit": 500})
    assert response.status_code == 200
    ids = {event["feedback_id"] for event in response.json()}
    assert feedback_id in ids
