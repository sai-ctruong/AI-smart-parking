"""Binary MobileNetV3-Small and independent checkpoint loading."""

import json
import os
from pathlib import Path

CLASS_MAPPING = {"empty": 0, "occupied": 1}


def build_model(*, pretrained: bool = True):
    """Replace the ImageNet head with two logits; weights download if uncached."""
    try:
        from torch import nn
        from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    except ImportError as exc:
        raise RuntimeError(
            "Install the AI train extra: pip install -e '.[train]'"
        ) from exc
    weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
    try:
        model = mobilenet_v3_small(weights=weights)
    except Exception as exc:
        if pretrained:
            raise RuntimeError(
                "ImageNet MobileNetV3-Small weights are unavailable; "
                "provide network/cache access for real training"
            ) from exc
        raise
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, 2)
    return model


def save_checkpoint(path: Path, model, metadata: dict) -> None:
    """Write only a state dict and JSON-compatible experiment metadata."""
    import torch

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    safe_metadata = json.loads(json.dumps(metadata))
    torch.save({"state_dict": model.state_dict(), "metadata": safe_metadata}, temporary)
    os.replace(temporary, path)


def load_checkpoint(path: Path, device: str = "cpu"):
    """Load without fetching pretrained weights or executing pickle objects."""
    import torch

    payload = torch.load(Path(path), map_location=device, weights_only=True)
    metadata = payload["metadata"]
    if metadata.get("class_mapping") != CLASS_MAPPING:
        raise ValueError("Checkpoint class mapping is not empty=0, occupied=1")
    model = build_model(pretrained=False)
    model.load_state_dict(payload["state_dict"], strict=True)
    model.to(device)
    model.eval()
    return model, metadata
