"""Behavioral checks for ROI preparation and leakage-safe manifests."""

import json
import random
from pathlib import Path

import pytest
from PIL import Image

from data.dataset import PKLotDataset, prepare_dataset
from data.preprocessing import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    crop_polygon,
    transform_image,
)
from data.split import Frame, SplitError, split_frames


def _frame(day: str, name: str, fingerprint: int) -> Frame:
    return Frame(
        name, name.replace(".png", ".xml"), "UFPR04", day, 32, 32, fingerprint, ()
    )


def _source(root: Path, day: str, name: str, color: str, label: str = "1") -> None:
    folder = root / "UFPR04" / day
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(day[5:7]))
    image = Image.new("RGB", (32, 32), color)
    image.putdata(
        [
            (value, value, value)
            for value in (rng.randrange(256) for _ in range(32 * 32))
        ]
    )
    image.save(folder / f"{name}.png")
    (folder / f"{name}.xml").write_text(
        '<parking id="UFPR04"><space id="7" occupied="' + label + '">'
        '<contour><point x="4" y="4"/><point x="24" y="4"/>'
        '<point x="24" y="24"/><point x="4" y="24"/></contour>'
        "</space></parking>",
        encoding="utf-8",
    )


def test_polygon_crop_masks_irregular_area_without_mutating_source() -> None:
    image = Image.new("RGB", (20, 20), (200, 10, 10))
    polygon = ((2, 2), (17, 2), (10, 17))
    crop = crop_polygon(image, polygon)

    assert crop.size == (16, 16)
    assert crop.getpixel((8, 5)) == (200, 10, 10)
    assert crop.getpixel((0, 15)) != (200, 10, 10)
    assert image.getpixel((2, 17)) == (200, 10, 10)


def test_rotated_roi_uses_the_same_masked_bounding_rule() -> None:
    image = Image.new("RGB", (21, 21), (10, 40, 180))
    crop = crop_polygon(image, ((10, 1), (19, 10), (10, 19), (1, 10)))

    assert crop.size == (19, 19)
    assert crop.getpixel((9, 9)) == (10, 40, 180)
    assert crop.getpixel((0, 0)) != (10, 40, 180)


def test_validation_transform_is_repeatable_and_imagenet_normalized() -> None:
    image = Image.new("RGB", (12, 8), "white")
    first = transform_image(image, "val", seed=1, size=8, pretrained=True)
    second = transform_image(image, "test", seed=99, size=8, pretrained=True)

    assert first.shape == (3, 8, 8)
    assert first.pixels == second.pixels
    assert first.pixels[3 * 8 + 3] == pytest.approx(
        (1 - IMAGENET_MEAN[0]) / IMAGENET_STD[0]
    )


def test_train_transform_uses_seeded_augmentation_only_for_train() -> None:
    image = Image.new("RGB", (10, 10), (120, 120, 120))

    assert (
        transform_image(image, "train", seed=1, size=8).pixels
        == transform_image(image, "train", seed=1, size=8).pixels
    )
    assert (
        transform_image(image, "train", seed=1, size=8).pixels
        != transform_image(image, "train", seed=2, size=8).pixels
    )
    assert (
        transform_image(image, "val", seed=1, size=8).pixels
        == transform_image(image, "val", seed=2, size=8).pixels
    )


def test_near_duplicate_dates_are_grouped_and_seed_is_repeatable() -> None:
    frames = [
        _frame("2012-01-01", "a.png", 0),
        _frame("2012-01-02", "b.png", 1),
        _frame("2012-01-03", "c.png", 0xFFFF0000FFFF0000),
        _frame("2012-01-04", "d.png", 0x0000FFFF0000FFFF),
    ]
    first = split_frames(frames, seed=23, near_duplicate_hamming=1)
    second = split_frames(list(reversed(frames)), seed=23, near_duplicate_hamming=1)

    assert first == second
    assert first["2012-01-01"] == first["2012-01-02"]
    assert set(first.values()) == {"train", "val", "test"}


def test_missing_dates_or_too_few_independent_days_fail_closed() -> None:
    with pytest.raises(SplitError, match="capture day"):
        split_frames([_frame("", "a.png", 0)])
    with pytest.raises(SplitError, match="independent"):
        split_frames([_frame("2012-01-01", "a.png", 0)])


def test_prepare_writes_reproducible_manifests_and_visual_samples(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    for day, color, label in (
        ("2012-01-01", "red", "1"),
        ("2012-02-01", "green", "0"),
        ("2012-03-01", "blue", "1"),
    ):
        _source(root, day, "frame", color, label)
    first = tmp_path / "first"
    second = tmp_path / "second"

    summary = prepare_dataset(root, first, "UFPR04", seed=7, visual_samples_per_split=1)
    prepare_dataset(root, second, "UFPR04", seed=7, visual_samples_per_split=1)

    all_rows = []
    for split in ("train", "val", "test"):
        manifest = first / f"{split}.jsonl"
        assert manifest.read_bytes() == (second / f"{split}.jsonl").read_bytes()
        rows = [json.loads(line) for line in manifest.read_text().splitlines()]
        assert len(rows) == 1
        row = rows[0]
        assert (root / row["source_image"]).is_file()
        assert (root / row["source_annotation"]).is_file()
        assert row["label"] in {"empty", "occupied"}
        assert row["polygon"] == [[4, 4], [24, 4], [24, 24], [4, 24]]
        assert list((first / "visual_samples" / split).glob("*.png"))
        all_rows += rows
    assert len({row["capture_day"] for row in all_rows}) == 3
    assert summary["split_sizes"] == {"train": 1, "val": 1, "test": 1}
    dataset = PKLotDataset(first / "train.jsonl", root, split="train", size=16)
    model_input, label, metadata = dataset[0]
    assert model_input.shape == (3, 16, 16)
    assert label in {0, 1}
    assert metadata["source_image"]


def test_prepare_rejects_unmatched_images_without_partial_manifests(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    _source(root, "2012-01-01", "frame", "white")
    Image.new("RGB", (32, 32), "black").save(
        root / "UFPR04" / "2012-01-01" / "orphan.png"
    )
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="matching annotation"):
        prepare_dataset(root, output, "UFPR04")
    assert not (output / "train.jsonl").exists()
