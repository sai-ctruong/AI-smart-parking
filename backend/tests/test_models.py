"""Schema contracts against a fresh, disposable migrated database."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from alembic import command
from app.models import (
    AuditLog,
    Camera,
    ParkingLot,
    ParkingSpot,
    PolygonRevision,
    Snapshot,
    SpotPrediction,
    SpotReview,
    User,
)


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'schema.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    yield engine
    engine.dispose()


def _seed(session: Session):
    admin = User(username="admin", password_hash="hashed", role="admin")
    lot = ParkingLot(name="Main", singleton_key=True)
    camera = Camera(name="Entry", parking_lot=lot)
    spot = ParkingSpot(code="A1", camera=camera)
    revision = PolygonRevision(
        spot=spot,
        revision_no=1,
        points=[
            {"x": 0.1, "y": 0.2},
            {"x": 0.3, "y": 0.2},
            {"x": 0.3, "y": 0.5},
            {"x": 0.1, "y": 0.5},
        ],
        author=admin,
    )
    snapshot = Snapshot(
        camera=camera,
        uploader=admin,
        captured_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        original_key="private/snapshot-1.jpg",
        sha256="a" * 64,
        mime_type="image/jpeg",
        byte_size=1024,
        width=1280,
        height=720,
    )
    session.add_all([admin, lot, camera, spot, revision, snapshot])
    session.flush()
    return admin, lot, camera, spot, revision, snapshot


def test_migrated_schema_persists_relationships_and_review_provenance(engine) -> None:
    with Session(engine) as session:
        admin, lot, camera, spot, revision, snapshot = _seed(session)
        prediction = SpotPrediction(
            snapshot=snapshot,
            spot=spot,
            polygon_revision=revision,
            camera_id=camera.id,
            prediction_status="empty",
            confidence=0.82,
            model_version="sha256:model-v1",
            review_version=1,
        )
        session.add(prediction)
        session.flush()
        session.add_all(
            [
                SpotReview(
                    prediction=prediction,
                    reviewer=admin,
                    reviewed_status="occupied",
                    revision_no=1,
                    note="Vehicle visible",
                ),
                AuditLog(
                    actor=admin,
                    action="review.created",
                    target_type="prediction",
                    target_id=prediction.id,
                ),
            ]
        )
        session.commit()
        session.expire_all()

        stored = session.scalar(select(SpotPrediction))
        assert lot.cameras[0].spots[0].revisions[0].id == revision.id
        assert snapshot.predictions[0].spot_id == spot.id
        assert stored.prediction_status == "empty"
        assert stored.reviews[0].reviewed_status == "occupied"
        assert stored.model_version == "sha256:model-v1"
        assert stored.snapshot.original_key == "private/snapshot-1.jpg"
        assert session.scalar(select(AuditLog)).actor_id == admin.id


def test_invalid_keys_and_cross_camera_prediction_are_rejected(engine) -> None:
    with Session(engine) as session:
        admin, lot, camera, spot, revision, snapshot = _seed(session)
        other_camera = Camera(name="Other", parking_lot_id=lot.id)
        session.add(other_camera)
        with pytest.raises(IntegrityError):
            session.flush()  # One camera per lot.
        session.rollback()

    with Session(engine) as session:
        admin, _, camera, spot, revision, snapshot = _seed(session)
        prediction = SpotPrediction(
            snapshot_id=snapshot.id,
            spot_id=spot.id,
            polygon_revision_id=revision.id,
            camera_id=admin.id,  # No matching camera/spot/snapshot pair.
            prediction_status="occupied",
            confidence=0.9,
            model_version="v1",
        )
        session.add(prediction)
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize(
    "points",
    [
        [{"x": 0, "y": 0}, {"x": 1.1, "y": 0}, {"x": 1, "y": 1}],
        [{"x": 0, "y": 0}, {"x": 0.5, "y": 0.5}, {"x": 1, "y": 1}],
        [{"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 1, "y": 0}, {"x": 0, "y": 1}],
    ],
)
def test_invalid_normalized_polygon_is_rejected(points) -> None:
    with pytest.raises(ValueError, match="polygon"):
        PolygonRevision(revision_no=1, points=points)


def test_core_insert_cannot_bypass_polygon_validation(engine) -> None:
    with Session(engine) as session:
        admin, _, _, spot, _, _ = _seed(session)
        with pytest.raises(StatementError, match="polygon"):
            session.execute(
                PolygonRevision.__table__.insert().values(
                    spot_id=spot.id,
                    revision_no=2,
                    points=[
                        {"x": 0, "y": 0},
                        {"x": 2, "y": 0},
                        {"x": 1, "y": 1},
                    ],
                    created_by=admin.id,
                )
            )


def test_confidence_and_status_constraints_are_enforced(engine) -> None:
    with Session(engine) as session:
        _, _, camera, spot, revision, snapshot = _seed(session)
        session.add(
            SpotPrediction(
                snapshot=snapshot,
                spot=spot,
                polygon_revision=revision,
                camera_id=camera.id,
                prediction_status="empty",
                confidence=1.2,
                model_version="v1",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_prediction_cannot_reference_another_spots_polygon(engine) -> None:
    with Session(engine) as session:
        admin, _, camera, spot, _, snapshot = _seed(session)
        other_spot = ParkingSpot(code="A2", camera=camera)
        other_revision = PolygonRevision(
            spot=other_spot,
            author=admin,
            revision_no=1,
            points=[
                {"x": 0.5, "y": 0.1},
                {"x": 0.7, "y": 0.1},
                {"x": 0.7, "y": 0.3},
            ],
        )
        session.add(other_revision)
        session.flush()
        session.add(
            SpotPrediction(
                snapshot_id=snapshot.id,
                camera_id=camera.id,
                spot_id=spot.id,
                polygon_revision_id=other_revision.id,
                prediction_status="unknown",
                confidence=None,
                model_version=None,
                reason_code="MODEL_UNAVAILABLE",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_unknown_without_model_requires_reason(engine) -> None:
    with Session(engine) as session:
        _, _, camera, spot, revision, snapshot = _seed(session)
        session.add(
            SpotPrediction(
                snapshot=snapshot,
                camera_id=camera.id,
                spot=spot,
                polygon_revision=revision,
                prediction_status="unknown",
                confidence=None,
                model_version=None,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_historical_rows_prevent_parent_deletion(engine) -> None:
    with Session(engine) as session:
        _, _, _, spot, _, _ = _seed(session)
        session.commit()
        session.delete(spot)
        with pytest.raises(IntegrityError):
            session.flush()
