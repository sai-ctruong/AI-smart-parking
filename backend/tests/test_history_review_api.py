"""Operational history, append-only review, and CSV API contracts."""

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_snapshot_inference_api import configured_camera, upload

from app import snapshots as snapshot_api
from app.models import AuditLog, SpotPrediction, SpotReview

pytest_plugins = ("test_snapshot_inference_api",)


def test_history_pages_filters_and_validates_query(context):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin)
    now = datetime.now(timezone.utc)
    times = [
        now - timedelta(hours=3),
        now - timedelta(hours=2),
        now - timedelta(hours=1),
    ]
    ids = []
    for moment in times:
        response = upload(client, admin, camera_id, captured_at=moment.isoformat())
        assert response.status_code == 201, response.text
        ids.append(response.json()["snapshot_id"])

    page = client.get("/api/v1/snapshots?page=1&page_size=2", headers=admin)
    assert page.status_code == 200, page.text
    assert page.json()["total_items"] == 3
    assert [item["snapshot_id"] for item in page.json()["items"]] == ids[2:0:-1]
    assert page.json()["items"][0]["unknown_count"] == 1
    assert page.json()["items"][0]["alert_state"] == "STALE"
    second = client.get("/api/v1/snapshots?page=2&page_size=2", headers=admin)
    assert [item["snapshot_id"] for item in second.json()["items"]] == ids[:1]

    start = (now - timedelta(hours=2, minutes=30)).isoformat()
    end = (now - timedelta(hours=1, minutes=30)).isoformat()
    filtered = client.get(
        "/api/v1/snapshots",
        headers=admin,
        params={"camera_id": camera_id, "from": start, "to": end},
    )
    assert [item["snapshot_id"] for item in filtered.json()["items"]] == ids[1:2]
    for params in (
        {"page": 0},
        {"page_size": 101},
        {"from": end, "to": start},
        {"from": "2026-10-25T00:00:00"},
        {"camera_id": "bad"},
    ):
        assert (
            client.get("/api/v1/snapshots", headers=admin, params=params).status_code
            == 422
        )
    assert client.get("/api/v1/snapshots").status_code == 401


def test_operator_review_preserves_ai_value_and_audits_versions(context, monkeypatch):
    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin)
    monkeypatch.setattr(
        snapshot_api,
        "_predict",
        lambda _image, spots, _settings: [
            snapshot_api.Verdict("occupied", 0.91, "test-model", None) for _ in spots
        ],
    )
    created = upload(client, admin, camera_id)
    assert created.status_code == 201
    snapshot_id = created.json()["snapshot_id"]
    prediction_id = created.json()["predictions"][0]["prediction_id"]
    user = client.post(
        "/api/v1/users",
        headers=admin,
        json={
            "username": "reviewer",
            "password": "Reviewer-password-2026",
            "role": "operator",
        },
    ).json()
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "reviewer", "password": "Reviewer-password-2026"},
    ).json()["access_token"]
    operator = {"Authorization": f"Bearer {token}"}
    path = f"/api/v1/predictions/{prediction_id}/reviews"
    assert (
        client.post(
            path, headers=operator, json={"reviewed_status": "empty"}
        ).status_code
        == 428
    )
    first = client.post(
        path,
        headers={**operator, "If-Match": '"0"'},
        json={"reviewed_status": "empty", "note": "Space is clear"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["revision_no"] == 1
    assert first.json()["reviewed_by"] == user["id"]
    assert datetime.fromisoformat(first.json()["reviewed_at"]).tzinfo is not None
    after_first = client.get("/api/v1/lots/current/occupancy", headers=operator).json()
    assert after_first["counts"]["empty"] == 1
    assert after_first["alert_state"] == "NONE"
    stale = client.post(
        path,
        headers={**operator, "If-Match": '"0"'},
        json={"reviewed_status": "occupied"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "REVIEW_CONFLICT"
    second = client.post(
        path,
        headers={**operator, "If-Match": '"1"'},
        json={"reviewed_status": "unknown"},
    )
    assert second.status_code == 201
    detail = client.get(f"/api/v1/snapshots/{snapshot_id}", headers=operator).json()
    item = detail["predictions"][0]
    assert item["predicted_status"] == "occupied"
    assert item["effective_status"] == "unknown"
    assert item["confidence"] == 0.91
    assert item["latest_review_id"] == second.json()["id"]
    assert (
        detail["empty_count"],
        detail["occupied_count"],
        detail["unknown_count"],
    ) == (0, 0, 1)
    assert detail["alert_state"] == "NONE"
    history = client.get(path, headers=operator)
    assert [row["revision_no"] for row in history.json()["items"]] == [1, 2]
    with Session(engine) as session:
        prediction = session.get(SpotPrediction, UUID(prediction_id))
        assert prediction.prediction_status == "occupied"
        assert prediction.review_version == 2
        assert len(session.scalars(select(SpotReview)).all()) == 2
        audits = session.scalars(
            select(AuditLog).where(AuditLog.action == "prediction.reviewed")
        ).all()
        assert len(audits) == 2
        assert all(a.actor_id == UUID(user["id"]) for a in audits)


def test_review_validation_missing_prediction_and_csv(context):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin)
    created = upload(client, admin, camera_id).json()
    prediction_id = created["predictions"][0]["prediction_id"]
    path = f"/api/v1/predictions/{prediction_id}/reviews"
    assert (
        client.post(
            path, headers={**admin, "If-Match": '"0"'}, json={"reviewed_status": "full"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, headers={**admin, "If-Match": "0"}, json={"reviewed_status": "empty"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/predictions/{'0' * 8}-0000-0000-0000-000000000000/reviews",
            headers=admin,
        ).status_code
        == 404
    )
    assert client.get(path).status_code == 401
    review = client.post(
        path,
        headers={**admin, "If-Match": '"0"'},
        json={"reviewed_status": "occupied", "note": "=SUM(1,1)"},
    )
    assert review.status_code == 201
    exported = client.get("/api/v1/snapshots/export.csv", headers=admin)
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(StringIO(exported.text)))
    assert len(rows) == 1
    assert list(rows[0]) == [
        "snapshot_id",
        "camera_id",
        "captured_at",
        "uploaded_at",
        "spot_id",
        "polygon_revision_id",
        "prediction_status",
        "effective_status",
        "confidence",
        "model_version",
        "reason_code",
        "inferred_at",
        "latest_review_id",
        "latest_reviewed_by",
        "latest_reviewed_at",
    ]
    assert rows[0]["snapshot_id"] == created["snapshot_id"]
    assert rows[0]["prediction_status"] == "unknown"
    assert rows[0]["effective_status"] == "occupied"
    assert rows[0]["latest_review_id"] == review.json()["id"]
    detail = client.get(
        f"/api/v1/snapshots/{created['snapshot_id']}", headers=admin
    ).json()
    assert detail["alert_state"] == "FULL"
    assert detail["predictions"][0]["predicted_status"] == "unknown"
    assert detail["predictions"][0]["effective_status"] == "occupied"
    assert client.get(
        "/api/v1/snapshots/export.csv",
        headers=admin,
        params={"from": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    ).text.splitlines() == [",".join(list(rows[0]))]
    assert (
        client.get(
            "/api/v1/snapshots/export.csv",
            headers=admin,
            params={"from": "2026-10-26T00:00:00Z", "to": "2026-10-25T00:00:00Z"},
        ).status_code
        == 422
    )
    assert client.get("/api/v1/snapshots/export.csv").status_code == 401
