"""Inference contracts using a real checkpoint and synthetic image only."""

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
Image = pytest.importorskip("PIL.Image")

from inference.predictor import ParkingOccupancyPredictor, predict_spots  # noqa: E402
from models.mobilenet_classifier import build_model, save_checkpoint  # noqa: E402


@pytest.fixture
def checkpoint(tmp_path: Path) -> Path:
    model = build_model(pretrained=False)
    model.classifier[-1].weight.data.zero_()
    model.classifier[-1].bias.data.copy_(torch.tensor([2.0, -2.0]))
    path = tmp_path / "model.pt"
    save_checkpoint(
        path,
        model,
        {
            "scope": "synthetic_smoke",
            "model_architecture": "torchvision.mobilenet_v3_small",
            "class_mapping": {"empty": 0, "occupied": 1},
            "preprocessing": {
                "image_size": 32,
                "imagenet_normalization": False,
                "mean": [0.0, 0.0, 0.0],
                "std": [1.0, 1.0, 1.0],
                "polygon_crop": "masked_tight_square_pad",
            },
        },
    )
    return path


def test_binary_predictions_keep_spot_order_and_metadata(checkpoint: Path) -> None:
    predictor = ParkingOccupancyPredictor(checkpoint, batch_size=1, device="cpu")
    model = predictor.model
    image = Image.new("RGB", (64, 64), "white")
    regions = [
        {"spot_id": "A", "polygon": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4]]},
        {"spot_id": "B", "polygon": [[0.5, 0.5], [0.9, 0.5], [0.9, 0.9]]},
    ]

    result = predictor.predict_spots(image, regions)

    assert [item.spot_id for item in result] == ["A", "B"]
    assert [item.predicted_status for item in result] == ["empty", "empty"]
    assert all(item.confidence > 0.9 for item in result)
    assert all(item.class_probabilities["empty"] > 0.9 for item in result)
    assert all(item.calibrated_confidence is None for item in result)
    assert all(item.model_version == predictor.model_version for item in result)
    assert predictor.model is model


def test_occupied_and_low_confidence_unknown(checkpoint: Path) -> None:
    image = Image.new("RGB", (32, 32), "white")
    polygon = [{"spot_id": "A", "polygon": [[0, 0], [1, 0], [1, 1]]}]
    payload = torch.load(checkpoint, weights_only=True)
    payload["state_dict"]["classifier.3.bias"] = torch.tensor([-2.0, 2.0])
    torch.save(payload, checkpoint)
    occupied = ParkingOccupancyPredictor(checkpoint).predict_spots(image, polygon)[0]
    assert occupied.predicted_status == "occupied"
    assert occupied.class_probabilities["occupied"] > 0.9

    payload["state_dict"]["classifier.3.bias"] = torch.tensor([0.0, 0.0])
    torch.save(payload, checkpoint)
    unknown = ParkingOccupancyPredictor(
        checkpoint, confidence_threshold=0.8
    ).predict_spots(image, polygon)[0]
    assert unknown.predicted_status == "unknown"
    assert unknown.confidence == pytest.approx(0.5)
    assert unknown.class_probabilities == pytest.approx({"empty": 0.5, "occupied": 0.5})
    assert unknown.uncertainty_reason == "low_confidence"


def test_bad_rois_return_unknown_without_disrupting_valid_spots(
    checkpoint: Path,
) -> None:
    predictor = ParkingOccupancyPredictor(checkpoint)
    image = Image.new("RGB", (64, 64), "white")
    regions = [
        {"spot_id": "outside", "polygon": [[0, 0], [1.1, 0], [1, 1]]},
        {"spot_id": "valid", "polygon": [[0, 0], [1, 0], [1, 1]]},
        {"spot_id": "line", "polygon": [[0, 0], [0.5, 0.5], [1, 1]]},
        {"spot_id": "cross", "polygon": [[0, 0], [1, 1], [1, 0], [0, 1]]},
    ]

    result = predictor.predict_spots(image, regions)

    assert [item.spot_id for item in result] == ["outside", "valid", "line", "cross"]
    assert [item.predicted_status for item in result] == [
        "unknown",
        "empty",
        "unknown",
        "unknown",
    ]
    for index in (0, 2, 3):
        assert result[index].confidence is None
        assert result[index].class_probabilities is None
        assert result[index].uncertainty_reason == "invalid_polygon"


def test_missing_checkpoint_and_bad_image_raise_clear_errors(checkpoint: Path) -> None:
    with pytest.raises(FileNotFoundError, match="checkpoint"):
        ParkingOccupancyPredictor(checkpoint.parent / "missing.pt")
    with pytest.raises(ValueError, match="confidence_threshold"):
        ParkingOccupancyPredictor(checkpoint, confidence_threshold=1.5)
    with pytest.raises(ValueError, match="confidence_threshold"):
        ParkingOccupancyPredictor(checkpoint, confidence_threshold=True)
    with pytest.raises(ValueError, match="image"):
        ParkingOccupancyPredictor(checkpoint).predict_spots("not an image", [])


def test_module_function_reads_configured_checkpoint(
    checkpoint: Path, monkeypatch
) -> None:
    monkeypatch.setenv("PARKING_MODEL_CHECKPOINT", str(checkpoint))
    image = Image.new("RGB", (32, 32), "white")
    result = predict_spots(
        image, [{"spot_id": "A", "polygon": [[0, 0], [1, 0], [1, 1]]}]
    )
    assert result[0].predicted_status == "empty"
    assert result[0].model_version
