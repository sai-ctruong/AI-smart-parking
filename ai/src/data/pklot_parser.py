"""Parse PKLot full-frame XML annotations as offline ground truth."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

KNOWN_PARKING_CAMERAS = {"UFPR04", "UFPR05", "PUCPR"}


class AnnotationError(ValueError):
    """An annotation is malformed or uses an unsupported schema."""


@dataclass(frozen=True)
class SpotAnnotation:
    spot_id: str
    occupied: bool
    polygon: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class FrameAnnotation:
    camera_id: str
    capture_day: str
    spots: tuple[SpotAnnotation, ...]


def _capture_day(source: str) -> str:
    matches = re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", source)
    if not matches:
        raise AnnotationError(f"Capture day (YYYY-MM-DD) missing from {source}")
    if len(set(matches)) != 1:
        raise AnnotationError(f"Conflicting capture days in {source}")
    try:
        date.fromisoformat(matches[0])
    except ValueError as exc:
        raise AnnotationError(f"Invalid capture day in {source}") from exc
    return matches[0]


def _area2(points: tuple[tuple[int, int], ...]) -> int:
    return sum(
        x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )


def _orientation(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> int:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(
    a: tuple[int, int],
    b: tuple[int, int],
    c: tuple[int, int],
    d: tuple[int, int],
) -> bool:
    first = (_orientation(a, b, c), _orientation(a, b, d))
    second = (_orientation(c, d, a), _orientation(c, d, b))
    return first[0] * first[1] < 0 and second[0] * second[1] < 0


def _validate_polygon(points: tuple[tuple[int, int], ...], spot_id: str) -> None:
    if len(points) < 3 or len(set(points)) != len(points) or _area2(points) == 0:
        raise AnnotationError(f"Spot {spot_id} has invalid polygon")
    count = len(points)
    for index in range(count):
        for other in range(index + 2, count):
            if index == 0 and other == count - 1:
                continue
            if _segments_cross(
                points[index],
                points[(index + 1) % count],
                points[other],
                points[(other + 1) % count],
            ):
                raise AnnotationError(f"Spot {spot_id} has self-intersecting polygon")


def parse_pklot_xml(xml_bytes: bytes, source: str) -> FrameAnnotation:
    """Read one PKLot `<parking>` XML; reject invalid labels and contours."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise AnnotationError(f"Malformed XML in {source}: {exc}") from exc
    if root.tag != "parking":
        raise AnnotationError(f"Unsupported XML root <{root.tag}> in {source}")
    camera = root.get("id", "").strip().upper()
    if not camera:
        raise AnnotationError(f"Camera ID missing in {source}")
    path_cameras = {
        part.upper()
        for part in re.split(r"[/\\]", source)
        if part.upper() in KNOWN_PARKING_CAMERAS
    }
    if path_cameras and path_cameras != {camera}:
        raise AnnotationError(f"XML camera ID does not match path camera in {source}")
    capture_day = _capture_day(source)
    spots: list[SpotAnnotation] = []
    seen_ids: set[str] = set()
    for space in root:
        if space.tag != "space":
            raise AnnotationError(f"Unsupported <{space.tag}> element in {source}")
        spot_id = space.get("id", "").strip()
        if not spot_id or spot_id in seen_ids:
            raise AnnotationError(f"Missing or duplicate spot ID in {source}")
        seen_ids.add(spot_id)
        label = space.get("occupied")
        if label not in {"0", "1"}:
            raise AnnotationError(
                f"Spot {spot_id} has invalid occupied label {label!r}"
            )
        unsupported = [
            child.tag for child in space if child.tag not in {"rotatedRect", "contour"}
        ]
        if unsupported or len(space.findall("contour")) != 1:
            raise AnnotationError(f"Unsupported space structure for spot {spot_id}")
        contour = space.find("contour")
        if contour is None or any(child.tag != "point" for child in contour):
            raise AnnotationError(f"Spot {spot_id} has missing or unsupported contour")
        try:
            points = tuple(
                (int(point.attrib["x"]), int(point.attrib["y"])) for point in contour
            )
        except (KeyError, ValueError) as exc:
            raise AnnotationError(
                f"Spot {spot_id} has invalid polygon coordinates"
            ) from exc
        if len(points) >= 2 and points[0] == points[-1]:
            points = points[:-1]
        _validate_polygon(points, spot_id)
        spots.append(SpotAnnotation(spot_id, label == "1", points))
    if not spots:
        raise AnnotationError(f"No parking spaces in {source}")
    return FrameAnnotation(camera, capture_day, tuple(spots))
