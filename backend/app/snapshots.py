"""Authenticated snapshot upload, operational inference and private originals."""

import hashlib
import logging
import math
import os
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import ApiError, get_auth_session, get_current_user
from app.config import AppSettings
from app.error_schemas import ApiErrorResponse
from app.models import (
    Camera,
    ParkingSpot,
    PolygonRevision,
    Snapshot,
    SpotPrediction,
    SpotReview,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1",
    tags=["Snapshots and occupancy"],
    responses={
        401: {"model": ApiErrorResponse, "description": "Authentication required"},
        404: {"model": ApiErrorResponse, "description": "Camera or snapshot not found"},
        409: {"model": ApiErrorResponse, "description": "Camera or polygon conflict"},
        413: {"model": ApiErrorResponse, "description": "Upload exceeds size limit"},
        415: {"model": ApiErrorResponse, "description": "Unsupported image media type"},
        422: {"model": ApiErrorResponse, "description": "Invalid image or request"},
        503: {
            "model": ApiErrorResponse,
            "description": "Storage or database unavailable",
        },
    },
)
Viewer = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_auth_session)]

MIME_BY_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png"}
EXTENSION_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}


class PredictionOut(BaseModel):
    prediction_id: UUID
    spot_id: UUID
    polygon_revision_id: UUID
    predicted_status: Literal["empty", "occupied", "unknown"]
    effective_status: Literal["empty", "occupied", "unknown"]
    review_version: int
    latest_review_id: UUID | None
    latest_reviewed_by: UUID | None
    latest_reviewed_at: datetime | None
    confidence: float | None
    model_version: str | None
    reason_code: str | None
    polygon: list[dict[str, float]]


class SnapshotOut(BaseModel):
    snapshot_id: UUID
    camera_id: UUID
    timestamp: datetime
    total_spots: int
    empty_count: int
    occupied_count: int
    unknown_count: int
    occupancy_percent: float | None
    predictions: list[PredictionOut]
    model_version: str | None
    processing_time_ms: float | None
    alert_state: Literal["NONE", "FULL", "STALE"]
    image_url: str


class OccupancyCounts(BaseModel):
    total: int
    empty: int
    occupied: int
    unknown: int
    available_confirmed: int
    occupancy_percent: float | None


class OccupancyOut(BaseModel):
    snapshot_id: UUID | None
    camera_id: UUID
    captured_at: datetime | None
    as_of: datetime
    stale_after_seconds: int
    counts: OccupancyCounts | None
    alert_state: Literal["NONE", "FULL", "STALE"]


@dataclass(frozen=True)
class CaptureSpot:
    spot_id: UUID
    revision_id: UUID
    points: list[dict[str, float]]


@dataclass(frozen=True)
class Verdict:
    status: Literal["empty", "occupied", "unknown"]
    confidence: float | None
    model_version: str | None
    reason_code: str | None


def _storage_root(settings: AppSettings) -> Path:
    if settings.image_storage_root is None:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Private image storage is not configured"
        )
    return settings.image_storage_root.resolve()


async def _read_upload(file: UploadFile, settings: AppSettings) -> bytes:
    if file.content_type not in EXTENSION_BY_MIME:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Upload must be JPEG or PNG")
    parts = []
    total = 0
    while True:
        part = await file.read(min(1024 * 1024, settings.max_upload_bytes - total + 1))
        if not part:
            break
        total += len(part)
        if total > settings.max_upload_bytes:
            raise ApiError(413, "PAYLOAD_TOO_LARGE", "Image exceeds MAX_UPLOAD_BYTES")
        parts.append(part)
    if total == 0:
        raise ApiError(422, "INVALID_IMAGE", "Image is empty")
    return b"".join(parts)


def _decode_image(
    data: bytes, declared_mime: str, settings: AppSettings
) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                actual_mime = MIME_BY_FORMAT.get(probe.format)
                if actual_mime is None or actual_mime != declared_mime:
                    raise ApiError(
                        415,
                        "UNSUPPORTED_MEDIA_TYPE",
                        "Image content does not match JPEG/PNG MIME",
                    )
                if (
                    probe.width < 2
                    or probe.height < 2
                    or probe.width * probe.height > settings.max_image_pixels
                ):
                    raise ApiError(
                        422, "INVALID_IMAGE", "Image dimensions are outside limits"
                    )
                probe.verify()
            with Image.open(BytesIO(data)) as decoded:
                decoded.load()
                return decoded.convert("RGB")
    except ApiError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise ApiError(422, "INVALID_IMAGE", "Image cannot be decoded safely") from exc


def _capture_spots(session: Session, camera: Camera) -> list[CaptureSpot]:
    active = session.scalars(
        select(ParkingSpot)
        .where(ParkingSpot.camera_id == camera.id, ParkingSpot.is_active.is_(True))
        .order_by(ParkingSpot.code)
    ).all()
    captured = []
    for spot in active:
        revision = session.scalar(
            select(PolygonRevision)
            .where(PolygonRevision.spot_id == spot.id)
            .order_by(PolygonRevision.revision_no.desc())
            .limit(1)
        )
        if (
            revision is None
            or revision.camera_viewpoint_version != camera.viewpoint_version
            or revision.reference_image_sha256 != camera.reference_image_sha256
            or revision.reference_width != camera.reference_width
            or revision.reference_height != camera.reference_height
        ):
            raise ApiError(
                409, "VIEWPOINT_CONFLICT", "Active spot geometry needs recalibration"
            )
        captured.append(CaptureSpot(spot.id, revision.id, revision.points))
    return captured


@lru_cache(maxsize=4)
def _model(path: str, threshold: float, batch_size: int, device: str):
    from inference.predictor import ParkingOccupancyPredictor

    return ParkingOccupancyPredictor(
        path,
        confidence_threshold=threshold,
        batch_size=batch_size,
        device=device,
    )


def _unknown(spots: list[CaptureSpot], reason: str) -> list[Verdict]:
    return [Verdict("unknown", None, None, reason) for _ in spots]


def _predict(
    image: Image.Image, spots: list[CaptureSpot], settings: AppSettings
) -> list[Verdict]:
    if not spots:
        return []
    checkpoint = settings.parking_model_checkpoint
    if checkpoint is None:
        return _unknown(spots, "MODEL_UNAVAILABLE")
    try:
        predictor = _model(
            str(checkpoint.resolve()),
            settings.parking_confidence_threshold,
            settings.parking_inference_batch_size,
            settings.parking_inference_device,
        )
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        logger.warning("AI model unavailable: %s", type(exc).__name__)
        return _unknown(spots, "MODEL_UNAVAILABLE")
    regions = [
        {
            "spot_id": str(spot.spot_id),
            "polygon": [[point["x"], point["y"]] for point in spot.points],
        }
        for spot in spots
    ]
    try:
        results = predictor.predict_spots(image, regions)
        if len(results) != len(spots):
            raise ValueError("Predictor returned an incomplete batch")
        verdicts = []
        for spot, result in zip(spots, results):
            if str(spot.spot_id) != result.spot_id:
                raise ValueError("Predictor changed spot order")
            if result.predicted_status not in {"empty", "occupied", "unknown"}:
                raise ValueError("Predictor returned an invalid status")
            confidence = result.confidence
            if confidence is not None and (
                not isinstance(confidence, (float, int))
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("Predictor returned an invalid confidence")
            if confidence is None:
                if result.predicted_status != "unknown":
                    raise ValueError("Binary prediction has no confidence")
                verdicts.append(Verdict("unknown", None, None, "INVALID_ROI"))
            else:
                if not result.model_version:
                    raise ValueError("Model prediction has no version")
                reason = (
                    "LOW_CONFIDENCE" if result.predicted_status == "unknown" else None
                )
                verdicts.append(
                    Verdict(
                        result.predicted_status,
                        float(confidence),
                        result.model_version,
                        reason,
                    )
                )
        return verdicts
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("AI inference failed: %s", type(exc).__name__)
        return _unknown(spots, "INFERENCE_ERROR")


def _counts(verdicts: list[Verdict]) -> tuple[int, int, int, float | None]:
    empty = sum(item.status == "empty" for item in verdicts)
    occupied = sum(item.status == "occupied" for item in verdicts)
    unknown = sum(item.status == "unknown" for item in verdicts)
    total = len(verdicts)
    percentage = 100 * occupied / total if total > 0 and unknown == 0 else None
    return empty, occupied, unknown, percentage


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _effective_verdicts(session: Session, snapshot_id: UUID) -> list[Verdict]:
    predictions = session.scalars(
        select(SpotPrediction)
        .where(SpotPrediction.snapshot_id == snapshot_id)
        .order_by(SpotPrediction.spot_id)
    ).all()
    verdicts = []
    for prediction in predictions:
        review = session.scalar(
            select(SpotReview)
            .where(SpotReview.prediction_id == prediction.id)
            .order_by(SpotReview.revision_no.desc())
            .limit(1)
        )
        verdicts.append(
            Verdict(
                review.reviewed_status if review else prediction.prediction_status,
                prediction.confidence,
                prediction.model_version,
                prediction.reason_code,
            )
        )
    return verdicts


def _alert(
    *,
    total: int,
    empty: int,
    unknown: int,
    captured_at: datetime | None,
    now: datetime,
    stale_after_seconds: int,
) -> Literal["NONE", "FULL", "STALE"]:
    if captured_at is None or (now - captured_at).total_seconds() > stale_after_seconds:
        return "STALE"
    if total > 0 and empty == 0 and unknown == 0:
        return "FULL"
    return "NONE"


def _save(
    session: Session,
    settings: AppSettings,
    *,
    camera: Camera,
    user: User,
    captured_at: datetime,
    image: Image.Image,
    data: bytes,
    mime_type: str,
    spots: list[CaptureSpot],
    verdicts: list[Verdict],
    processing_time_ms: float,
) -> tuple[Snapshot, list[SpotPrediction]]:
    root = _storage_root(settings)
    snapshot_id = uuid4()
    key = f"{snapshot_id.hex}{EXTENSION_BY_MIME[mime_type]}"
    final = root / key
    temporary = root / f".{snapshot_id.hex}.uploading"
    renamed = False
    staged = False
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with temporary.open("xb") as output:
            staged = True
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        snapshot = Snapshot(
            id=snapshot_id,
            camera_id=camera.id,
            uploaded_by=user.id,
            captured_at=captured_at,
            original_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            mime_type=mime_type,
            byte_size=len(data),
            width=image.width,
            height=image.height,
            processing_time_ms=processing_time_ms,
        )
        session.add(snapshot)
        session.flush()
        predictions = []
        for spot, verdict in zip(spots, verdicts):
            prediction = SpotPrediction(
                snapshot_id=snapshot.id,
                spot_id=spot.spot_id,
                polygon_revision_id=spot.revision_id,
                camera_id=camera.id,
                prediction_status=verdict.status,
                confidence=verdict.confidence,
                model_version=verdict.model_version,
                reason_code=verdict.reason_code,
            )
            session.add(prediction)
            predictions.append(prediction)
        session.flush()
        os.replace(temporary, final)
        renamed = True
        session.commit()
        return snapshot, predictions
    except (OSError, SQLAlchemyError) as exc:
        session.rollback()
        if staged and not renamed:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("Temporary snapshot cleanup failed")
        logger.error("Snapshot persistence failed: %s", type(exc).__name__)
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Snapshot could not be saved"
        ) from exc


@router.post("/snapshots/predict", response_model=SnapshotOut, status_code=201)
async def upload_and_predict(
    file: Annotated[UploadFile, File(description="JPEG or PNG snapshot")],
    camera_id: Annotated[UUID, Form()],
    request: Request,
    user: Viewer,
    session: Db,
    captured_at: Annotated[datetime | None, Form()] = None,
) -> SnapshotOut:
    started = time.perf_counter()
    settings: AppSettings = request.app.state.settings
    now = datetime.now(timezone.utc)
    if captured_at is not None and captured_at.tzinfo is None:
        raise ApiError(422, "VALIDATION_ERROR", "captured_at requires a timezone")
    timestamp = captured_at.astimezone(timezone.utc) if captured_at else now
    if timestamp > now:
        raise ApiError(422, "VALIDATION_ERROR", "captured_at cannot be in the future")
    camera = session.get(Camera, camera_id)
    if camera is None:
        raise ApiError(404, "NOT_FOUND", "Camera not found")
    if not camera.is_active:
        raise ApiError(409, "CONFLICT", "Camera is inactive")
    data = await _read_upload(file, settings)
    image = _decode_image(data, file.content_type, settings)
    spots = _capture_spots(session, camera)
    verdicts = _predict(image, spots, settings)
    processing_time_ms = (time.perf_counter() - started) * 1000
    snapshot, predictions = _save(
        session,
        settings,
        camera=camera,
        user=user,
        captured_at=timestamp,
        image=image,
        data=data,
        mime_type=file.content_type,
        spots=spots,
        verdicts=verdicts,
        processing_time_ms=processing_time_ms,
    )
    empty, occupied, unknown, percentage = _counts(verdicts)
    version = next(
        (item.model_version for item in verdicts if item.model_version), None
    )
    return SnapshotOut(
        snapshot_id=snapshot.id,
        camera_id=camera.id,
        timestamp=timestamp,
        total_spots=len(spots),
        empty_count=empty,
        occupied_count=occupied,
        unknown_count=unknown,
        occupancy_percent=percentage,
        predictions=[
            PredictionOut(
                prediction_id=prediction.id,
                spot_id=spot.spot_id,
                polygon_revision_id=spot.revision_id,
                predicted_status=verdict.status,
                effective_status=verdict.status,
                review_version=0,
                latest_review_id=None,
                latest_reviewed_by=None,
                latest_reviewed_at=None,
                confidence=verdict.confidence,
                model_version=verdict.model_version,
                reason_code=verdict.reason_code,
                polygon=spot.points,
            )
            for spot, verdict, prediction in zip(spots, verdicts, predictions)
        ],
        model_version=version,
        processing_time_ms=processing_time_ms,
        alert_state=_alert(
            total=len(spots),
            empty=empty,
            unknown=unknown,
            captured_at=timestamp,
            now=datetime.now(timezone.utc),
            stale_after_seconds=settings.stale_after_seconds,
        ),
        image_url=f"/api/v1/snapshots/{snapshot.id}/image",
    )


@router.get("/snapshots/{snapshot_id}/image")
def original_image(
    snapshot_id: UUID, request: Request, _viewer: Viewer, session: Db
) -> Response:
    snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise ApiError(404, "NOT_FOUND", "Snapshot not found")
    root = _storage_root(request.app.state.settings)
    path = (root / snapshot.original_key).resolve()
    if path.parent != root:
        raise ApiError(503, "SERVICE_UNAVAILABLE", "Original image is unavailable")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Original image is unavailable"
        ) from exc
    if hashlib.sha256(data).hexdigest() != snapshot.sha256:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Original image failed integrity check"
        )
    return Response(
        content=data,
        media_type=snapshot.mime_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotOut)
def snapshot_detail(
    snapshot_id: UUID, request: Request, _viewer: Viewer, session: Db
) -> SnapshotOut:
    snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise ApiError(404, "NOT_FOUND", "Snapshot not found")
    predictions = session.scalars(
        select(SpotPrediction)
        .join(ParkingSpot, ParkingSpot.id == SpotPrediction.spot_id)
        .where(SpotPrediction.snapshot_id == snapshot.id)
        .order_by(ParkingSpot.code)
    ).all()
    output = []
    for prediction in predictions:
        revision = session.get(PolygonRevision, prediction.polygon_revision_id)
        review = session.scalar(
            select(SpotReview)
            .where(SpotReview.prediction_id == prediction.id)
            .order_by(SpotReview.revision_no.desc())
            .limit(1)
        )
        output.append(
            PredictionOut(
                prediction_id=prediction.id,
                spot_id=prediction.spot_id,
                polygon_revision_id=prediction.polygon_revision_id,
                predicted_status=prediction.prediction_status,
                effective_status=(
                    review.reviewed_status if review else prediction.prediction_status
                ),
                review_version=prediction.review_version,
                latest_review_id=review.id if review else None,
                latest_reviewed_by=review.reviewed_by if review else None,
                latest_reviewed_at=_utc(review.reviewed_at) if review else None,
                confidence=prediction.confidence,
                model_version=prediction.model_version,
                reason_code=prediction.reason_code,
                polygon=revision.points,
            )
        )
    verdicts = _effective_verdicts(session, snapshot.id)
    empty, occupied, unknown, percentage = _counts(verdicts)
    timestamp = _utc(snapshot.captured_at)
    settings: AppSettings = request.app.state.settings
    return SnapshotOut(
        snapshot_id=snapshot.id,
        camera_id=snapshot.camera_id,
        timestamp=timestamp,
        total_spots=len(predictions),
        empty_count=empty,
        occupied_count=occupied,
        unknown_count=unknown,
        occupancy_percent=percentage,
        predictions=output,
        model_version=next(
            (item.model_version for item in predictions if item.model_version), None
        ),
        processing_time_ms=snapshot.processing_time_ms,
        alert_state=_alert(
            total=len(predictions),
            empty=empty,
            unknown=unknown,
            captured_at=timestamp,
            now=datetime.now(timezone.utc),
            stale_after_seconds=settings.stale_after_seconds,
        ),
        image_url=f"/api/v1/snapshots/{snapshot.id}/image",
    )


@router.get("/lots/current/occupancy", response_model=OccupancyOut)
def current_occupancy(request: Request, _viewer: Viewer, session: Db) -> OccupancyOut:
    camera = session.scalar(select(Camera))
    if camera is None:
        raise ApiError(404, "NOT_FOUND", "Camera not found")
    settings: AppSettings = request.app.state.settings
    now = datetime.now(timezone.utc)
    latest = session.scalar(
        select(Snapshot)
        .where(Snapshot.camera_id == camera.id)
        .order_by(
            Snapshot.captured_at.desc(),
            Snapshot.uploaded_at.desc(),
            Snapshot.id.desc(),
        )
        .limit(1)
    )
    if latest is None:
        return OccupancyOut(
            snapshot_id=None,
            camera_id=camera.id,
            captured_at=None,
            as_of=now,
            stale_after_seconds=settings.stale_after_seconds,
            counts=None,
            alert_state="STALE",
        )
    verdicts = _effective_verdicts(session, latest.id)
    empty, occupied, unknown, percentage = _counts(verdicts)
    captured_at = _utc(latest.captured_at)
    return OccupancyOut(
        snapshot_id=latest.id,
        camera_id=camera.id,
        captured_at=captured_at,
        as_of=now,
        stale_after_seconds=settings.stale_after_seconds,
        counts=OccupancyCounts(
            total=len(verdicts),
            empty=empty,
            occupied=occupied,
            unknown=unknown,
            available_confirmed=empty,
            occupancy_percent=percentage,
        ),
        alert_state=_alert(
            total=len(verdicts),
            empty=empty,
            unknown=unknown,
            captured_at=captured_at,
            now=now,
            stale_after_seconds=settings.stale_after_seconds,
        ),
    )
