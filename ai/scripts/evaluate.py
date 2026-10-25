"""Evaluate a saved best checkpoint on the untouched test manifest."""

import argparse
import json
import os
import sys
from pathlib import Path

from training.evaluate import evaluate_checkpoint

AI_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--manifest-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args(argv)
    root = (
        args.dataset_root
        or os.environ.get("PKLOT_DATASET_ROOT")
        or AI_ROOT / "data" / "raw" / "PKLot"
    )
    manifests = args.manifest_dir or AI_ROOT / "data" / "processed" / "pklot"
    output = args.output or args.checkpoint.parent / "test_evaluation.json"
    try:
        report = evaluate_checkpoint(
            args.checkpoint,
            Path(manifests),
            Path(root),
            output,
            device=args.device,
            batch_size=args.batch_size,
        )
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
