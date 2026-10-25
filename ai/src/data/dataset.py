"""Validated PKLot frame index, lazy ROI dataset and split manifests."""

import json
import os
from pathlib import Path

from PIL import Image

from data.preprocessing import ModelInput, crop_polygon, transform_image
from data.split import Frame, frame_fingerprint, split_frames
from data.validation import IMAGE_SUFFIXES, validate_pair


def discover_frames(root: Path, camera_id: str) -> list[Frame]:
    """Validate all full-frame pairs before selecting one camera."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Dataset directory does not exist: {root}")
    frames: list[Frame] = []
    seen_xml = 0
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name.casefold() != "pklotsegmented")
        xmls = sorted(name for name in files if Path(name).suffix.lower() == ".xml")
        images = sorted(
            name for name in files if Path(name).suffix.lower() in IMAGE_SUFFIXES
        )
        by_stem: dict[str, str] = {}
        for name in images:
            stem = Path(name).stem.casefold()
            if stem in by_stem:
                raise ValueError(f"Ambiguous images for {folder / stem}")
            by_stem[stem] = name
        xml_stems = {Path(name).stem.casefold() for name in xmls}
        for name in images:
            if Path(name).stem.casefold() not in xml_stems:
                raise ValueError(
                    f"Image has no matching annotation: {Path(folder) / name}"
                )
        for name in xmls:
            seen_xml += 1
            xml_path = Path(folder) / name
            image_name = by_stem.get(xml_path.stem.casefold())
            if image_name is None:
                raise ValueError(f"Annotation has no matching image: {xml_path}")
            image_path = Path(folder) / image_name
            relative_xml = xml_path.relative_to(root).as_posix()
            try:
                sample = validate_pair(
                    image_path.read_bytes(), xml_path.read_bytes(), relative_xml
                )
            except (OSError, ValueError) as exc:
                raise ValueError(f"Invalid PKLot pair {relative_xml}: {exc}") from exc
            if sample.annotation.camera_id == camera_id.upper():
                frames.append(
                    Frame(
                        image_path.relative_to(root).as_posix(),
                        relative_xml,
                        sample.annotation.camera_id,
                        sample.annotation.capture_day,
                        sample.width,
                        sample.height,
                        frame_fingerprint(sample.image),
                        sample.annotation.spots,
                    )
                )
    if not seen_xml:
        raise ValueError(f"No PKLot XML annotations found under {root}")
    if not frames:
        raise ValueError(
            f"No validated frames for camera {camera_id.upper()} under {root}"
        )
    return frames


def _row(frame: Frame, split: str, spot) -> dict:
    return {
        "source_image": frame.image,
        "source_annotation": frame.annotation,
        "camera_id": frame.camera_id,
        "capture_day": frame.capture_day,
        "source_frame": frame.image,
        "spot_id": spot.spot_id,
        "polygon": [list(point) for point in spot.polygon],
        "label": "occupied" if spot.occupied else "empty",
        "image_width": frame.width,
        "image_height": frame.height,
        "frame_fingerprint": f"{frame.fingerprint:016x}",
        "split": split,
    }


def prepare_dataset(
    root: Path,
    output: Path,
    camera_id: str,
    *,
    seed: int = 42,
    near_duplicate_hamming: int = 4,
    train_fraction: float = 0.7,
    val_fraction: float = 0.15,
    test_fraction: float = 0.15,
    size: int = 224,
    pretrained: bool = True,
    visual_samples_per_split: int = 3,
) -> dict:
    """Write lazy-crop manifests and a small visual audit after full validation."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("Output must be outside the raw dataset directory")
    if visual_samples_per_split < 0 or size < 1:
        raise ValueError("Visual sample count must be nonnegative and size positive")
    frames = discover_frames(root, camera_id)
    day_splits = split_frames(
        frames,
        seed=seed,
        near_duplicate_hamming=near_duplicate_hamming,
        train_fraction=train_fraction,
        val_fraction=val_fraction,
        test_fraction=test_fraction,
    )
    manifests: dict[str, list[dict]] = {name: [] for name in ("train", "val", "test")}
    for frame in sorted(frames, key=lambda item: item.image):
        split = day_splits[frame.capture_day]
        manifests[split].extend(_row(frame, split, spot) for spot in frame.spots)
    summary = {
        "camera_id": camera_id.upper(),
        "seed": seed,
        "image_size": size,
        "pretrained": pretrained,
        "near_duplicate_hamming": near_duplicate_hamming,
        "source_frame_count": len(frames),
        "capture_day_count": len(day_splits),
        "split_sizes": {name: len(rows) for name, rows in manifests.items()},
        "split_days": {
            name: sorted(
                day for day, assigned in day_splits.items() if assigned == name
            )
            for name in manifests
        },
        "class_counts": {
            name: {
                label: sum(row["label"] == label for row in rows)
                for label in ("empty", "occupied")
            }
            for name, rows in manifests.items()
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in manifests.items():
        (output / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        for index, row in enumerate(rows[:visual_samples_per_split], start=1):
            with Image.open(root / row["source_image"]) as image:
                crop = crop_polygon(image, tuple(map(tuple, row["polygon"])))
            destination = (
                output / "visual_samples" / name / f"{index:03d}_{row['label']}.png"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            crop.save(destination, format="PNG")
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


class PKLotDataset:
    """Load polygon crops lazily; returns normalized CHW data and metadata."""

    def __init__(
        self,
        manifest: Path,
        root: Path,
        *,
        split: str,
        size: int = 224,
        pretrained: bool = True,
        seed: int = 42,
    ) -> None:
        if split not in {"train", "val", "test"}:
            raise ValueError("split must be train, val, or test")
        self.rows = [
            json.loads(line)
            for line in Path(manifest).read_text(encoding="utf-8").splitlines()
        ]
        if any(row["split"] != split for row in self.rows):
            raise ValueError("Manifest contains a row from another split")
        self.root = Path(root).resolve()
        self.split = split
        self.size = size
        self.pretrained = pretrained
        self.seed = seed
        self.epoch = 0

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[ModelInput, int, dict]:
        row = self.rows[index]
        source = (self.root / row["source_image"]).resolve()
        if not source.is_relative_to(self.root):
            raise ValueError("Manifest source image escapes dataset root")
        with Image.open(source) as image:
            crop = crop_polygon(image, tuple(map(tuple, row["polygon"])))
        prepared = transform_image(
            crop,
            self.split,
            seed=self.seed + self.epoch * len(self.rows) + index,
            size=self.size,
            pretrained=self.pretrained,
        )
        return prepared, int(row["label"] == "occupied"), row

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch
