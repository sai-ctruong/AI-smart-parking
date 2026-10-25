"""Held-out classifier metrics; ground truth and predictions stay distinct."""

import json
import time
from pathlib import Path


def classification_metrics(actual: list[int], predicted: list[int]) -> dict:
    """Binary metrics with rows=true and columns=predicted; 0=empty, 1=occupied."""
    if len(actual) != len(predicted) or not actual:
        raise ValueError("Actual and predicted labels must have equal nonzero length")
    if any(value not in (0, 1) for value in actual + predicted):
        raise ValueError("Only binary labels 0 and 1 are supported")
    matrix = [[0, 0], [0, 0]]
    for truth, prediction in zip(actual, predicted):
        matrix[truth][prediction] += 1
    per_class = {}
    for index, name in enumerate(("empty", "occupied")):
        true_positive = matrix[index][index]
        support = sum(matrix[index])
        predicted_count = sum(row[index] for row in matrix)
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        per_class[name] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    return {
        "accuracy": (matrix[0][0] + matrix[1][1]) / len(actual),
        "macro_f1": sum(item["f1"] for item in per_class.values()) / 2,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "false_occupied": matrix[0][1],
        "false_empty": matrix[1][0],
        "sample_count": len(actual),
    }


def evaluate_model(model, dataset, *, batch_size: int, device: str) -> dict:
    """Run one deterministic pass over validation or untouched test samples."""
    import torch
    from torch.utils.data import DataLoader

    from training.train import collate_batch

    if not len(dataset):
        raise ValueError("Evaluation split is empty")
    loader = DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=collate_batch
    )
    actual: list[int] = []
    predicted: list[int] = []
    errors: list[dict] = []
    forward_seconds = 0.0
    model.eval()
    with torch.inference_mode():
        for inputs, targets, metadata in loader:
            inputs = inputs.to(device)
            if device == "cuda":
                torch.cuda.synchronize()
            start = time.perf_counter()
            logits = model(inputs)
            if device == "cuda":
                torch.cuda.synchronize()
            forward_seconds += time.perf_counter() - start
            probabilities = logits.softmax(dim=1)
            predictions = probabilities.argmax(dim=1).cpu().tolist()
            truths = targets.tolist()
            actual.extend(truths)
            predicted.extend(predictions)
            for truth, prediction, confidence, row in zip(
                truths,
                predictions,
                probabilities.max(dim=1).values.cpu().tolist(),
                metadata,
            ):
                if truth != prediction:
                    errors.append(
                        {
                            "source_image": row["source_image"],
                            "spot_id": row["spot_id"],
                            "capture_day": row["capture_day"],
                            "true_label": "occupied" if truth else "empty",
                            "predicted_label": "occupied" if prediction else "empty",
                            "prediction_confidence": confidence,
                        }
                    )
    report = classification_metrics(actual, predicted)
    report["inference_latency_ms_per_image"] = 1000 * forward_seconds / len(actual)
    report["latency_measurement"] = "forward pass only; batch and hardware dependent"
    report["false_occupied_examples"] = [
        row for row in errors if row["true_label"] == "empty"
    ][:20]
    report["false_empty_examples"] = [
        row for row in errors if row["true_label"] == "occupied"
    ][:20]
    return report


def evaluate_checkpoint(
    checkpoint: Path,
    manifest_dir: Path,
    dataset_root: Path,
    output: Path,
    *,
    device: str = "auto",
    batch_size: int = 32,
) -> dict:
    """Load best checkpoint independently and evaluate test once."""

    from data.dataset import PKLotDataset
    from models.mobilenet_classifier import load_checkpoint
    from training.train import resolve_device, validate_split_manifests

    resolved_device = resolve_device(device)
    model, metadata = load_checkpoint(checkpoint, resolved_device)
    manifest_report = validate_split_manifests(
        manifest_dir,
        near_duplicate_hamming=metadata["config"]["near_duplicate_hamming"],
    )
    if metadata["dataset_version"] != manifest_report["dataset_version"]:
        raise ValueError("Dataset/split version differs from checkpoint")
    preprocessing = metadata["preprocessing"]
    dataset = PKLotDataset(
        Path(manifest_dir) / "test.jsonl",
        dataset_root,
        split="test",
        size=preprocessing["image_size"],
        pretrained=preprocessing["imagenet_normalization"],
    )
    model_report = evaluate_model(
        model, dataset, batch_size=batch_size, device=resolved_device
    )
    majority = metadata["train_majority_class"]
    actual = [int(row["label"] == "occupied") for row in dataset.rows]
    baseline = classification_metrics(actual, [majority] * len(actual))
    report = {
        "scope": (
            "synthetic smoke test"
            if metadata["scope"] == "synthetic smoke test"
            else "held-out PKLot test"
        ),
        "checkpoint": str(Path(checkpoint).resolve()),
        "dataset_version": metadata["dataset_version"],
        "device": resolved_device,
        "model": model_report,
        "train_majority_baseline": baseline,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
