"""Snapshot upload and inference contracts on disposable migrated storage."""

import struct
import zlib
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from alembic import command
from app import db as db_module
from app import snapshots as snapshot_api
from app.auth import ApiError
from app.bootstrap_admin import bootstrap_admin
from app.config import DevelopmentSettings
from app.main import create_app
from app.models import (
    Camera,
    ParkingSpot,
    PolygonRevision,
    Snapshot,
    SpotPrediction,
    User,
)

SECRET = "test-only-snapshot-secret-with-at-least-32-bytes"
PASSWORD = "Correct-horse-admin-2026"


def png_bytes(width: int = 64, height: int = 64) -> bytes:
    """Build a real RGB PNG without an image library in the test fixture."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = (b"\x00" + b"\xff\xff\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def context(tmp_path: Path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'snapshots.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    engine = create_engine(url)
    with Session(engine) as session:
        bootstrap_admin(session, "admin", PASSWORD)
        session.commit()
    settings = DevelopmentSettings(
        _env_file=None,
        database_url=url,
        auth_secret_key=SECRET,
        image_storage_root=tmp_path / "private-images",
        cors_origins=["http://localhost:5173"],
    )
    with TestClient(create_app(settings)) as client:
        token = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["access_token"]
        yield client, engine, {"Authorization": f"Bearer {token}"}, tmp_path
    engine.dispose()


def configured_camera(client: TestClient, admin: dict[str, str], spots: int = 1) -> str:
    lot = client.post("/api/v1/lots", headers=admin, json={"name": "Main lot"}).json()
    camera = client.post(
        f"/api/v1/lots/{lot['id']}/cameras",
        headers=admin,
        json={
            "name": "Fixed camera",
            "reference_image": {"sha256": "a" * 64, "width": 64, "height": 64},
        },
    ).json()
    items = []
    for index in range(spots):
        left = 0.1 + index * 0.15
        items.append(
            {
                "code": f"S{index + 1:02d}",
                "points": [
                    {"x": left, "y": 0.1},
                    {"x": left + 0.1, "y": 0.1},
                    {"x": left + 0.1, "y": 0.3},
                    {"x": left, "y": 0.3},
                ],
            }
        )
    if items:
        result = client.put(
            f"/api/v1/cameras/{camera['id']}/spots/bulk",
            headers=admin,
            json={"items": items},
        )
        assert result.status_code == 200, result.text
    return camera["id"]


def upload(
    client: TestClient,
    headers: dict[str, str],
    camera_id: str,
    image: bytes | None = None,
    **data,
):
    return client.post(
        "/api/v1/snapshots/predict",
        headers=headers,
        data={"camera_id": camera_id, **data},
        files={
            "file": ("scene.png", png_bytes() if image is None else image, "image/png")
        },
    )


def test_valid_png_without_model_saves_unknown_predictions_and_original(context):
    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=2)
    original = png_bytes()

    response = upload(client, admin, camera_id, original)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["camera_id"] == camera_id
    assert body["total_spots"] == 2
    assert (body["empty_count"], body["occupied_count"], body["unknown_count"]) == (
        0,
        0,
        2,
    )
    assert body["alert_state"] == "NONE"
    assert body["model_version"] is None
    assert body["processing_time_ms"] >= 0
    assert len(body["predictions"]) == 2
    assert all(item["predicted_status"] == "unknown" for item in body["predictions"])
    assert all(
        item["reason_code"] == "MODEL_UNAVAILABLE" for item in body["predictions"]
    )
    assert all(len(item["polygon"]) == 4 for item in body["predictions"])
    assert client.get(body["image_url"]).status_code == 401
    image_response = client.get(body["image_url"], headers=admin)
    assert image_response.status_code == 200
    assert image_response.content == original
    with Session(engine) as session:
        snapshot = session.scalar(select(Snapshot))
        assert snapshot is not None
        assert snapshot.camera_id == camera_id or str(snapshot.camera_id) == camera_id
        assert snapshot.sha256
        assert snapshot.byte_size == len(original)
        assert snapshot.width == 64 and snapshot.height == 64
        assert len(session.scalars(select(SpotPrediction)).all()) == 2
    assert len(list((tmp_path / "private-images").iterdir())) == 1


def test_saved_snapshot_detail_retains_original_prediction_and_polygon(context):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    created = upload(client, admin, camera_id)
    assert created.status_code == 201
    snapshot_id = created.json()["snapshot_id"]
    assert client.get(f"/api/v1/snapshots/{snapshot_id}").status_code == 401
    detail = client.get(f"/api/v1/snapshots/{snapshot_id}", headers=admin)
    assert detail.status_code == 200
    assert detail.json()["snapshot_id"] == snapshot_id
    assert (
        detail.json()["predictions"][0]["polygon"]
        == created.json()["predictions"][0]["polygon"]
    )
    assert detail.json()["predictions"][0]["predicted_status"] == "unknown"


def test_upload_openapi_describes_multipart_and_actual_error_envelope(context):
    client, _, _, _ = context
    operation = client.get("/openapi.json").json()["paths"][
        "/api/v1/snapshots/predict"
    ]["post"]
    assert "multipart/form-data" in operation["requestBody"]["content"]
    assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ApiErrorResponse"
    }


def test_occupancy_is_stale_without_snapshot_and_reads_latest_capture(context):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    path = "/api/v1/lots/current/occupancy"
    before = client.get(path, headers=admin)
    assert before.status_code == 200
    assert before.json()["snapshot_id"] is None
    assert before.json()["counts"] is None
    assert before.json()["alert_state"] == "STALE"

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    uploaded = upload(client, admin, camera_id, captured_at=old)
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["alert_state"] == "STALE"
    latest = client.get(path, headers=admin)
    assert latest.status_code == 200
    assert latest.json()["snapshot_id"] == uploaded.json()["snapshot_id"]
    assert latest.json()["counts"]["unknown"] == 1
    assert latest.json()["alert_state"] == "STALE"


@pytest.mark.parametrize(
    ("statuses", "expected_alert", "expected_percentage"),
    [
        (["occupied", "occupied"], "FULL", 100.0),
        (["occupied", "empty"], "NONE", 50.0),
        (["occupied", "unknown"], "NONE", None),
        ([], "NONE", None),
    ],
)
def test_counts_reconcile_and_unknown_or_zero_spots_never_full(
    context, monkeypatch, statuses, expected_alert, expected_percentage
):
    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin, spots=len(statuses))

    def predicted(_image, spots, _settings):
        assert len(spots) == len(statuses)
        return [
            snapshot_api.Verdict(
                status,
                0.9 if status != "unknown" else None,
                "test-model-version" if status != "unknown" else None,
                None if status != "unknown" else "MODEL_UNAVAILABLE",
            )
            for status in statuses
        ]

    monkeypatch.setattr(snapshot_api, "_predict", predicted)
    response = upload(client, admin, camera_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_spots"] == len(statuses)
    assert body["empty_count"] + body["occupied_count"] + body["unknown_count"] == len(
        statuses
    )
    assert body["alert_state"] == expected_alert
    assert body["occupancy_percent"] == expected_percentage
    assert (
        client.get("/api/v1/lots/current/occupancy", headers=admin).json()[
            "alert_state"
        ]
        == expected_alert
    )
    with Session(engine) as session:
        assert [
            p.prediction_status for p in session.scalars(select(SpotPrediction)).all()
        ] == statuses


def test_stale_suppresses_full_for_old_capture(context, monkeypatch):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    monkeypatch.setattr(
        snapshot_api,
        "_predict",
        lambda *_: [snapshot_api.Verdict("occupied", 0.99, "test-model", None)],
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    response = upload(client, admin, camera_id, captured_at=old)
    assert response.status_code == 201, response.text
    assert response.json()["alert_state"] == "STALE"


def test_model_runtime_failure_saves_explicit_unknown_without_changing_history(
    context, monkeypatch
):
    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    first = upload(client, admin, camera_id)
    assert first.status_code == 201
    client.app.state.settings.parking_model_checkpoint = tmp_path / "model.pt"

    class FailingPredictor:
        def predict_spots(self, _image, _regions):
            raise RuntimeError("model runtime failed")

    monkeypatch.setattr(snapshot_api, "_model", lambda *_: FailingPredictor())
    failed = upload(client, admin, camera_id)
    assert failed.status_code == 201, failed.text
    assert failed.json()["predictions"][0]["reason_code"] == "INFERENCE_ERROR"
    assert failed.json()["predictions"][0]["confidence"] is None
    with Session(engine) as session:
        assert len(session.scalars(select(Snapshot)).all()) == 2
        predictions = session.scalars(
            select(SpotPrediction).order_by(SpotPrediction.inferred_at)
        ).all()
        assert len(predictions) == 2
        assert all(item.prediction_status == "unknown" for item in predictions)
    assert len(list((tmp_path / "private-images").iterdir())) == 2


def test_model_low_confidence_remains_unknown_with_model_provenance(
    context, monkeypatch
):
    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    client.app.state.settings.parking_model_checkpoint = tmp_path / "configured.pt"

    class LowConfidencePredictor:
        def predict_spots(self, _image, regions):
            return [
                SimpleNamespace(
                    spot_id=regions[0]["spot_id"],
                    predicted_status="unknown",
                    confidence=0.52,
                    model_version="sha256:synthetic-smoke",
                )
            ]

    monkeypatch.setattr(snapshot_api, "_model", lambda *_: LowConfidencePredictor())
    response = upload(client, admin, camera_id)
    assert response.status_code == 201, response.text
    prediction = response.json()["predictions"][0]
    assert prediction["predicted_status"] == "unknown"
    assert prediction["confidence"] == 0.52
    assert prediction["model_version"] == "sha256:synthetic-smoke"
    assert prediction["reason_code"] == "LOW_CONFIDENCE"
    assert response.json()["unknown_count"] == 1
    assert response.json()["occupancy_percent"] is None
    with Session(engine) as session:
        stored = session.scalar(select(SpotPrediction))
        assert stored.prediction_status == "unknown"
        assert stored.confidence == 0.52
        assert stored.reason_code == "LOW_CONFIDENCE"


def test_missing_configured_checkpoint_is_explicitly_unavailable(context):
    client, _, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    client.app.state.settings.parking_model_checkpoint = tmp_path / "missing.pt"
    response = upload(client, admin, camera_id)
    assert response.status_code == 201, response.text
    assert response.json()["predictions"][0]["reason_code"] == "MODEL_UNAVAILABLE"
    assert response.json()["model_version"] is None


def test_upload_rejects_oversize_mismatch_and_corrupt_bytes_without_history(context):
    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    client.app.state.settings.max_upload_bytes = 10
    too_large = upload(client, admin, camera_id)
    assert too_large.status_code == 413
    client.app.state.settings.max_upload_bytes = 1024 * 1024
    mismatch = client.post(
        "/api/v1/snapshots/predict",
        headers=admin,
        data={"camera_id": camera_id},
        files={"file": ("scene.jpg", png_bytes(), "image/jpeg")},
    )
    assert mismatch.status_code == 415
    corrupt = upload(client, admin, camera_id, b"not actually an image")
    assert corrupt.status_code == 422
    assert corrupt.json()["error"]["code"] == "INVALID_IMAGE"
    with Session(engine) as session:
        assert session.scalars(select(Snapshot)).all() == []
    assert not (tmp_path / "private-images").exists()


def test_capture_time_must_be_timezone_aware_and_not_future(context):
    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    naive = upload(client, admin, camera_id, captured_at="2026-10-26T10:00:00")
    future = upload(
        client,
        admin,
        camera_id,
        captured_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    assert naive.status_code == 422
    assert future.status_code == 422
    with Session(engine) as session:
        assert session.scalars(select(Snapshot)).all() == []


def test_valid_jpeg_preserves_original_bytes(context):
    from PIL import Image

    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "navy").save(buffer, format="JPEG")
    original = buffer.getvalue()
    response = client.post(
        "/api/v1/snapshots/predict",
        headers=admin,
        data={"camera_id": camera_id},
        files={"file": ("scene.jpeg", original, "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    image = client.get(response.json()["image_url"], headers=admin)
    assert image.headers["content-type"].startswith("image/jpeg")
    assert image.content == original
    with Session(engine) as session:
        assert session.scalar(select(Snapshot)).mime_type == "image/jpeg"


def test_unwritable_image_root_leaves_no_snapshot_or_prediction(context):
    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    client.app.state.settings.image_storage_root = blocked
    response = upload(client, admin, camera_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    with Session(engine) as session:
        assert session.scalars(select(Snapshot)).all() == []
        assert session.scalars(select(SpotPrediction)).all() == []


def test_ambiguous_commit_keeps_original_if_database_commit_succeeded(
    context, monkeypatch
):
    from PIL import Image

    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    original = png_bytes()
    image = Image.open(BytesIO(original))
    image.load()
    with Session(engine) as session:
        camera = session.get(Camera, UUID(camera_id))
        spot = session.scalar(select(ParkingSpot))
        revision = session.scalar(select(PolygonRevision))
        user = session.scalar(select(User).where(User.username == "admin"))
        real_commit = session.commit

        def commit_then_lose_acknowledgement():
            real_commit()
            raise SQLAlchemyError("commit acknowledgement was lost")

        monkeypatch.setattr(session, "commit", commit_then_lose_acknowledgement)
        with pytest.raises(ApiError):
            snapshot_api._save(
                session,
                client.app.state.settings,
                camera=camera,
                user=user,
                captured_at=datetime.now(timezone.utc),
                image=image,
                data=original,
                mime_type="image/png",
                spots=[snapshot_api.CaptureSpot(spot.id, revision.id, revision.points)],
                verdicts=[
                    snapshot_api.Verdict("unknown", None, None, "MODEL_UNAVAILABLE")
                ],
                processing_time_ms=1.0,
            )
    with Session(engine) as session:
        stored = session.scalar(select(Snapshot))
        assert stored is not None
        assert (
            tmp_path / "private-images" / stored.original_key
        ).read_bytes() == original


def test_stale_boundary_is_strictly_greater_than_configured_seconds():
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    assert (
        snapshot_api._alert(
            total=1,
            empty=0,
            unknown=0,
            captured_at=now - timedelta(seconds=300),
            now=now,
            stale_after_seconds=300,
        )
        == "FULL"
    )
    assert (
        snapshot_api._alert(
            total=1,
            empty=0,
            unknown=0,
            captured_at=now - timedelta(seconds=301),
            now=now,
            stale_after_seconds=300,
        )
        == "STALE"
    )


def test_database_outage_has_safe_service_unavailable_response(context, monkeypatch):
    client, _, admin, _ = context

    def unavailable(_url):
        raise SQLAlchemyError("internal database details")

    monkeypatch.setattr(db_module, "get_engine", unavailable)
    response = client.get("/api/v1/spots", headers=admin)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["error"]["request_id"]
    assert "internal database details" not in response.text


def test_camera_selection_and_authentication_are_checked_before_save(context):
    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    assert upload(client, {}, camera_id).status_code == 401
    unknown_camera = upload(client, admin, "00000000-0000-0000-0000-000000000001")
    assert unknown_camera.status_code == 404
    client.patch(
        f"/api/v1/cameras/{camera_id}", headers=admin, json={"is_active": False}
    )
    assert upload(client, admin, camera_id).status_code == 409
    with Session(engine) as session:
        assert session.scalars(select(Snapshot)).all() == []


def test_operator_can_upload_but_inactive_spots_are_not_classified(context):
    client, engine, admin, _ = context
    camera_id = configured_camera(client, admin, spots=2)
    spots = client.get(f"/api/v1/cameras/{camera_id}/spots", headers=admin).json()[
        "items"
    ]
    disabled = client.patch(
        f"/api/v1/spots/{spots[1]['id']}", headers=admin, json={"is_active": False}
    )
    assert disabled.status_code == 200
    created = client.post(
        "/api/v1/users",
        headers=admin,
        json={
            "username": "operator",
            "password": "Correct-horse-operator-2026",
            "role": "operator",
        },
    )
    assert created.status_code == 201
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "Correct-horse-operator-2026"},
    ).json()["access_token"]
    response = upload(client, {"Authorization": f"Bearer {token}"}, camera_id)
    assert response.status_code == 201, response.text
    assert response.json()["total_spots"] == 1
    assert response.json()["predictions"][0]["spot_id"] == spots[0]["id"]
    with Session(engine) as session:
        assert len(session.scalars(select(SpotPrediction)).all()) == 1


def test_new_capture_supersedes_older_stale_snapshot(context):
    client, _, admin, _ = context
    camera_id = configured_camera(client, admin, spots=1)
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert (
        upload(client, admin, camera_id, captured_at=old).json()["alert_state"]
        == "STALE"
    )
    fresh = upload(client, admin, camera_id)
    assert fresh.status_code == 201
    latest = client.get("/api/v1/lots/current/occupancy", headers=admin)
    assert latest.status_code == 200
    assert latest.json()["snapshot_id"] == fresh.json()["snapshot_id"]
    assert latest.json()["alert_state"] == "NONE"


def test_configured_checkpoint_runs_real_model_on_synthetic_smoke_image(context):
    torch = pytest.importorskip("torch")
    from models.mobilenet_classifier import build_model, save_checkpoint

    client, engine, admin, tmp_path = context
    camera_id = configured_camera(client, admin, spots=1)
    model = build_model(pretrained=False)
    model.classifier[-1].weight.data.zero_()
    model.classifier[-1].bias.data.copy_(torch.tensor([3.0, -3.0]))
    checkpoint = tmp_path / "synthetic-smoke.pt"
    save_checkpoint(
        checkpoint,
        model,
        {
            "scope": "synthetic_smoke_only",
            "model_architecture": "torchvision.mobilenet_v3_small",
            "class_mapping": {"empty": 0, "occupied": 1},
            "preprocessing": {
                "image_size": 32,
                "imagenet_normalization": False,
                "mean": [0.0, 0.0, 0.0],
                "std": [1.0, 1.0, 1.0],
                "polygon_crop": "masked_tight_square_pad",
            },
        },
    )
    client.app.state.settings.parking_model_checkpoint = checkpoint
    response = upload(client, admin, camera_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["empty_count"] == 1
    assert body["occupied_count"] == 0
    assert body["unknown_count"] == 0
    assert body["predictions"][0]["confidence"] > 0.9
    assert body["model_version"].startswith("sha256:")
    assert body["predictions"][0]["model_version"] == body["model_version"]
    with Session(engine) as session:
        prediction = session.scalar(select(SpotPrediction))
        assert prediction.prediction_status == "empty"
        assert prediction.model_version == body["model_version"]
