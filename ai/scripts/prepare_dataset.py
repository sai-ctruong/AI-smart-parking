"""Prepare leakage-safe PKLot manifests; never trains or copies source frames."""

import argparse
import json
import os
import sys
from pathlib import Path

from data.dataset import prepare_dataset

AI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = AI_ROOT / "configs" / "dataset.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, help="Extracted PKLot root")
    parser.add_argument("--output-dir", type=Path, help="Generated manifest directory")
    parser.add_argument("--camera", help="One camera ID, e.g. UFPR04")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        root_value = (
            args.root or os.environ.get("PKLOT_DATASET_ROOT") or config["dataset_root"]
        )
        if root_value is None:
            root_value = AI_ROOT / "data" / "raw" / "PKLot"
        output_value = (
            args.output_dir
            or config["output_root"]
            or AI_ROOT / "data" / "processed" / "pklot"
        )
        summary = prepare_dataset(
            Path(root_value),
            Path(output_value),
            args.camera or config["camera_id"],
            seed=args.seed if args.seed is not None else config["seed"],
            near_duplicate_hamming=config["near_duplicate_hamming"],
            train_fraction=config["train_fraction"],
            val_fraction=config["val_fraction"],
            test_fraction=config["test_fraction"],
            size=config["image_size"],
            pretrained=config["pretrained"],
            visual_samples_per_split=config["visual_samples_per_split"],
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"PKLot preparation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
