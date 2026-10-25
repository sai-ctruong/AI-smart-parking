"""Audit local PKLot full frames; source files are read only."""

import csv
import json
import os
import tarfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, UnidentifiedImageError

from data.pklot_parser import AnnotationError, FrameAnnotation, parse_pklot_xml

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
SAMPLE_COLUMNS = (
    "image",
    "annotation",
    "camera_id",
    "capture_day",
    "width",
    "height",
    "empty",
    "occupied",
)
ERROR_COLUMNS = ("code", "source", "message")


class ImageValidationError(ValueError):
    """Image bytes cannot be decoded as JPEG or PNG."""


class PolygonValidationError(ValueError):
    """A polygon cannot fit the matching image."""


@dataclass(frozen=True)
class ValidatedSample:
    annotation: FrameAnnotation
    image: Image.Image
    width: int
    height: int
    empty_count: int
    occupied_count: int


def validate_pair(image_bytes: bytes, xml_bytes: bytes, source: str) -> ValidatedSample:
    """Validate image decoding, XML and polygon bounds for one pair."""
    annotation = parse_pklot_xml(xml_bytes, source)
    try:
        with Image.open(BytesIO(image_bytes)) as raw:
            if raw.format not in {"JPEG", "PNG"}:
                raise ImageValidationError("Image is not JPEG or PNG")
            raw.load()
            image = raw.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ImageValidationError(f"Image cannot decode: {exc}") from exc
    width, height = image.size
    if width < 1 or height < 1:
        raise ImageValidationError("Image has invalid dimensions")
    for spot in annotation.spots:
        if any(x < 0 or y < 0 or x >= width or y >= height for x, y in spot.polygon):
            raise PolygonValidationError(
                f"Spot {spot.spot_id} polygon extends outside {width}x{height} image"
            )
    occupied = sum(spot.occupied for spot in annotation.spots)
    return ValidatedSample(
        annotation, image, width, height, len(annotation.spots) - occupied, occupied
    )


def _new_report(source: str, scope: str) -> dict:
    return {
        "source": source,
        "scope": scope,
        "xml_files_seen": 0,
        "image_files_seen": 0,
        "valid_pairs": 0,
        "class_counts": {"empty": 0, "occupied": 0},
        "camera_counts": {},
        "day_counts": {},
        "dimension_counts": {},
        "overlays": [],
        "errors": [],
    }


def _error(report: dict, code: str, source: str, message: str) -> None:
    report["errors"].append({"code": code, "source": source, "message": message})


def _overlay(sample: ValidatedSample, destination: Path) -> None:
    canvas = sample.image.copy()
    draw = ImageDraw.Draw(canvas)
    for spot in sample.annotation.spots:
        color = (220, 40, 40) if spot.occupied else (20, 150, 80)
        draw.line((*spot.polygon, spot.polygon[0]), fill=color, width=3)
        draw.text(spot.polygon[0], spot.spot_id, fill=color)
    draw.rectangle((0, canvas.height - 18, canvas.width, canvas.height), fill="black")
    draw.text(
        (4, canvas.height - 16),
        "GROUND TRUTH: red=occupied green=empty",
        fill="white",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")


def _record_pair(
    report: dict,
    samples: list[dict],
    image_bytes: bytes,
    xml_bytes: bytes,
    image_name: str,
    xml_name: str,
    output_dir: Path,
    overlays: int,
) -> None:
    try:
        sample = validate_pair(image_bytes, xml_bytes, xml_name)
    except ImageValidationError as exc:
        _error(report, "CORRUPT_IMAGE", image_name, str(exc))
        return
    except PolygonValidationError as exc:
        _error(report, "INVALID_POLYGON", xml_name, str(exc))
        return
    except AnnotationError as exc:
        code = (
            "INVALID_POLYGON" if "polygon" in str(exc).lower() else "INVALID_ANNOTATION"
        )
        _error(report, code, xml_name, str(exc))
        return
    report["valid_pairs"] += 1
    report["class_counts"]["empty"] += sample.empty_count
    report["class_counts"]["occupied"] += sample.occupied_count
    for key, value in (
        ("camera_counts", sample.annotation.camera_id),
        ("day_counts", sample.annotation.capture_day),
        ("dimension_counts", f"{sample.width}x{sample.height}"),
    ):
        counts = report[key]
        counts[value] = counts.get(value, 0) + 1
    samples.append(
        {
            "image": image_name,
            "annotation": xml_name,
            "camera_id": sample.annotation.camera_id,
            "capture_day": sample.annotation.capture_day,
            "width": sample.width,
            "height": sample.height,
            "empty": sample.empty_count,
            "occupied": sample.occupied_count,
        }
    )
    if len(report["overlays"]) < overlays:
        relative = f"overlays/{len(report['overlays']) + 1:03d}.png"
        _overlay(sample, output_dir / relative)
        report["overlays"].append(relative)


def _save(report: dict, samples: list[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, fields, rows in (
        ("samples.csv", SAMPLE_COLUMNS, samples),
        ("errors.csv", ERROR_COLUMNS, report["errors"]),
    ):
        with (output_dir / filename).open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "stats.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def audit_directory(
    root: Path, output_dir: Path, max_samples: int = 0, overlays: int = 3
) -> dict:
    """Scan arbitrary nested folders; zero max_samples means all XML files."""
    root, output_dir = Path(root), Path(output_dir)
    if not root.is_dir():
        raise ValueError(f"Dataset directory does not exist: {root}")
    if max_samples < 0 or overlays < 0:
        raise ValueError("max_samples and overlays must be nonnegative")
    report = _new_report(str(root.resolve()), "sample" if max_samples else "complete")
    samples: list[dict] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name.casefold() != "pklotsegmented")
        xml_names = sorted(
            name for name in files if Path(name).suffix.lower() == ".xml"
        )
        image_names = sorted(
            name for name in files if Path(name).suffix.lower() in IMAGE_SUFFIXES
        )
        by_stem = {Path(name).stem.casefold(): name for name in image_names}
        xml_stems = {Path(name).stem.casefold() for name in xml_names}
        report["image_files_seen"] += len(image_names)
        for name in image_names:
            if Path(name).stem.casefold() not in xml_stems:
                relative = (Path(folder) / name).relative_to(root).as_posix()
                _error(
                    report, "MISSING_ANNOTATION", relative, "Matching XML is missing"
                )
        for name in xml_names:
            if max_samples and report["xml_files_seen"] >= max_samples:
                break
            report["xml_files_seen"] += 1
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            image_name = by_stem.get(path.stem.casefold())
            if image_name is None:
                _error(
                    report, "MISSING_IMAGE", relative, "Matching JPEG/PNG is missing"
                )
                continue
            image_path = Path(folder) / image_name
            try:
                _record_pair(
                    report,
                    samples,
                    image_path.read_bytes(),
                    path.read_bytes(),
                    image_path.relative_to(root).as_posix(),
                    relative,
                    output_dir,
                    overlays,
                )
            except OSError as exc:
                _error(report, "READ_ERROR", relative, str(exc))
        if max_samples and report["xml_files_seen"] >= max_samples:
            break
    if report["xml_files_seen"] == 0:
        raise ValueError(f"No PKLot XML annotations found under {root}")
    return _save(report, samples, output_dir)


def audit_archive(
    archive_path: Path, output_dir: Path, max_samples: int = 3, overlays: int = 3
) -> dict:
    """Audit a bounded sample from a local tar.gz without extracting it."""
    archive_path, output_dir = Path(archive_path), Path(output_dir)
    if not archive_path.is_file():
        raise ValueError(f"Dataset archive does not exist: {archive_path}")
    if max_samples < 1 or overlays < 0:
        raise ValueError("Archive max_samples must be positive; overlays nonnegative")
    report = _new_report(str(archive_path.resolve()), "sample")
    selected: dict[str, bytes] = {}
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            if (
                not member.isfile()
                or PurePosixPath(member.name).suffix.lower() != ".xml"
            ):
                continue
            stream = archive.extractfile(member)
            if stream is not None:
                selected[member.name] = stream.read()
            if len(selected) >= max_samples:
                break
    if not selected:
        raise ValueError(f"No PKLot XML annotations found in {archive_path}")
    report["xml_files_seen"] = len(selected)
    names_by_stem = {
        str(PurePosixPath(name).with_suffix("")): name for name in selected
    }
    images: dict[str, tuple[str, bytes]] = {}
    with tarfile.open(archive_path, "r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            stem = str(path.with_suffix(""))
            if (
                member.isfile()
                and path.suffix.lower() in IMAGE_SUFFIXES
                and stem in names_by_stem
            ):
                stream = archive.extractfile(member)
                if stream is not None:
                    images[stem] = (member.name, stream.read())
            if len(images) == len(selected):
                break
    report["image_files_seen"] = len(images)
    samples: list[dict] = []
    for stem, xml_name in names_by_stem.items():
        match = images.get(stem)
        if match is None:
            _error(report, "MISSING_IMAGE", xml_name, "Matching JPEG/PNG is missing")
            continue
        image_name, image_bytes = match
        _record_pair(
            report,
            samples,
            image_bytes,
            selected[xml_name],
            image_name,
            xml_name,
            output_dir,
            overlays,
        )
    return _save(report, samples, output_dir)
