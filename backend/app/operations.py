"""Authenticated operational history, append-only reviews, and CSV export."""

import csv
import re
from datetime import datetime, timezone
from io import StringIO
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import ApiError, get_auth_session, get_current_user
from app.error_schemas import ApiErrorResponse
from app.models import AuditLog, Snapshot, SpotPrediction, SpotReview, User
from app.snapshots import _alert, _counts, _effective_verdicts, _utc

router = APIRouter(
    prefix="/api/v1",
    tags=["History and reviews"],
    responses={
        401: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        409: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        428: {"model": ApiErrorResponse},
        503: {"model": ApiErrorResponse},
    },
)
Viewer = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_auth_session)]
Status = Literal["empty", "occupied", "unknown"]
CSV_COLUMNS = [
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


class SnapshotSummary(BaseModel):
    snapshot_id: UUID
    camera_id: UUID
    captured_at: datetime
    uploaded_at: datetime
    total_spots: int
    empty_count: int
    occupied_count: int
    unknown_count: int
    occupancy_percent: float | None
    model_version: str | None
    reviewed_spots: int
    alert_state: Literal["NONE", "FULL", "STALE"]


class SnapshotPage(BaseModel):
    items: list[SnapshotSummary]
    page: int
    page_size: int
    total_items: int


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_status: Status
    note: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    id: UUID
    prediction_id: UUID
    revision_no: int
    reviewed_status: Status
    note: str | None
    reviewed_by: UUID
    reviewed_at: datetime


class ReviewList(BaseModel):
    items: list[ReviewOut]


def _range_filters(
    camera_id: UUID | None, start: datetime | None, end: datetime | None
):
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise ApiError(422, "VALIDATION_ERROR", "Time filters require a timezone")
    if start is not None and end is not None and start >= end:
        raise ApiError(422, "VALIDATION_ERROR", "from must be earlier than to")
    filters = []
    if camera_id is not None:
        filters.append(Snapshot.camera_id == camera_id)
    if start is not None:
        filters.append(Snapshot.captured_at >= start.astimezone(timezone.utc))
    if end is not None:
        filters.append(Snapshot.captured_at < end.astimezone(timezone.utc))
    return filters


def _latest_review(session: Session, prediction_id: UUID) -> SpotReview | None:
    return session.scalar(
        select(SpotReview)
        .where(SpotReview.prediction_id == prediction_id)
        .order_by(SpotReview.revision_no.desc())
        .limit(1)
    )


def _review_out(review: SpotReview) -> ReviewOut:
    return ReviewOut(
        id=review.id,
        prediction_id=review.prediction_id,
        revision_no=review.revision_no,
        reviewed_status=review.reviewed_status,
        note=review.note,
        reviewed_by=review.reviewed_by,
        reviewed_at=_utc(review.reviewed_at),
    )


@router.get("/snapshots", response_model=SnapshotPage)
def snapshot_history(
    request: Request,
    _viewer: Viewer,
    session: Db,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    camera_id: UUID | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> SnapshotPage:
    filters = _range_filters(camera_id, start, end)
    total = session.scalar(select(func.count()).select_from(Snapshot).where(*filters))
    snapshots = session.scalars(
        select(Snapshot)
        .where(*filters)
        .order_by(
            Snapshot.captured_at.desc(), Snapshot.uploaded_at.desc(), Snapshot.id.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    now = datetime.now(timezone.utc)
    items = []
    for snapshot in snapshots:
        verdicts = _effective_verdicts(session, snapshot.id)
        empty, occupied, unknown, percentage = _counts(verdicts)
        predictions = session.scalars(
            select(SpotPrediction).where(SpotPrediction.snapshot_id == snapshot.id)
        ).all()
        captured_at = _utc(snapshot.captured_at)
        items.append(
            SnapshotSummary(
                snapshot_id=snapshot.id,
                camera_id=snapshot.camera_id,
                captured_at=captured_at,
                uploaded_at=_utc(snapshot.uploaded_at),
                total_spots=len(verdicts),
                empty_count=empty,
                occupied_count=occupied,
                unknown_count=unknown,
                occupancy_percent=percentage,
                model_version=next(
                    (row.model_version for row in predictions if row.model_version),
                    None,
                ),
                reviewed_spots=sum(row.review_version > 0 for row in predictions),
                alert_state=_alert(
                    total=len(verdicts),
                    empty=empty,
                    unknown=unknown,
                    captured_at=captured_at,
                    now=now,
                    stale_after_seconds=request.app.state.settings.stale_after_seconds,
                ),
            )
        )
    return SnapshotPage(
        items=items, page=page, page_size=page_size, total_items=total or 0
    )


@router.post(
    "/predictions/{prediction_id}/reviews", response_model=ReviewOut, status_code=201
)
def create_review(
    prediction_id: UUID,
    body: ReviewCreate,
    user: Viewer,
    session: Db,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ReviewOut:
    prediction = session.get(SpotPrediction, prediction_id)
    if prediction is None:
        raise ApiError(404, "NOT_FOUND", "Prediction not found")
    if if_match is None:
        raise ApiError(
            428, "PRECONDITION_REQUIRED", "If-Match review version is required"
        )
    if not re.fullmatch(r'"(0|[1-9][0-9]*)"', if_match):
        raise ApiError(
            422, "VALIDATION_ERROR", "If-Match must be a quoted review version"
        )
    expected = int(if_match[1:-1])
    if expected != prediction.review_version:
        raise ApiError(
            409, "REVIEW_CONFLICT", "Review version changed; reload prediction"
        )
    prior = _latest_review(session, prediction_id)
    previous_status = prior.reviewed_status if prior else prediction.prediction_status
    # A conditional UPDATE serializes competing writes on PostgreSQL. Exactly
    # one request based on the previous version can create the next review.
    result = session.execute(
        update(SpotPrediction)
        .where(
            SpotPrediction.id == prediction_id,
            SpotPrediction.review_version == expected,
        )
        .values(review_version=expected + 1)
    )
    if result.rowcount != 1:
        session.rollback()
        raise ApiError(
            409, "REVIEW_CONFLICT", "Review version changed; reload prediction"
        )
    review = SpotReview(
        prediction_id=prediction_id,
        reviewed_by=user.id,
        reviewed_status=body.reviewed_status,
        revision_no=expected + 1,
        note=body.note,
        reviewed_at=datetime.now(timezone.utc),
    )
    session.add(review)
    session.flush()
    session.add(
        AuditLog(
            actor_id=user.id,
            action="prediction.reviewed",
            target_type="prediction",
            target_id=prediction_id,
            details={
                "review_id": str(review.id),
                "revision_no": review.revision_no,
                "previous_status": previous_status,
                "reviewed_status": review.reviewed_status,
            },
        )
    )
    session.commit()
    return _review_out(review)


@router.get("/predictions/{prediction_id}/reviews", response_model=ReviewList)
def review_history(prediction_id: UUID, _viewer: Viewer, session: Db) -> ReviewList:
    if session.get(SpotPrediction, prediction_id) is None:
        raise ApiError(404, "NOT_FOUND", "Prediction not found")
    rows = session.scalars(
        select(SpotReview)
        .where(SpotReview.prediction_id == prediction_id)
        .order_by(SpotReview.revision_no)
    ).all()
    return ReviewList(items=[_review_out(row) for row in rows])


def _safe_csv(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        result = _utc(value).isoformat()
    else:
        result = str(value)
    if result.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + result
    return result


@router.get("/snapshots/export.csv")
def export_snapshots(
    _viewer: Viewer,
    session: Db,
    camera_id: UUID | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> Response:
    filters = _range_filters(camera_id, start, end)
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    rows = session.execute(
        select(Snapshot, SpotPrediction)
        .join(SpotPrediction, SpotPrediction.snapshot_id == Snapshot.id)
        .where(*filters)
        .order_by(
            Snapshot.captured_at.desc(),
            Snapshot.uploaded_at.desc(),
            Snapshot.id.desc(),
            SpotPrediction.spot_id,
        )
    )
    for snapshot, prediction in rows:
        review = _latest_review(session, prediction.id)
        writer.writerow(
            [
                _safe_csv(value)
                for value in (
                    snapshot.id,
                    snapshot.camera_id,
                    snapshot.captured_at,
                    snapshot.uploaded_at,
                    prediction.spot_id,
                    prediction.polygon_revision_id,
                    prediction.prediction_status,
                    review.reviewed_status if review else prediction.prediction_status,
                    prediction.confidence,
                    prediction.model_version,
                    prediction.reason_code,
                    prediction.inferred_at,
                    review.id if review else None,
                    review.reviewed_by if review else None,
                    review.reviewed_at if review else None,
                )
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="smart-parking-history.csv"',
            "Cache-Control": "private, no-store",
        },
    )
