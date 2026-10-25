"""Admin configuration of the MVP lot, fixed camera, and spot geometry."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ApiError, get_auth_session, get_current_user, require_admin
from app.models import (
    AuditLog,
    Camera,
    ParkingLot,
    ParkingSpot,
    PolygonRevision,
    Snapshot,
    User,
    validate_polygon,
)


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any]
    request_id: str


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


router = APIRouter(
    prefix="/api/v1",
    tags=["Parking configuration"],
    responses={
        401: {"model": ApiErrorResponse, "description": "Authentication required"},
        403: {
            "model": ApiErrorResponse,
            "description": "Admin permission required on writes",
        },
        404: {"model": ApiErrorResponse, "description": "Resource not found"},
        409: {
            "model": ApiErrorResponse,
            "description": "Configuration or revision conflict",
        },
        422: {"model": ApiErrorResponse, "description": "Invalid request or polygon"},
        428: {
            "model": ApiErrorResponse,
            "description": "Polygon revision precondition required",
        },
        503: {
            "model": ApiErrorResponse,
            "description": "Configuration database unavailable",
        },
    },
)
Admin = Annotated[User, Depends(require_admin)]
Viewer = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_auth_session)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceImage(InputModel):
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    width: int = Field(ge=2)
    height: int = Field(ge=2)

    @field_validator("sha256")
    @classmethod
    def lowercase_digest(cls, value: str) -> str:
        return value.lower()


class LotCreate(InputModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class LotPatch(LotCreate):
    pass


class LotOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime


class CameraCreate(LotCreate):
    reference_image: ReferenceImage


class CameraPatch(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    reference_image: ReferenceImage | None = None
    invalidate_spots: bool = False

    @field_validator("name")
    @classmethod
    def clean_optional_name(cls, value: str | None) -> str | None:
        return LotCreate.clean_name(value) if value is not None else None


class CameraOut(BaseModel):
    id: UUID
    parking_lot_id: UUID
    name: str
    is_active: bool
    reference_image: ReferenceImage | None
    viewpoint_version: int
    created_at: datetime


class PolygonOut(BaseModel):
    id: UUID
    revision_no: int
    points: list[dict[str, float]]
    reference_image: ReferenceImage | None
    camera_viewpoint_version: int | None
    created_by: UUID
    created_at: datetime


class SpotOut(BaseModel):
    id: UUID
    camera_id: UUID
    code: str
    is_active: bool
    geometry_status: Literal["current", "needs_recalibration", "legacy_missing"]
    polygon: PolygonOut | None
    created_at: datetime


class SpotList(BaseModel):
    items: list[SpotOut]


class RevisionList(BaseModel):
    items: list[PolygonOut]


class SpotCreate(InputModel):
    code: str = Field(min_length=1, max_length=40)
    points: list[dict[str, Any]] = Field(min_length=3)

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not code:
            raise ValueError("code must not be blank")
        return code


class SpotBulkItem(SpotCreate):
    id: UUID | None = None


class SpotBulk(InputModel):
    items: list[SpotBulkItem] = Field(min_length=1, max_length=100)


class SpotPatch(InputModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def clean_optional_code(cls, value: str | None) -> str | None:
        return SpotCreate.clean_code(value) if value is not None else None


class PolygonReplace(InputModel):
    points: list[dict[str, Any]] = Field(min_length=3)


class GeometryWarning(BaseModel):
    code: Literal["POLYGON_OVERLAP"]
    spot_ids: list[UUID]


class BulkResult(BaseModel):
    items: list[SpotOut]
    warnings: list[GeometryWarning]


def _audit(
    session: Session, actor: User, action: str, target_type: str, target_id: UUID
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
    )


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            409, "CONFLICT", "Configuration conflicts with existing data"
        ) from exc


def _lot(session: Session, lot_id: UUID) -> ParkingLot:
    lot = session.get(ParkingLot, lot_id)
    if lot is None:
        raise ApiError(404, "NOT_FOUND", "Parking lot not found")
    return lot


def _camera(session: Session, camera_id: UUID) -> Camera:
    camera = session.get(Camera, camera_id)
    if camera is None:
        raise ApiError(404, "NOT_FOUND", "Camera not found")
    return camera


def _spot(session: Session, spot_id: UUID) -> ParkingSpot:
    spot = session.get(ParkingSpot, spot_id)
    if spot is None:
        raise ApiError(404, "NOT_FOUND", "Parking spot not found")
    return spot


def _reference(camera_or_revision: Camera | PolygonRevision) -> ReferenceImage | None:
    if camera_or_revision.reference_image_sha256 is None:
        return None
    return ReferenceImage(
        sha256=camera_or_revision.reference_image_sha256,
        width=camera_or_revision.reference_width,
        height=camera_or_revision.reference_height,
    )


def _set_reference(camera: Camera, reference: ReferenceImage) -> None:
    camera.reference_image_sha256 = reference.sha256
    camera.reference_width = reference.width
    camera.reference_height = reference.height


def _camera_out(camera: Camera) -> CameraOut:
    return CameraOut(
        id=camera.id,
        parking_lot_id=camera.parking_lot_id,
        name=camera.name,
        is_active=camera.is_active,
        reference_image=_reference(camera),
        viewpoint_version=camera.viewpoint_version,
        created_at=camera.created_at,
    )


def _latest_revision(session: Session, spot_id: UUID) -> PolygonRevision | None:
    return session.scalar(
        select(PolygonRevision)
        .where(PolygonRevision.spot_id == spot_id)
        .order_by(PolygonRevision.revision_no.desc())
        .limit(1)
    )


def _polygon_out(revision: PolygonRevision) -> PolygonOut:
    return PolygonOut(
        id=revision.id,
        revision_no=revision.revision_no,
        points=revision.points,
        reference_image=_reference(revision),
        camera_viewpoint_version=revision.camera_viewpoint_version,
        created_by=revision.created_by,
        created_at=revision.created_at,
    )


def _geometry_current(revision: PolygonRevision | None, camera: Camera) -> bool:
    return (
        revision is not None
        and revision.camera_viewpoint_version == camera.viewpoint_version
        and revision.reference_image_sha256 == camera.reference_image_sha256
        and revision.reference_width == camera.reference_width
        and revision.reference_height == camera.reference_height
        and camera.reference_image_sha256 is not None
    )


def _spot_out(session: Session, spot: ParkingSpot) -> SpotOut:
    camera = _camera(session, spot.camera_id)
    revision = _latest_revision(session, spot.id)
    status = (
        "legacy_missing"
        if revision is None or revision.reference_image_sha256 is None
        else "current"
        if _geometry_current(revision, camera)
        else "needs_recalibration"
    )
    return SpotOut(
        id=spot.id,
        camera_id=spot.camera_id,
        code=spot.code,
        is_active=spot.is_active,
        geometry_status=status,
        polygon=_polygon_out(revision) if revision else None,
        created_at=spot.created_at,
    )


def _validated_points(
    points: list[dict[str, Any]], camera: Camera
) -> list[dict[str, float]]:
    if camera.reference_width is None or camera.reference_height is None:
        raise ApiError(
            409, "REFERENCE_REQUIRED", "Configure the camera reference image first"
        )
    try:
        normalized = validate_polygon(points)
    except ValueError as exc:
        raise ApiError(422, "INVALID_POLYGON", str(exc)) from exc
    vertices = [(point["x"], point["y"]) for point in normalized]
    double_area = abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1])
        )
    )
    if double_area * camera.reference_width * camera.reference_height / 2 < 4:
        raise ApiError(
            422,
            "INVALID_POLYGON",
            "Polygon covers fewer than four reference-image pixels",
        )
    return normalized


def _same_geometry(first: list[dict], second: list[dict]) -> bool:
    return sorted((p["x"], p["y"]) for p in first) == sorted(
        (p["x"], p["y"]) for p in second
    )


def _inside(point: tuple[float, float], polygon: list[dict]) -> bool:
    x, y = point
    vertices = [(p["x"], p["y"]) for p in polygon]
    inside = False
    for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]):
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if (
            abs(cross) < 1e-12
            and min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12
            and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12
        ):
            return False
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _overlaps(first: list[dict], second: list[dict]) -> bool:
    a = [(p["x"], p["y"]) for p in first]
    b = [(p["x"], p["y"]) for p in second]
    for p1, p2 in zip(a, a[1:] + a[:1]):
        for q1, q2 in zip(b, b[1:] + b[:1]):
            cross1 = (p2[0] - p1[0]) * (q1[1] - p1[1]) - (p2[1] - p1[1]) * (
                q1[0] - p1[0]
            )
            cross2 = (p2[0] - p1[0]) * (q2[1] - p1[1]) - (p2[1] - p1[1]) * (
                q2[0] - p1[0]
            )
            cross3 = (q2[0] - q1[0]) * (p1[1] - q1[1]) - (q2[1] - q1[1]) * (
                p1[0] - q1[0]
            )
            cross4 = (q2[0] - q1[0]) * (p2[1] - q1[1]) - (q2[1] - q1[1]) * (
                p2[0] - q1[0]
            )
            if cross1 * cross2 < 0 and cross3 * cross4 < 0:
                return True
    for vertices, other in ((a, second), (b, first)):
        if any(_inside(point, other) for point in vertices):
            return True
        if any(
            _inside(((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2), other)
            for p1, p2 in zip(vertices, vertices[1:] + vertices[:1])
        ):
            return True
    return False


def _current_spots(session: Session, camera_id: UUID) -> list[SpotOut]:
    spots = session.scalars(
        select(ParkingSpot)
        .where(ParkingSpot.camera_id == camera_id)
        .order_by(ParkingSpot.code)
    ).all()
    return [_spot_out(session, spot) for spot in spots]


def _warnings(spots: list[SpotOut]) -> list[GeometryWarning]:
    current = [
        spot for spot in spots if spot.is_active and spot.geometry_status == "current"
    ]
    warnings = []
    for index, first in enumerate(current):
        for second in current[index + 1 :]:
            if _overlaps(first.polygon.points, second.polygon.points):
                warnings.append(
                    GeometryWarning(
                        code="POLYGON_OVERLAP", spot_ids=[first.id, second.id]
                    )
                )
    return warnings


def _check_unique_code(
    session: Session, camera_id: UUID, code: str, excluding: UUID | None = None
) -> None:
    existing = session.scalar(
        select(ParkingSpot).where(
            ParkingSpot.camera_id == camera_id, ParkingSpot.code == code
        )
    )
    if existing is not None and existing.id != excluding:
        raise ApiError(409, "CONFLICT", "Spot code already exists in this camera")


def _check_duplicate_geometry(
    session: Session, camera_id: UUID, points: list[dict], excluding: UUID | None = None
) -> None:
    for spot in session.scalars(
        select(ParkingSpot).where(
            ParkingSpot.camera_id == camera_id, ParkingSpot.is_active.is_(True)
        )
    ):
        if spot.id == excluding:
            continue
        revision = _latest_revision(session, spot.id)
        if revision and _same_geometry(revision.points, points):
            raise ApiError(
                422, "INVALID_POLYGON", "Another active spot has identical geometry"
            )


def _reject_overlap(
    session: Session, camera_id: UUID, points: list[dict], excluding: UUID | None = None
) -> None:
    for other in _current_spots(session, camera_id):
        if (
            other.id != excluding
            and other.is_active
            and other.geometry_status == "current"
            and _overlaps(other.polygon.points, points)
        ):
            raise ApiError(
                422,
                "OVERLAPPING_POLYGON",
                f"Polygon overlaps active spot {other.code}; review with bulk upsert",
            )


def _write_polygon(
    session: Session, spot: ParkingSpot, camera: Camera, points: list[dict], actor: User
) -> None:
    latest = _latest_revision(session, spot.id)
    session.add(
        PolygonRevision(
            spot_id=spot.id,
            revision_no=latest.revision_no + 1 if latest else 1,
            points=points,
            reference_image_sha256=camera.reference_image_sha256,
            reference_width=camera.reference_width,
            reference_height=camera.reference_height,
            camera_viewpoint_version=camera.viewpoint_version,
            created_by=actor.id,
        )
    )
    session.flush()


def _upsert_spot(
    session: Session,
    camera: Camera,
    item: SpotBulkItem,
    actor: User,
    *,
    reject_overlap: bool = False,
) -> ParkingSpot:
    points = _validated_points(item.points, camera)
    spot = _spot(session, item.id) if item.id else None
    if spot is not None and spot.camera_id != camera.id:
        raise ApiError(409, "CONFLICT", "Spot belongs to another camera")
    _check_unique_code(session, camera.id, item.code, spot.id if spot else None)
    _check_duplicate_geometry(session, camera.id, points, spot.id if spot else None)
    if reject_overlap:
        _reject_overlap(session, camera.id, points, spot.id if spot else None)
    if spot is None:
        spot = ParkingSpot(camera_id=camera.id, code=item.code, is_active=True)
        session.add(spot)
        session.flush()
        _write_polygon(session, spot, camera, points, actor)
    else:
        spot.code = item.code
        latest = _latest_revision(session, spot.id)
        if (
            latest is None
            or latest.points != points
            or not _geometry_current(latest, camera)
        ):
            _write_polygon(session, spot, camera, points, actor)
        spot.is_active = True
    return spot


@router.post("/lots", response_model=LotOut, status_code=201)
def create_lot(body: LotCreate, admin: Admin, session: Db) -> ParkingLot:
    if session.scalar(select(ParkingLot.id)) is not None:
        raise ApiError(409, "CONFLICT", "The MVP already has a parking lot")
    lot = ParkingLot(name=body.name)
    session.add(lot)
    session.flush()
    _audit(session, admin, "config.lot.create", "parking_lot", lot.id)
    _commit(session)
    session.refresh(lot)
    return lot


@router.get("/lots/current", response_model=LotOut)
def current_lot(_viewer: Viewer, session: Db) -> ParkingLot:
    lot = session.scalar(select(ParkingLot))
    if lot is None:
        raise ApiError(404, "NOT_FOUND", "Parking lot not found")
    return lot


@router.get("/lots/{lot_id}", response_model=LotOut)
def get_lot(lot_id: UUID, _viewer: Viewer, session: Db) -> ParkingLot:
    return _lot(session, lot_id)


@router.patch("/lots/{lot_id}", response_model=LotOut)
def update_lot(lot_id: UUID, body: LotPatch, admin: Admin, session: Db) -> ParkingLot:
    lot = _lot(session, lot_id)
    lot.name = body.name
    _audit(session, admin, "config.lot.update", "parking_lot", lot.id)
    _commit(session)
    session.refresh(lot)
    return lot


@router.delete("/lots/{lot_id}", status_code=204)
def delete_lot(lot_id: UUID, admin: Admin, session: Db) -> Response:
    lot = _lot(session, lot_id)
    if (
        session.scalar(select(Camera.id).where(Camera.parking_lot_id == lot.id))
        is not None
    ):
        raise ApiError(409, "CONFLICT", "Remove the camera before deleting this lot")
    _audit(session, admin, "config.lot.delete", "parking_lot", lot.id)
    session.delete(lot)
    _commit(session)
    return Response(status_code=204)


@router.post("/lots/{lot_id}/cameras", response_model=CameraOut, status_code=201)
def create_camera(
    lot_id: UUID, body: CameraCreate, admin: Admin, session: Db
) -> CameraOut:
    _lot(session, lot_id)
    if (
        session.scalar(select(Camera.id).where(Camera.parking_lot_id == lot_id))
        is not None
    ):
        raise ApiError(409, "CONFLICT", "The MVP lot already has a camera")
    camera = Camera(parking_lot_id=lot_id, name=body.name, is_active=True)
    _set_reference(camera, body.reference_image)
    session.add(camera)
    session.flush()
    _audit(session, admin, "config.camera.create", "camera", camera.id)
    _commit(session)
    session.refresh(camera)
    return _camera_out(camera)


@router.get("/cameras/current", response_model=CameraOut)
def current_camera(_viewer: Viewer, session: Db) -> CameraOut:
    camera = session.scalar(select(Camera))
    if camera is None:
        raise ApiError(404, "NOT_FOUND", "Camera not found")
    return _camera_out(camera)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: UUID, _viewer: Viewer, session: Db) -> CameraOut:
    return _camera_out(_camera(session, camera_id))


@router.patch("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: UUID, body: CameraPatch, admin: Admin, session: Db
) -> CameraOut:
    camera = _camera(session, camera_id)
    if not body.model_fields_set or body.model_fields_set == {"invalidate_spots"}:
        raise ApiError(422, "VALIDATION_ERROR", "No camera changes supplied")
    if body.name is not None:
        camera.name = body.name
    if body.is_active is not None:
        camera.is_active = body.is_active
    if body.reference_image is not None and body.reference_image != _reference(camera):
        spots = session.scalars(
            select(ParkingSpot).where(ParkingSpot.camera_id == camera.id)
        ).all()
        if spots and not body.invalidate_spots:
            raise ApiError(
                409,
                "VIEWPOINT_CONFLICT",
                "Set invalidate_spots=true to retire existing geometry",
            )
        _set_reference(camera, body.reference_image)
        camera.viewpoint_version += 1
        for spot in spots:
            spot.is_active = False
    _audit(session, admin, "config.camera.update", "camera", camera.id)
    _commit(session)
    session.refresh(camera)
    return _camera_out(camera)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: UUID, admin: Admin, session: Db) -> Response:
    camera = _camera(session, camera_id)
    if (
        session.scalar(select(ParkingSpot.id).where(ParkingSpot.camera_id == camera.id))
        is not None
        or session.scalar(select(Snapshot.id).where(Snapshot.camera_id == camera.id))
        is not None
    ):
        raise ApiError(
            409, "CONFLICT", "Camera has spots or snapshots; deactivate it instead"
        )
    _audit(session, admin, "config.camera.delete", "camera", camera.id)
    session.delete(camera)
    _commit(session)
    return Response(status_code=204)


@router.get("/spots", response_model=SpotList)
def list_spots(_viewer: Viewer, session: Db) -> SpotList:
    camera = session.scalar(select(Camera))
    return SpotList(items=_current_spots(session, camera.id) if camera else [])


@router.get("/cameras/{camera_id}/spots", response_model=SpotList)
def list_camera_spots(camera_id: UUID, _viewer: Viewer, session: Db) -> SpotList:
    _camera(session, camera_id)
    return SpotList(items=_current_spots(session, camera_id))


@router.put("/cameras/{camera_id}/spots/bulk", response_model=BulkResult)
def bulk_upsert_spots(
    camera_id: UUID, body: SpotBulk, admin: Admin, session: Db
) -> BulkResult:
    camera = _camera(session, camera_id)
    if not camera.is_active:
        raise ApiError(409, "CONFLICT", "Camera is inactive")
    ids = [item.id for item in body.items if item.id is not None]
    codes = [item.code for item in body.items]
    if len(set(ids)) != len(ids) or len(set(codes)) != len(codes):
        raise ApiError(
            422, "VALIDATION_ERROR", "Duplicate spot ID or code in bulk request"
        )
    spots = [_upsert_spot(session, camera, item, admin) for item in body.items]
    result = [_spot_out(session, spot) for spot in spots]
    warnings = _warnings(_current_spots(session, camera.id))
    _audit(session, admin, "config.spots.bulk", "camera", camera.id)
    _commit(session)
    return BulkResult(items=result, warnings=warnings)


@router.post("/cameras/{camera_id}/spots", response_model=SpotOut, status_code=201)
def create_spot(
    camera_id: UUID, body: SpotCreate, admin: Admin, session: Db
) -> SpotOut:
    camera = _camera(session, camera_id)
    if not camera.is_active:
        raise ApiError(409, "CONFLICT", "Camera is inactive")
    spot = _upsert_spot(
        session, camera, SpotBulkItem(**body.model_dump()), admin, reject_overlap=True
    )
    result = _spot_out(session, spot)
    _audit(session, admin, "config.spot.create", "parking_spot", spot.id)
    _commit(session)
    return result


@router.get("/spots/{spot_id}", response_model=SpotOut)
def get_spot(spot_id: UUID, _viewer: Viewer, session: Db) -> SpotOut:
    return _spot_out(session, _spot(session, spot_id))


@router.get("/spots/{spot_id}/revisions", response_model=RevisionList)
def list_revisions(spot_id: UUID, _viewer: Viewer, session: Db) -> RevisionList:
    _spot(session, spot_id)
    revisions = session.scalars(
        select(PolygonRevision)
        .where(PolygonRevision.spot_id == spot_id)
        .order_by(PolygonRevision.revision_no)
    ).all()
    return RevisionList(items=[_polygon_out(revision) for revision in revisions])


@router.patch("/spots/{spot_id}", response_model=SpotOut)
def update_spot(spot_id: UUID, body: SpotPatch, admin: Admin, session: Db) -> SpotOut:
    spot = _spot(session, spot_id)
    if not body.model_fields_set:
        raise ApiError(422, "VALIDATION_ERROR", "No spot changes supplied")
    if body.code is not None:
        _check_unique_code(session, spot.camera_id, body.code, spot.id)
        spot.code = body.code
    if body.is_active is not None:
        if body.is_active and not _geometry_current(
            _latest_revision(session, spot.id), _camera(session, spot.camera_id)
        ):
            raise ApiError(
                409,
                "VIEWPOINT_CONFLICT",
                "Recalibrate the polygon before activating this spot",
            )
        spot.is_active = body.is_active
    _audit(session, admin, "config.spot.update", "parking_spot", spot.id)
    _commit(session)
    return _spot_out(session, spot)


@router.put("/spots/{spot_id}/polygon", response_model=SpotOut)
def replace_polygon(
    spot_id: UUID,
    body: PolygonReplace,
    admin: Admin,
    session: Db,
    if_match: Annotated[
        str | None, Header(description='Quoted current revision, e.g. "1"')
    ] = None,
) -> SpotOut:
    spot = _spot(session, spot_id)
    camera = _camera(session, spot.camera_id)
    if if_match is None:
        raise ApiError(428, "PRECONDITION_REQUIRED", "If-Match revision is required")
    latest = _latest_revision(session, spot.id)
    match = re.fullmatch(r'"(0|[1-9][0-9]*)"', if_match)
    if not match:
        raise ApiError(
            422, "VALIDATION_ERROR", "If-Match must be a quoted revision number"
        )
    if latest is None or int(match.group(1)) != latest.revision_no:
        raise ApiError(
            409, "REVISION_CONFLICT", "Polygon revision changed; reload this spot"
        )
    points = _validated_points(body.points, camera)
    _check_duplicate_geometry(session, camera.id, points, spot.id)
    _reject_overlap(session, camera.id, points, spot.id)
    if latest.points != points or not _geometry_current(latest, camera):
        _write_polygon(session, spot, camera, points, admin)
    spot.is_active = True
    _audit(session, admin, "config.spot.polygon", "parking_spot", spot.id)
    _commit(session)
    return _spot_out(session, spot)


@router.delete("/spots/{spot_id}", status_code=204)
def delete_spot(spot_id: UUID, admin: Admin, session: Db) -> Response:
    spot = _spot(session, spot_id)
    spot.is_active = False
    _audit(session, admin, "config.spot.deactivate", "parking_spot", spot.id)
    _commit(session)
    return Response(status_code=204)
