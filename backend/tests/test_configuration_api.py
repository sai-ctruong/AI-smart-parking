"""Configuration API contracts against a disposable, migrated database."""

import hashlib
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from alembic import command
from app.bootstrap_admin import bootstrap_admin
from app.config import DevelopmentSettings
from app.main import create_app
from app.models import AuditLog, Camera, ParkingSpot, PolygonRevision

SECRET = "test-only-configuration-secret-at-least-32-bytes"
PASSWORD = "Correct-horse-admin-2026"
REFERENCE_A = {"sha256": "a" * 64, "width": 1200, "height": 800}
REFERENCE_B = {"sha256": "b" * 64, "width": 1200, "height": 800}


@pytest.fixture
def context(tmp_path: Path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'configuration.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    engine = create_engine(url)
    with Session(engine) as session:
        admin = bootstrap_admin(session, "admin", PASSWORD)
        session.commit()
        admin_id = admin.id
    settings = DevelopmentSettings(
        _env_file=None,
        database_url=url,
        auth_secret_key=SECRET,
        cors_origins=["http://localhost:5173"],
        image_storage_root=tmp_path / "images",
    )
    with TestClient(create_app(settings)) as client:
        token = client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["access_token"]
        yield client, engine, {"Authorization": f"Bearer {token}"}, admin_id
    engine.dispose()


def configure(client: TestClient, headers: dict[str, str]):
    lot = client.post("/api/v1/lots", headers=headers, json={"name": "Main lot"})
    assert lot.status_code == 201, lot.text
    camera = client.post(
        f"/api/v1/lots/{lot.json()['id']}/cameras",
        headers=headers,
        json={"name": "Entrance camera", "reference_image": REFERENCE_A},
    )
    assert camera.status_code == 201, camera.text
    return lot.json(), camera.json()


def rectangle(x: float, y: float, size: float = 0.04):
    return [
        {"x": x, "y": y},
        {"x": x + size, "y": y},
        {"x": x + size, "y": y + size},
        {"x": x, "y": y + size},
    ]


def test_reference_image_upload_is_private_and_matches_camera_metadata(context):
    client, _, admin, _ = context
    image = Image.new("RGB", (640, 480), "#364c53")
    output = BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    reference = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": 640,
        "height": 480,
    }
    lot = client.post("/api/v1/lots", headers=admin, json={"name": "Main lot"}).json()
    camera = client.post(
        f"/api/v1/lots/{lot['id']}/cameras",
        headers=admin,
        json={"name": "Entrance camera", "reference_image": reference},
    ).json()
    url = f"/api/v1/cameras/{camera['id']}/reference-image"

    assert client.get(url).status_code == 401
    assert client.get(url, headers=admin).status_code == 404
    assert (
        client.put(
            url, headers=admin, files={"file": ("bad.jpg", data, "image/jpeg")}
        ).status_code
        == 415
    )
    wrong = client.put(
        url,
        headers=admin,
        files={"file": ("wrong.png", BytesIO(b"not an image"), "image/png")},
    )
    assert wrong.status_code == 422
    other = BytesIO()
    Image.new("RGB", (640, 480), "#365d53").save(other, format="PNG")
    mismatch = client.put(
        url,
        headers=admin,
        files={"file": ("other.png", other.getvalue(), "image/png")},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "REFERENCE_MISMATCH"
    saved = client.put(
        url, headers=admin, files={"file": ("reference.png", data, "image/png")}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["sha256"] == reference["sha256"]
    loaded = client.get(url, headers=admin)
    assert loaded.status_code == 200
    assert loaded.headers["content-type"] == "image/png"
    assert loaded.content == data

    client.post(
        "/api/v1/users",
        headers=admin,
        json={
            "username": "operator",
            "password": "Correct-horse-operator-2026",
            "role": "operator",
        },
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "Correct-horse-operator-2026"},
    ).json()["access_token"]
    operator = {"Authorization": f"Bearer {token}"}
    assert (
        client.put(
            url, headers=operator, files={"file": ("reference.png", data, "image/png")}
        ).status_code
        == 403
    )
    assert client.get(url, headers=operator).content == data


def test_reference_upload_rejects_exif_rotation_that_would_shift_polygons(context):
    client, _, admin, _ = context
    output = BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (640, 480), "#364c53").save(output, format="JPEG", exif=exif)
    data = output.getvalue()
    lot = client.post("/api/v1/lots", headers=admin, json={"name": "Main lot"}).json()
    camera = client.post(
        f"/api/v1/lots/{lot['id']}/cameras",
        headers=admin,
        json={
            "name": "Entrance",
            "reference_image": {
                "sha256": hashlib.sha256(data).hexdigest(),
                "width": 640,
                "height": 480,
            },
        },
    ).json()
    response = client.put(
        f"/api/v1/cameras/{camera['id']}/reference-image",
        headers=admin,
        files={"file": ("rotated.jpg", data, "image/jpeg")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IMAGE"


def test_lot_camera_crud_and_singleton_with_rbac(context):
    client, _, admin, _ = context
    assert client.post("/api/v1/lots", json={"name": "Forbidden"}).status_code == 401
    lot, camera = configure(client, admin)
    assert (
        client.post("/api/v1/lots", headers=admin, json={"name": "Other"}).status_code
        == 409
    )
    assert client.get("/api/v1/lots/current", headers=admin).json()["id"] == lot["id"]
    assert (
        client.get("/api/v1/cameras/current", headers=admin).json()["id"]
        == camera["id"]
    )
    assert (
        client.patch(
            f"/api/v1/lots/{lot['id']}", headers=admin, json={"name": "Updated lot"}
        ).json()["name"]
        == "Updated lot"
    )
    operator = client.post(
        "/api/v1/users",
        headers=admin,
        json={
            "username": "operator",
            "password": "Correct-horse-operator-2026",
            "role": "operator",
        },
    )
    assert operator.status_code == 201
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "Correct-horse-operator-2026"},
    ).json()["access_token"]
    operator_header = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/spots", headers=operator_header).status_code == 200
    assert (
        client.patch(
            f"/api/v1/cameras/{camera['id']}",
            headers=operator_header,
            json={"name": "Illegal"},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/v1/lots/{lot['id']}", headers=admin).status_code == 409
    assert (
        client.delete(f"/api/v1/cameras/{camera['id']}", headers=admin).status_code
        == 204
    )
    assert client.delete(f"/api/v1/lots/{lot['id']}", headers=admin).status_code == 204


def test_bulk_eleven_spots_reload_stable_ids_and_revisions(context):
    client, engine, admin, admin_id = context
    _, camera = configure(client, admin)
    items = [
        {"code": f"S{index:02d}", "points": rectangle(0.05 + index * 0.08, 0.1)}
        for index in range(11)
    ]
    created = client.put(
        f"/api/v1/cameras/{camera['id']}/spots/bulk",
        headers=admin,
        json={"items": items},
    )
    assert created.status_code == 200, created.text
    spots = created.json()["items"]
    assert len(spots) == 11
    assert len({spot["id"] for spot in spots}) == 11
    assert [spot["polygon"]["points"] for spot in spots] == [
        item["points"] for item in items
    ]
    assert all(
        spot["polygon"]["reference_image"]["sha256"] == "a" * 64 for spot in spots
    )
    loaded = client.get("/api/v1/spots", headers=admin).json()["items"]
    assert {spot["id"] for spot in loaded} == {spot["id"] for spot in spots}
    updated = client.put(
        f"/api/v1/cameras/{camera['id']}/spots/bulk",
        headers=admin,
        json={
            "items": [
                {"id": spots[0]["id"], "code": "S00", "points": rectangle(0.06, 0.2)}
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["items"][0]["id"] == spots[0]["id"]
    assert updated.json()["items"][0]["polygon"]["revision_no"] == 2
    assert client.get(
        f"/api/v1/spots/{spots[0]['id']}/revisions", headers=admin
    ).json()["items"][0]["created_by"] == str(admin_id)
    with Session(engine) as session:
        assert (
            session.scalar(select(ParkingSpot).where(ParkingSpot.code == "S00"))
            is not None
        )
        assert len(session.scalars(select(PolygonRevision)).all()) == 12
        assert session.scalar(
            select(AuditLog).where(AuditLog.action == "config.spots.bulk")
        )


@pytest.mark.parametrize(
    "points",
    [
        [{"x": -0.1, "y": 0.1}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.2}],
        [
            {"x": 0.1, "y": 0.1},
            {"x": 0.2, "y": 0.2},
            {"x": 0.1, "y": 0.2},
            {"x": 0.2, "y": 0.1},
        ],
        rectangle(0.1, 0.1, 0.00001),
    ],
)
def test_rejects_invalid_polygon_without_partial_insert(context, points):
    client, engine, admin, _ = context
    _, camera = configure(client, admin)
    response = client.put(
        f"/api/v1/cameras/{camera['id']}/spots/bulk",
        headers=admin,
        json={
            "items": [
                {"code": "GOOD", "points": rectangle(0.1, 0.1)},
                {"code": "BAD", "points": points},
            ]
        },
    )
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.scalars(select(ParkingSpot)).all() == []


def test_duplicate_code_and_polygon_overlap_are_explicit(context):
    client, _, admin, _ = context
    _, camera = configure(client, admin)
    path = f"/api/v1/cameras/{camera['id']}/spots/bulk"
    assert (
        client.put(
            path,
            headers=admin,
            json={"items": [{"code": "A1", "points": rectangle(0.1, 0.1)}]},
        ).status_code
        == 200
    )
    duplicate = client.put(
        path,
        headers=admin,
        json={"items": [{"code": "a1", "points": rectangle(0.2, 0.1)}]},
    )
    assert duplicate.status_code == 409
    exact = client.put(
        path,
        headers=admin,
        json={"items": [{"code": "B2", "points": rectangle(0.1, 0.1)}]},
    )
    assert exact.status_code == 422
    overlapping = client.put(
        path,
        headers=admin,
        json={"items": [{"code": "B2", "points": rectangle(0.12, 0.12)}]},
    )
    assert overlapping.status_code == 200
    assert any(w["code"] == "POLYGON_OVERLAP" for w in overlapping.json()["warnings"])


def test_adjacent_polygons_sharing_only_boundary_do_not_warn(context):
    client, _, admin, _ = context
    _, camera = configure(client, admin)
    result = client.put(
        f"/api/v1/cameras/{camera['id']}/spots/bulk",
        headers=admin,
        json={
            "items": [
                {"code": "A1", "points": rectangle(0.1, 0.1)},
                {"code": "A2", "points": rectangle(0.14, 0.1)},
            ]
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["warnings"] == []


def test_overlapping_rectangles_with_shared_horizontal_edges_warn(context):
    client, _, admin, _ = context
    _, camera = configure(client, admin)
    result = client.put(
        f"/api/v1/cameras/{camera['id']}/spots/bulk",
        headers=admin,
        json={
            "items": [
                {"code": "A1", "points": rectangle(0.1, 0.1)},
                {"code": "A2", "points": rectangle(0.12, 0.1)},
            ]
        },
    )
    assert result.status_code == 200, result.text
    assert len(result.json()["warnings"]) == 1


def test_single_spot_changes_reject_overlapping_active_geometry(context):
    client, _, admin, _ = context
    _, camera = configure(client, admin)
    path = f"/api/v1/cameras/{camera['id']}/spots"
    first = client.post(
        path, headers=admin, json={"code": "A1", "points": rectangle(0.1, 0.1)}
    )
    assert first.status_code == 201
    duplicate = client.post(
        path, headers=admin, json={"code": "A2", "points": rectangle(0.12, 0.1)}
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "OVERLAPPING_POLYGON"
    second = client.post(
        path, headers=admin, json={"code": "A2", "points": rectangle(0.3, 0.1)}
    )
    assert second.status_code == 201
    update = client.put(
        f"/api/v1/spots/{second.json()['id']}/polygon",
        headers={**admin, "If-Match": '"1"'},
        json={"points": rectangle(0.12, 0.1)},
    )
    assert update.status_code == 422
    assert update.json()["error"]["code"] == "OVERLAPPING_POLYGON"


def test_viewpoint_change_requires_explicit_invalidation_and_recalibration(context):
    client, engine, admin, _ = context
    _, camera = configure(client, admin)
    created = client.post(
        f"/api/v1/cameras/{camera['id']}/spots",
        headers=admin,
        json={"code": "A1", "points": rectangle(0.1, 0.1)},
    )
    assert created.status_code == 201, created.text
    spot = created.json()
    change = {"reference_image": REFERENCE_B}
    path = f"/api/v1/cameras/{camera['id']}"
    assert client.patch(path, headers=admin, json=change).status_code == 409
    changed = client.patch(
        path, headers=admin, json={**change, "invalidate_spots": True}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["viewpoint_version"] == 2
    stale = client.get(f"/api/v1/spots/{spot['id']}", headers=admin).json()
    assert stale["is_active"] is False
    assert stale["geometry_status"] == "needs_recalibration"
    assert (
        client.patch(
            f"/api/v1/spots/{spot['id']}", headers=admin, json={"is_active": True}
        ).status_code
        == 409
    )
    revised = client.put(
        f"/api/v1/spots/{spot['id']}/polygon",
        headers={**admin, "If-Match": '"1"'},
        json={"points": rectangle(0.15, 0.15)},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["id"] == spot["id"]
    assert revised.json()["is_active"] is True
    assert revised.json()["polygon"]["revision_no"] == 2
    assert revised.json()["polygon"]["reference_image"]["sha256"] == "b" * 64
    with Session(engine) as session:
        assert session.get(Camera, UUID(camera["id"])).viewpoint_version == 2


def test_polygon_revision_precondition_soft_delete_and_openapi(context):
    client, engine, admin, _ = context
    _, camera = configure(client, admin)
    created = client.post(
        f"/api/v1/cameras/{camera['id']}/spots",
        headers=admin,
        json={"code": "A1", "points": rectangle(0.1, 0.1)},
    ).json()
    path = f"/api/v1/spots/{created['id']}/polygon"
    assert (
        client.put(
            path, headers=admin, json={"points": rectangle(0.2, 0.2)}
        ).status_code
        == 428
    )
    assert (
        client.put(
            path,
            headers={**admin, "If-Match": '"0"'},
            json={"points": rectangle(0.2, 0.2)},
        ).status_code
        == 409
    )
    assert (
        client.delete(f"/api/v1/spots/{created['id']}", headers=admin).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/spots/{created['id']}", headers=admin).json()["is_active"]
        is False
    )
    with Session(engine) as session:
        assert session.get(ParkingSpot, UUID(created["id"])) is not None
        assert len(session.scalars(select(PolygonRevision)).all()) == 1
    spec = client.get("/openapi.json").json()
    assert spec["paths"][path.replace(created["id"], "{spot_id}")]["put"]["requestBody"]
    assert spec["paths"]["/api/v1/cameras/{camera_id}/spots/bulk"]["put"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    validation_schema = spec["paths"]["/api/v1/cameras/{camera_id}/spots/bulk"]["put"][
        "responses"
    ]["422"]["content"]["application/json"]["schema"]
    assert validation_schema == {"$ref": "#/components/schemas/ApiErrorResponse"}
    reference_path = spec["paths"]["/api/v1/cameras/{camera_id}/reference-image"]
    assert reference_path["put"]["requestBody"]["content"]["multipart/form-data"]
    assert "403" in reference_path["put"]["responses"]
    assert "415" in reference_path["put"]["responses"]
    assert "200" in reference_path["get"]["responses"]
