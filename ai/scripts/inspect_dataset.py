"""Inspect locally supplied PKLot full frames without changing source files."""

import argparse
import json
import os
import sys
import tarfile
from pathlib import Path

from data.validation import audit_archive, audit_directory

AI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = AI_ROOT / "data" / "raw" / "PKLot"
DEFAULT_OUTPUT = AI_ROOT / "data" / "audit" / "pklot"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--root", type=Path, help="Extracted PKLot directory")
    source.add_argument(
        "--archive", type=Path, help="Local .tar.gz archive (sample only)"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--max-samples",
        type=int,
        help="Maximum XML files; default: all extracted files or 3 archive files",
    )
    parser.add_argument("--overlays", type=int, default=3)
    args = parser.parse_args(argv)
    max_samples = args.max_samples
    if max_samples is None:
        max_samples = 3 if args.archive else 0
    try:
        if args.archive:
            report = audit_archive(
                args.archive, args.output_dir, max_samples, args.overlays
            )
        else:
            root = args.root or Path(os.environ.get("PKLOT_DATASET_ROOT", DEFAULT_ROOT))
            report = audit_directory(root, args.output_dir, max_samples, args.overlays)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(f"PKLot inspection failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "source": report["source"],
                "scope": report["scope"],
                "valid_pairs": report["valid_pairs"],
                "class_counts": report["class_counts"],
                "error_count": len(report["errors"]),
                "report": str((args.output_dir / "stats.json").resolve()),
            },
            indent=2,
        )
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
