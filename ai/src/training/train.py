"""Deterministic train/validation loop; test labels never select checkpoints."""

import hashlib
import json
import os
import random
from pathlib import Path

from data.dataset import PKLotDataset
from data.preprocessing import IMAGENET_MEAN, IMAGENET_STD
from models.mobilenet_classifier import CLASS_MAPPING, build_model, save_checkpoint
from training.evaluate import classification_metrics


def validate_split_manifests(
    manifest_dir: Path, *, near_duplicate_hamming: int = 4
) -> dict:
    """Reject malformed rows, overlapping days and similar cross-split frames."""
    directory = Path(manifest_dir)
    rows_by_split: dict[str, list[dict]] = {}
    hashes: dict[str, str] = {}
    version = hashlib.sha256()
    for split in ("train", "val", "test"):
        path = directory / f"{split}.jsonl"
        raw = path.read_bytes()
        hashes[split] = hashlib.sha256(raw).hexdigest()
        version.update(split.encode() + b"\0" + raw)
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        if not rows:
            raise ValueError(f"{split} manifest is empty")
        for row in rows:
            if row.get("split") != split:
                raise ValueError(f"Manifest row has wrong split in {path}")
            if row.get("label") not in CLASS_MAPPING:
                raise ValueError(f"Invalid ground-truth label in {path}")
            if not row.get("capture_day") or not row.get("source_image"):
                raise ValueError(f"Missing capture day or source image in {path}")
            try:
                fingerprint = int(row["frame_fingerprint"], 16)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid frame fingerprint in {path}") from exc
            if not 0 <= fingerprint < 2**64:
                raise ValueError(f"Invalid frame fingerprint in {path}")
        rows_by_split[split] = rows
    if len({row["camera_id"] for rows in rows_by_split.values() for row in rows}) != 1:
        raise ValueError("Manifests must contain exactly one camera")
    days = {
        split: {row["capture_day"] for row in rows}
        for split, rows in rows_by_split.items()
    }
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        if days[left] & days[right]:
            raise ValueError(f"Overlapping capture day between {left} and {right}")
    frames = {
        split: {row["source_image"] for row in rows}
        for split, rows in rows_by_split.items()
    }
    for left, right in (("train", "val"), ("train", "test"), ("val", "test")):
        if frames[left] & frames[right]:
            raise ValueError(f"Source image overlaps {left} and {right}")
        left_hashes = {int(row["frame_fingerprint"], 16) for row in rows_by_split[left]}
        right_hashes = {
            int(row["frame_fingerprint"], 16) for row in rows_by_split[right]
        }
        if any(
            (first ^ second).bit_count() <= near_duplicate_hamming
            for first in left_hashes
            for second in right_hashes
        ):
            raise ValueError(f"Cross-split near-duplicate frame in {left} and {right}")
    return {
        "dataset_version": version.hexdigest(),
        "manifest_sha256": hashes,
        "split_sizes": {split: len(rows) for split, rows in rows_by_split.items()},
        "train_class_counts": {
            label: sum(row["label"] == label for row in rows_by_split["train"])
            for label in CLASS_MAPPING
        },
    }


def resolve_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be auto, cpu, or cuda")
    return requested


def set_seed(seed: int) -> None:
    """Set RNGs and deterministic kernels when the installed backend supports them."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:2")
    random.seed(seed)
    import torch

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass


def collate_batch(batch):
    """Top-level function remains pickleable for Windows DataLoader workers."""
    import torch

    inputs, targets, metadata = zip(*batch)
    return (
        torch.stack([item.to_tensor() for item in inputs]),
        torch.tensor(targets, dtype=torch.long),
        list(metadata),
    )


def _run_epoch(
    model, loader, criterion, device: str, optimizer=None, scaler=None
) -> dict:
    import torch

    training = optimizer is not None
    model.train(training)
    actual: list[int] = []
    predicted: list[int] = []
    total_loss = 0.0
    total_samples = 0
    for inputs, targets, _ in loader:
        inputs, targets = inputs.to(device), targets.to(device)
        if training:
            optimizer.zero_grad(set_to_none=True)
        with torch.set_grad_enabled(training):
            with torch.autocast(device_type="cuda", enabled=scaler is not None):
                logits = model(inputs)
                loss = criterion(logits, targets)
            if training:
                if scaler is not None:
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    loss.backward()
                    optimizer.step()
        count = len(targets)
        total_loss += loss.detach().item() * count
        total_samples += count
        actual.extend(targets.cpu().tolist())
        predicted.extend(logits.detach().argmax(dim=1).cpu().tolist())
    result = classification_metrics(actual, predicted)
    result["loss"] = total_loss / total_samples
    return result


def train_experiment(
    config: dict,
    dataset_root: Path,
    manifest_dir: Path,
    output_dir: Path,
    *,
    scope: str = "real-data training",
) -> dict:
    """Fit on train, select on validation macro F1, save one best checkpoint."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:2")
    import torch
    import torchvision
    from torch.utils.data import DataLoader

    if config["epochs"] < 1 or config["batch_size"] < 1 or config["patience"] < 1:
        raise ValueError("epochs, batch_size and patience must be positive")
    if (
        config["num_workers"] < 0
        or config["image_size"] < 1
        or config["scheduler_patience"] < 0
    ):
        raise ValueError("num_workers, image_size or scheduler_patience is invalid")
    if config["learning_rate"] <= 0 or config["weight_decay"] < 0:
        raise ValueError("Learning rate or weight decay is invalid")
    if not 0 < config["scheduler_factor"] < 1:
        raise ValueError("scheduler_factor must be below 1")
    manifest_report = validate_split_manifests(
        manifest_dir, near_duplicate_hamming=config["near_duplicate_hamming"]
    )
    set_seed(config["seed"])
    device = resolve_device(config["device"])
    train_set = PKLotDataset(
        Path(manifest_dir) / "train.jsonl",
        dataset_root,
        split="train",
        size=config["image_size"],
        pretrained=config["pretrained"],
        seed=config["seed"],
    )
    val_set = PKLotDataset(
        Path(manifest_dir) / "val.jsonl",
        dataset_root,
        split="val",
        size=config["image_size"],
        pretrained=config["pretrained"],
        seed=config["seed"],
    )
    generator = torch.Generator().manual_seed(config["seed"])
    train_loader = DataLoader(
        train_set,
        batch_size=config["batch_size"],
        shuffle=True,
        generator=generator,
        num_workers=config["num_workers"],
        collate_fn=collate_batch,
    )
    val_loader = DataLoader(
        val_set,
        batch_size=config["batch_size"],
        shuffle=False,
        num_workers=config["num_workers"],
        collate_fn=collate_batch,
    )
    model = build_model(pretrained=config["pretrained"]).to(device)
    criterion = torch.nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["learning_rate"],
        weight_decay=config["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="max",
        factor=config["scheduler_factor"],
        patience=config["scheduler_patience"],
    )
    scaler = (
        torch.amp.GradScaler("cuda")
        if device == "cuda" and config["mixed_precision"]
        else None
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = manifest_report["train_class_counts"]
    majority = 0 if counts["empty"] >= counts["occupied"] else 1
    metadata = {
        "scope": scope,
        "model_architecture": "torchvision.mobilenet_v3_small",
        "initial_weights": "IMAGENET1K_V1" if config["pretrained"] else "random",
        "class_mapping": CLASS_MAPPING,
        "preprocessing": {
            "image_size": config["image_size"],
            "imagenet_normalization": config["pretrained"],
            "mean": IMAGENET_MEAN if config["pretrained"] else (0.0, 0.0, 0.0),
            "std": IMAGENET_STD if config["pretrained"] else (1.0, 1.0, 1.0),
            "polygon_crop": "masked_tight_square_pad",
        },
        "dataset_version": manifest_report["dataset_version"],
        "manifest_sha256": manifest_report["manifest_sha256"],
        "train_majority_class": majority,
        "config": config,
        "paths": {
            "dataset_root": str(Path(dataset_root).resolve()),
            "manifest_dir": str(Path(manifest_dir).resolve()),
            "output_dir": str(output_dir.resolve()),
        },
        "seed": config["seed"],
        "torch_version": torch.__version__,
        "torchvision_version": torchvision.__version__,
    }
    (output_dir / "experiment.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    best = float("-inf")
    stale_epochs = 0
    best_epoch = 0
    history_path = output_dir / "epochs.jsonl"
    with history_path.open("w", encoding="utf-8") as history:
        for epoch in range(1, config["epochs"] + 1):
            train_set.set_epoch(epoch)
            train_result = _run_epoch(
                model, train_loader, criterion, device, optimizer, scaler
            )
            val_result = _run_epoch(model, val_loader, criterion, device)
            metric = val_result["macro_f1"]
            scheduler.step(metric)
            record = {
                "epoch": epoch,
                "learning_rate": optimizer.param_groups[0]["lr"],
                "train": train_result,
                "validation": val_result,
            }
            history.write(json.dumps(record, sort_keys=True) + "\n")
            history.flush()
            if metric > best + 1e-12:
                best = metric
                best_epoch = epoch
                stale_epochs = 0
                save_checkpoint(
                    output_dir / "best.pt",
                    model,
                    {**metadata, "best_epoch": best_epoch, "best_val_macro_f1": best},
                )
            else:
                stale_epochs += 1
                if stale_epochs >= config["patience"]:
                    break
    result = {
        "scope": scope,
        "best_epoch": best_epoch,
        "best_validation_macro_f1": best,
        "epochs_completed": epoch,
        "checkpoint": str((output_dir / "best.pt").resolve()),
        "dataset_version": manifest_report["dataset_version"],
        "device": device,
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
