"""MVP persistence models; operational records never contain dataset labels."""

import math
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator

from app.db import Base


def _orientation(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _edges_intersect(a, b, c, d):
    def on_segment(p, q, r):
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and (
            min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    ac, ad = _orientation(a, b, c), _orientation(a, b, d)
    ca, cb = _orientation(c, d, a), _orientation(c, d, b)
    return (
        (ac * ad < 0 and ca * cb < 0)
        or (ac == 0 and on_segment(a, c, b))
        or (ad == 0 and on_segment(a, d, b))
        or (ca == 0 and on_segment(c, a, d))
        or (cb == 0 and on_segment(c, b, d))
    )


def validate_polygon(points: object) -> list[dict[str, float]]:
    """Validate ordered normalized vertices before persisting a revision."""
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("polygon must contain at least three vertices")
    vertices = []
    for point in points:
        if not isinstance(point, dict) or set(point) != {"x", "y"}:
            raise ValueError("polygon vertices must contain only x and y")
        x, y = point["x"], point["y"]
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not math.isfinite(x)
            or not math.isfinite(y)
            or not 0 <= x <= 1
            or not 0 <= y <= 1
        ):
            raise ValueError("polygon coordinates must be finite in [0,1]")
        vertices.append((float(x), float(y)))
    if len(set(vertices)) != len(vertices):
        raise ValueError("polygon vertices must be distinct")
    area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1])
    )
    if abs(area) < 1e-12:
        raise ValueError("polygon area must be positive")
    count = len(vertices)
    for first in range(count):
        for second in range(first + 2, count):
            if first == 0 and second == count - 1:
                continue
            if _edges_intersect(
                vertices[first],
                vertices[(first + 1) % count],
                vertices[second],
                vertices[(second + 1) % count],
            ):
                raise ValueError("polygon edges must not intersect")
    return [{"x": x, "y": y} for x, y in vertices]


class NormalizedPolygon(TypeDecorator):
    """Apply geometry validation to ORM and SQLAlchemy Core writes."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, _dialect):
        return validate_polygon(value)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'operator')", name="ck_users_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ParkingLot(Base):
    __tablename__ = "parking_lots"
    __table_args__ = (
        CheckConstraint("singleton_key = true", name="ck_parking_lots_singleton"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    singleton_key: Mapped[bool] = mapped_column(
        Boolean, nullable=False, unique=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cameras: Mapped[list["Camera"]] = relationship(back_populates="parking_lot")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    parking_lot_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("parking_lots.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    reference_image_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reference_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    viewpoint_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    parking_lot: Mapped[ParkingLot] = relationship(back_populates="cameras")
    spots: Mapped[list["ParkingSpot"]] = relationship(back_populates="camera")
    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="camera")


class ParkingSpot(Base):
    __tablename__ = "parking_spots"
    __table_args__ = (
        UniqueConstraint("camera_id", "code", name="uq_spots_camera_code"),
        UniqueConstraint("id", "camera_id", name="uq_spots_id_camera"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    camera: Mapped[Camera] = relationship(back_populates="spots")
    revisions: Mapped[list["PolygonRevision"]] = relationship(back_populates="spot")
    predictions: Mapped[list["SpotPrediction"]] = relationship(
        back_populates="spot", foreign_keys="SpotPrediction.spot_id"
    )


class PolygonRevision(Base):
    __tablename__ = "polygon_revisions"
    __table_args__ = (
        UniqueConstraint("spot_id", "revision_no", name="uq_revisions_spot_number"),
        UniqueConstraint("id", "spot_id", name="uq_revisions_id_spot"),
        CheckConstraint("revision_no > 0", name="ck_revisions_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    spot_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("parking_spots.id", ondelete="RESTRICT"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[list[dict]] = mapped_column(NormalizedPolygon, nullable=False)
    reference_image_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    reference_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_viewpoint_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    spot: Mapped[ParkingSpot] = relationship(back_populates="revisions")
    author: Mapped[User] = relationship(foreign_keys=[created_by])
    predictions: Mapped[list["SpotPrediction"]] = relationship(
        back_populates="polygon_revision",
        foreign_keys="SpotPrediction.polygon_revision_id",
    )

    @validates("points")
    def _validate_points(self, _key: str, value: object) -> list[dict[str, float]]:
        return validate_polygon(value)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("id", "camera_id", name="uq_snapshots_id_camera"),
        CheckConstraint("byte_size > 0", name="ck_snapshots_byte_size"),
        CheckConstraint("width > 0 AND height > 0", name="ck_snapshots_dimensions"),
        CheckConstraint("length(sha256) = 64", name="ck_snapshots_sha256_length"),
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png')", name="ck_snapshots_mime_type"
        ),
        Index("ix_snapshots_camera_captured", "camera_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    camera_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cameras.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    original_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    camera: Mapped[Camera] = relationship(back_populates="snapshots")
    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by])
    predictions: Mapped[list["SpotPrediction"]] = relationship(
        back_populates="snapshot", foreign_keys="SpotPrediction.snapshot_id"
    )


class SpotPrediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "camera_id"],
            ["snapshots.id", "snapshots.camera_id"],
            ondelete="RESTRICT",
            name="fk_predictions_snapshot_camera",
        ),
        ForeignKeyConstraint(
            ["spot_id", "camera_id"],
            ["parking_spots.id", "parking_spots.camera_id"],
            ondelete="RESTRICT",
            name="fk_predictions_spot_camera",
        ),
        ForeignKeyConstraint(
            ["polygon_revision_id", "spot_id"],
            ["polygon_revisions.id", "polygon_revisions.spot_id"],
            ondelete="RESTRICT",
            name="fk_predictions_revision_spot",
        ),
        UniqueConstraint("snapshot_id", "spot_id", name="uq_predictions_snapshot_spot"),
        CheckConstraint(
            "prediction_status IN ('empty', 'occupied', 'unknown')",
            name="ck_predictions_status",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_predictions_confidence",
        ),
        CheckConstraint(
            "(confidence IS NOT NULL AND model_version IS NOT NULL AND "
            "length(model_version) > 0) OR (confidence IS NULL AND "
            "model_version IS NULL AND prediction_status = 'unknown' AND "
            "reason_code IS NOT NULL)",
            name="ck_predictions_model_provenance",
        ),
        Index("ix_predictions_snapshot", "snapshot_id"),
        Index("ix_predictions_revision", "polygon_revision_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    spot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    polygon_revision_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    camera_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    prediction_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    snapshot: Mapped[Snapshot] = relationship(
        back_populates="predictions", foreign_keys=[snapshot_id]
    )
    spot: Mapped[ParkingSpot] = relationship(
        back_populates="predictions", foreign_keys=[spot_id]
    )
    polygon_revision: Mapped[PolygonRevision] = relationship(
        back_populates="predictions", foreign_keys=[polygon_revision_id]
    )
    reviews: Mapped[list["SpotReview"]] = relationship(back_populates="prediction")


class SpotReview(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint(
            "reviewed_status IN ('empty', 'occupied', 'unknown')",
            name="ck_reviews_status",
        ),
        Index("ix_reviews_prediction_reviewed", "prediction_id", "reviewed_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prediction_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("predictions.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    prediction: Mapped[SpotPrediction] = relationship(back_populates="reviews")
    reviewer: Mapped[User] = relationship(foreign_keys=[reviewed_by])


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
