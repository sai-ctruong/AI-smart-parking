"""Reuse one checkpoint for batched, annotation-free ROI inference."""

import hashlib
import math
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image

from data.preprocessing import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    crop_polygon,
    transform_image,
)
from inference.schemas import SpotPrediction
from models.mobilenet_classifier import load_checkpoint


def _resolve_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be auto, cpu, or cuda")
    return requested


def _intersects(a, b, c, d) -> bool:
    def orientation(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    ab_c, ab_d = orientation(a, b, c), orientation(a, b, d)
    cd_a, cd_b = orientation(c, d, a), orientation(c, d, b)

    def on_segment(p, q, r):
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and (
            min(p[1], r[1]) <= q[1] <= max(p[1], r[1])
        )

    return (
        (ab_c * ab_d < 0 and cd_a * cd_b < 0)
        or (ab_c == 0 and on_segment(a, c, b))
        or (ab_d == 0 and on_segment(a, d, b))
        or (cd_a == 0 and on_segment(c, a, d))
        or (cd_b == 0 and on_segment(c, b, d))
    )


def _pixel_polygon(points, size: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise ValueError("polygon needs at least three points")
    normalized = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("each polygon point needs x and y")
        x, y = point
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
        normalized.append((x, y))
    if len(set(normalized)) != len(normalized):
        raise ValueError("polygon points must be distinct")
    area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(normalized, normalized[1:] + normalized[:1])
    )
    if abs(area) < 1e-12:
        raise ValueError("polygon area must be positive")
    count = len(normalized)
    for first in range(count):
        for second in range(first + 2, count):
            if first == 0 and second == count - 1:
                continue
            if _intersects(
                normalized[first],
                normalized[(first + 1) % count],
                normalized[second],
                normalized[(second + 1) % count],
            ):
                raise ValueError("polygon edges intersect")
    width, height = size
    pixel = tuple(
        (round(x * (width - 1)), round(y * (height - 1))) for x, y in normalized
    )
    if len(set(pixel)) < 3:
        raise ValueError("polygon is too small at image resolution")
    return pixel


class ParkingOccupancyPredictor:
    """Load a saved binary MobileNet once, then classify normalized ROIs."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        *,
        confidence_threshold: float = 0.7,
        batch_size: int = 32,
        device: str = "auto",
    ) -> None:
        if (
            isinstance(confidence_threshold, bool)
            or not isinstance(confidence_threshold, (int, float))
            or not math.isfinite(confidence_threshold)
            or not 0.5 <= confidence_threshold <= 1
        ):
            raise ValueError("confidence_threshold must be finite in [0.5,1]")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("batch_size must be a positive integer")
        path = Path(checkpoint_path)
        if not path.is_file():
            raise FileNotFoundError(f"Model checkpoint does not exist: {path}")
        self.device = _resolve_device(device)
        try:
            self.model, metadata = load_checkpoint(path, self.device)
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            raise ValueError(f"Cannot load model checkpoint {path}: {exc}") from exc
        preprocessing = metadata.get("preprocessing")
        if not isinstance(preprocessing, dict):
            raise ValueError("Checkpoint has no preprocessing metadata")
        size = preprocessing.get("image_size")
        normalized = preprocessing.get("imagenet_normalization")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError("Checkpoint has invalid preprocessing image_size")
        if not isinstance(normalized, bool):
            raise ValueError("Checkpoint has invalid normalization metadata")
        expected_mean = IMAGENET_MEAN if normalized else (0.0, 0.0, 0.0)
        expected_std = IMAGENET_STD if normalized else (1.0, 1.0, 1.0)
        if (
            preprocessing.get("polygon_crop") != "masked_tight_square_pad"
            or list(preprocessing.get("mean", [])) != list(expected_mean)
            or list(preprocessing.get("std", [])) != list(expected_std)
        ):
            raise ValueError("Checkpoint preprocessing is incompatible with inference")
        self.image_size = size
        self.imagenet_normalization = normalized
        self.confidence_threshold = confidence_threshold
        self.batch_size = batch_size
        self.model_version = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        self.metadata = metadata

    def predict_spots(
        self, image: Image.Image, polygons: list[dict]
    ) -> list[SpotPrediction]:
        """Classify spots in input order; invalid polygons become unknown.

        `polygons` contains {"spot_id": str, "polygon": [[x,y], ...]}; x/y are
        normalized coordinates in [0,1]. No labels or XML are accepted.
        """
        if not isinstance(image, Image.Image):
            raise ValueError("image must be a PIL Image")
        try:
            image.load()
            if image.width < 2 or image.height < 2:
                raise ValueError("image must be at least 2x2 pixels")
            rgb = image.convert("RGB")
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid image: {exc}") from exc
        if not isinstance(polygons, (list, tuple)):
            raise ValueError("polygons must be an ordered list")
        results: list[SpotPrediction | None] = [None] * len(polygons)
        valid = []
        seen = set()
        for index, region in enumerate(polygons):
            if (
                not isinstance(region, dict)
                or not isinstance(region.get("spot_id"), str)
                or not region["spot_id"]
            ):
                raise ValueError(f"polygons[{index}] needs a nonempty spot_id")
            spot_id = region["spot_id"]
            if spot_id in seen:
                raise ValueError(f"Duplicate spot_id: {spot_id}")
            seen.add(spot_id)
            try:
                pixels = _pixel_polygon(region.get("polygon"), rgb.size)
                crop = crop_polygon(rgb, pixels)
                prepared = transform_image(
                    crop,
                    "test",
                    size=self.image_size,
                    pretrained=self.imagenet_normalization,
                )
            except (TypeError, ValueError):
                results[index] = SpotPrediction(
                    spot_id,
                    "unknown",
                    None,
                    None,
                    self.model_version,
                    uncertainty_reason="invalid_polygon",
                )
                continue
            valid.append((index, spot_id, prepared))
        if valid:
            import torch

            for start in range(0, len(valid), self.batch_size):
                batch = valid[start : start + self.batch_size]
                inputs = torch.stack([item.to_tensor() for _, _, item in batch]).to(
                    self.device
                )
                try:
                    with torch.inference_mode():
                        logits = self.model(inputs)
                        probabilities = torch.softmax(logits, dim=1).cpu().tolist()
                except RuntimeError as exc:
                    raise RuntimeError(f"Model inference failed: {exc}") from exc
                if len(probabilities) != len(batch) or any(
                    len(row) != 2 for row in probabilities
                ):
                    raise RuntimeError("Model returned an invalid output shape")
                for (index, spot_id, _), row in zip(batch, probabilities):
                    if not all(math.isfinite(value) for value in row):
                        results[index] = SpotPrediction(
                            spot_id,
                            "unknown",
                            None,
                            None,
                            self.model_version,
                            uncertainty_reason="non_finite_output",
                        )
                        continue
                    confidence = max(row)
                    status = "empty" if row[0] >= row[1] else "occupied"
                    reason = None
                    if confidence < self.confidence_threshold:
                        status = "unknown"
                        reason = "low_confidence"
                    results[index] = SpotPrediction(
                        spot_id,
                        status,
                        confidence,
                        {"empty": row[0], "occupied": row[1]},
                        self.model_version,
                        uncertainty_reason=reason,
                    )
        return results


@lru_cache(maxsize=4)
def _configured_predictor(path: str, threshold: float, batch_size: int, device: str):
    return ParkingOccupancyPredictor(
        path, confidence_threshold=threshold, batch_size=batch_size, device=device
    )


def predict_spots(image: Image.Image, polygons: list[dict]) -> list[SpotPrediction]:
    """Use a cached predictor configured by PARKING_MODEL_CHECKPOINT and options."""
    checkpoint = os.getenv("PARKING_MODEL_CHECKPOINT")
    if not checkpoint:
        raise ValueError("PARKING_MODEL_CHECKPOINT is required for inference")
    return _configured_predictor(
        checkpoint,
        float(os.getenv("PARKING_CONFIDENCE_THRESHOLD", "0.7")),
        int(os.getenv("PARKING_INFERENCE_BATCH_SIZE", "32")),
        os.getenv("PARKING_INFERENCE_DEVICE", "auto"),
    ).predict_spots(image, polygons)
