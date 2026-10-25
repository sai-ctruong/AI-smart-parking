"""Capture-day splitting with conservative frame similarity grouping."""

import random
from dataclasses import dataclass

from PIL import Image

from data.pklot_parser import SpotAnnotation


class SplitError(ValueError):
    """A leakage-safe three-way split cannot be constructed."""


@dataclass(frozen=True)
class Frame:
    image: str
    annotation: str
    camera_id: str
    capture_day: str
    width: int
    height: int
    fingerprint: int
    spots: tuple[SpotAnnotation, ...]


def frame_fingerprint(image: Image.Image) -> int:
    """64-bit difference hash of a full frame, independent of crop labels."""
    small = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = small.tobytes()
    value = 0
    for row in range(8):
        for col in range(8):
            value = (value << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return value


def split_frames(
    frames: list[Frame],
    seed: int = 42,
    near_duplicate_hamming: int = 4,
    train_fraction: float = 0.7,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
) -> dict[str, str]:
    """Assign whole capture-day components to splits; never split a frame."""
    if not frames:
        raise SplitError("No validated frames for the selected camera")
    if any(not frame.capture_day for frame in frames):
        raise SplitError("Missing capture day; cannot make a leakage-safe split")
    if len({frame.camera_id for frame in frames}) != 1:
        raise SplitError("Select exactly one camera before splitting")
    if not 0 <= near_duplicate_hamming <= 64:
        raise SplitError("near_duplicate_hamming must be between 0 and 64")
    if (
        any(value <= 0 for value in (train_fraction, val_fraction, test_fraction))
        or not abs(train_fraction + val_fraction + test_fraction - 1) < 1e-9
    ):
        raise SplitError("Split fractions must be positive and sum to 1")

    days = sorted({frame.capture_day for frame in frames})
    parent = {day: day for day in days}

    def find(day: str) -> str:
        while parent[day] != day:
            parent[day] = parent[parent[day]]
            day = parent[day]
        return day

    def union(first: str, second: str) -> None:
        first, second = find(first), find(second)
        if first != second:
            parent[max(first, second)] = min(first, second)

    # One entry per fingerprint is enough; matching frames connect all their days.
    hashes: dict[int, set[str]] = {}
    for frame in frames:
        hashes.setdefault(frame.fingerprint, set()).add(frame.capture_day)
    unique = sorted(hashes)
    for index, first_hash in enumerate(unique):
        for second_hash in unique[index:]:
            if (first_hash ^ second_hash).bit_count() <= near_duplicate_hamming:
                joined = sorted(hashes[first_hash] | hashes[second_hash])
                for day in joined[1:]:
                    union(joined[0], day)
    components: dict[str, list[str]] = {}
    for day in days:
        components.setdefault(find(day), []).append(day)
    groups = sorted(components.values())
    if len(groups) < 3:
        raise SplitError(
            f"Need at least 3 independent capture-day groups; found {len(groups)} "
            "after near-duplicate grouping"
        )
    random.Random(seed).shuffle(groups)
    count = len(groups)
    val_count = max(1, round(count * val_fraction))
    test_count = max(1, round(count * test_fraction))
    if val_count + test_count >= count:
        val_count = test_count = 1
    train_count = count - val_count - test_count
    assignments: dict[str, str] = {}
    for split, selected in (
        ("train", groups[:train_count]),
        ("val", groups[train_count : train_count + val_count]),
        ("test", groups[train_count + val_count :]),
    ):
        for group in selected:
            for day in group:
                assignments[day] = split
    return assignments
