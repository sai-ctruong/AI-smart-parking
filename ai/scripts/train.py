"""Train MobileNetV3-Small on prepared PKLot splits or a synthetic smoke fixture."""

import argparse
import json
import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from data.dataset import prepare_dataset
from training.evaluate import evaluate_checkpoint
from training.train import train_experiment

AI_ROOT = Path(__file__).resolve().parents[1]


def _make_synthetic_fixture(root: Path) -> None:
    """Create tiny, explicitly synthetic data under an ignored output directory."""
    for number, day in enumerate(("2012-01-01", "2012-02-01", "2012-03-01"), 1):
        folder = root / "UFPR04" / day
        folder.mkdir(parents=True, exist_ok=True)
        for frame in range(2):
            rng = random.Random(number * 100 + frame)
            image = Image.new("RGB", (64, 64))
            image.putdata(
                [
                    (value, value, value)
                    for value in (rng.randrange(256) for _ in range(64 * 64))
                ]
            )
            draw = ImageDraw.Draw(image)
            draw.rectangle((6, 6, 28, 28), fill=(35, 115, 45))
            draw.rectangle((36, 36, 58, 58), fill=(180, 45, 35))
            name = f"synthetic_{frame}"
            image.save(folder / f"{name}.png")
            (folder / f"{name}.xml").write_text(
                '<parking id="UFPR04">'
                '<space id="1" occupied="0"><contour>'
                '<point x="6" y="6"/><point x="28" y="6"/>'
                '<point x="28" y="28"/><point x="6" y="28"/>'
                "</contour></space>"
                '<space id="2" occupied="1"><contour>'
                '<point x="36" y="36"/><point x="58" y="36"/>'
                '<point x="58" y="58"/><point x="36" y="58"/>'
                "</contour></space></parking>",
                encoding="utf-8",
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=AI_ROOT / "configs" / "train.yaml"
    )
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--manifest-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"))
    parser.add_argument(
        "--smoke", action="store_true", help="Synthetic, no pretrained download"
    )
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if args.smoke:
            root = AI_ROOT / "data" / "smoke" / "task06" / "raw"
            manifests = AI_ROOT / "data" / "smoke" / "task06" / "manifests"
            output = args.output_dir or AI_ROOT / "runs" / "task06-smoke"
            _make_synthetic_fixture(root)
            prepare_dataset(
                root,
                manifests,
                "UFPR04",
                seed=config["seed"],
                near_duplicate_hamming=0,
                size=64,
                visual_samples_per_split=1,
            )
            config.update(
                {
                    "epochs": 1,
                    "batch_size": 2,
                    "num_workers": 0,
                    "image_size": 64,
                    "pretrained": False,
                    "mixed_precision": False,
                    "near_duplicate_hamming": 0,
                    "device": args.device or "cpu",
                }
            )
            scope = "synthetic smoke test"
        else:
            root = (
                args.dataset_root
                or os.environ.get("PKLOT_DATASET_ROOT")
                or config["dataset_root"]
                or AI_ROOT / "data" / "raw" / "PKLot"
            )
            manifests = (
                args.manifest_dir
                or config["manifest_dir"]
                or AI_ROOT / "data" / "processed" / "pklot"
            )
            output = (
                args.output_dir or config["output_dir"] or AI_ROOT / "runs" / "pklot"
            )
            config["device"] = args.device or config["device"]
            scope = "real-data training"
        result = train_experiment(
            config, Path(root), Path(manifests), Path(output), scope=scope
        )
        if args.smoke:
            evaluation = evaluate_checkpoint(
                Path(output) / "best.pt",
                Path(manifests),
                Path(root),
                Path(output) / "smoke_evaluation.json",
                device=config["device"],
                batch_size=config["batch_size"],
            )
            result["synthetic_test_report"] = str(
                Path(output) / "smoke_evaluation.json"
            )
            result["synthetic_test_accuracy"] = evaluation["model"]["accuracy"]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
