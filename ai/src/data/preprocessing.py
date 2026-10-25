"""Read-only polygon crops and MobileNetV3-Small input preparation."""

import random
from array import array
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
OUTSIDE_COLOR = tuple(round(channel * 255) for channel in IMAGENET_MEAN)


@dataclass(frozen=True)
class ModelInput:
    pixels: array
    shape: tuple[int, int, int]

    def to_tensor(self):
        """Convert to a PyTorch tensor when the optional vision extra is installed."""
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Install the AI vision extra to create torch tensors"
            ) from exc
        return torch.tensor(self.pixels, dtype=torch.float32).reshape(self.shape)


def crop_polygon(
    image: Image.Image, polygon: tuple[tuple[int, int], ...]
) -> Image.Image:
    """Tight bounding crop; mask every pixel outside the polygon.

    Keeps source orientation for both rotated and irregular contours. The source
    image is never edited. Geometry must already have passed PKLot validation.
    """
    if len(polygon) < 3 or any(
        x < 0 or y < 0 or x >= image.width or y >= image.height for x, y in polygon
    ):
        raise ValueError("Polygon must have >=3 in-bounds points")
    left = min(x for x, _ in polygon)
    top = min(y for _, y in polygon)
    right = max(x for x, _ in polygon) + 1
    bottom = max(y for _, y in polygon) + 1
    if right - left < 2 or bottom - top < 2:
        raise ValueError("Polygon bounding box is too small")
    mask = Image.new("L", (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).polygon([(x - left, y - top) for x, y in polygon], fill=255)
    foreground = image.convert("RGB").crop((left, top, right, bottom))
    return Image.composite(
        foreground, Image.new("RGB", foreground.size, OUTSIDE_COLOR), mask
    )


def _resize_square(image: Image.Image, size: int) -> Image.Image:
    if size < 1:
        raise ValueError("size must be positive")
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), OUTSIDE_COLOR)
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    return canvas.resize((size, size), Image.Resampling.BILINEAR)


def transform_image(
    image: Image.Image,
    split: str,
    *,
    seed: int = 42,
    size: int = 224,
    pretrained: bool = True,
) -> ModelInput:
    """Train-only augmentation; deterministic validation/test normalization."""
    if split not in {"train", "val", "test"}:
        raise ValueError("split must be train, val, or test")
    prepared = _resize_square(image.convert("RGB"), size)
    if split == "train":
        rng = random.Random(seed)
        if rng.random() < 0.5:
            prepared = ImageOps.mirror(prepared)
        prepared = ImageEnhance.Brightness(prepared).enhance(rng.uniform(0.9, 1.1))
    raw = prepared.tobytes()
    channels = array("f")
    for channel in range(3):
        mean = IMAGENET_MEAN[channel] if pretrained else 0.0
        std = IMAGENET_STD[channel] if pretrained else 1.0
        channels.extend(
            (
                (raw[offset] / 255.0 - mean) / std
                for offset in range(channel, len(raw), 3)
            )
        )
    return ModelInput(channels, (3, size, size))
