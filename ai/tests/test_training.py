"""Training contracts; synthetic examples are never reported as PKLot metrics."""

import json
from pathlib import Path

import pytest

from training.evaluate import classification_metrics
from training.train import validate_split_manifests


def _write_rows(root: Path, split: str, rows: list[dict]) -> None:
    (root / f"{split}.jsonl").write_text(
        "".join(json.dumps({**row, "split": split}) + "\n" for row in rows),
        encoding="utf-8",
    )


def _row(day: str, image: str, fingerprint: str, label: str = "empty") -> dict:
    return {
        "camera_id": "UFPR04",
        "capture_day": day,
        "source_image": image,
        "source_annotation": image.replace(".png", ".xml"),
        "frame_fingerprint": fingerprint,
        "label": label,
        "spot_id": "1",
        "polygon": [[0, 0], [3, 0], [3, 3], [0, 3]],
    }


def test_metrics_include_both_error_directions() -> None:
    result = classification_metrics([0, 0, 1, 1], [0, 1, 0, 1])

    assert result["confusion_matrix"] == [[1, 1], [1, 1]]
    assert result["false_occupied"] == 1
    assert result["false_empty"] == 1
    assert result["accuracy"] == 0.5
    assert result["macro_f1"] == 0.5
    assert result["per_class"]["empty"]["precision"] == 0.5
    assert result["per_class"]["occupied"]["recall"] == 0.5


def test_metrics_define_zero_denominator_as_zero() -> None:
    result = classification_metrics([0, 0], [0, 0])

    assert result["per_class"]["occupied"] == {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "support": 0,
    }


def test_manifest_guard_rejects_capture_day_overlap(tmp_path: Path) -> None:
    _write_rows(tmp_path, "train", [_row("2012-01-01", "a.png", "0000000000000000")])
    _write_rows(tmp_path, "val", [_row("2012-01-01", "b.png", "ffffffffffffffff")])
    _write_rows(tmp_path, "test", [_row("2012-01-03", "c.png", "aaaaaaaaaaaaaaaa")])

    with pytest.raises(ValueError, match="capture day"):
        validate_split_manifests(tmp_path)


def test_manifest_guard_rejects_similar_frame_across_splits(tmp_path: Path) -> None:
    _write_rows(tmp_path, "train", [_row("2012-01-01", "a.png", "0000000000000000")])
    _write_rows(tmp_path, "val", [_row("2012-01-02", "b.png", "0000000000000001")])
    _write_rows(tmp_path, "test", [_row("2012-01-03", "c.png", "ffffffffffffffff")])

    with pytest.raises(ValueError, match="near-duplicate"):
        validate_split_manifests(tmp_path, near_duplicate_hamming=4)


def test_manifest_guard_accepts_three_independent_splits(tmp_path: Path) -> None:
    _write_rows(tmp_path, "train", [_row("2012-01-01", "a.png", "0000000000000000")])
    _write_rows(tmp_path, "val", [_row("2012-01-02", "b.png", "ffffffffffffffff")])
    _write_rows(tmp_path, "test", [_row("2012-01-03", "c.png", "aaaaaaaaaaaaaaaa")])

    report = validate_split_manifests(tmp_path)

    assert report["split_sizes"] == {"train": 1, "val": 1, "test": 1}
    assert len(report["manifest_sha256"]["train"]) == 64


def test_manifest_guard_rejects_unknown_ground_truth(tmp_path: Path) -> None:
    _write_rows(
        tmp_path,
        "train",
        [_row("2012-01-01", "a.png", "0000000000000000", "unknown")],
    )
    _write_rows(tmp_path, "val", [_row("2012-01-02", "b.png", "ffffffffffffffff")])
    _write_rows(tmp_path, "test", [_row("2012-01-03", "c.png", "aaaaaaaaaaaaaaaa")])

    with pytest.raises(ValueError, match="ground-truth label"):
        validate_split_manifests(tmp_path)


def test_checkpoint_loads_without_imagenet_download(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    from models.mobilenet_classifier import (
        build_model,
        load_checkpoint,
        save_checkpoint,
    )

    model = build_model(pretrained=False)
    path = tmp_path / "best.pt"
    metadata = {
        "class_mapping": {"empty": 0, "occupied": 1},
        "preprocessing": {"image_size": 64, "imagenet_normalization": True},
        "dataset_version": "synthetic-test",
        "torch_version": torch.__version__,
    }
    save_checkpoint(path, model, metadata)
    loaded, restored = load_checkpoint(path, "cpu")

    assert restored["torch_version"] == str(torch.__version__)
    assert restored["class_mapping"] == metadata["class_mapping"]
    assert torch.equal(model.classifier[-1].weight, loaded.classifier[-1].weight)


def test_real_model_requests_imagenet_v1_weights_without_downloading(
    monkeypatch,
) -> None:
    pytest.importorskip("torch")
    torchvision = pytest.importorskip("torchvision")
    from models.mobilenet_classifier import build_model

    requested = []
    original = torchvision.models.mobilenet_v3_small

    def local_builder(*, weights):
        requested.append(weights)
        return original(weights=None)

    monkeypatch.setattr(torchvision.models, "mobilenet_v3_small", local_builder)
    model = build_model(pretrained=True)

    assert requested == [torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1]
    assert model.classifier[-1].out_features == 2
