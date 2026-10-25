# PKLot occupancy classifier training

This pipeline consumes the validated, leakage-safe manifests from [dataset preparation](DATASET.md#roi-preparation-and-leakage-safe-manifests-task-05). It predicts **empty (0)** or **occupied (1)** for one annotated parking spot. XML labels remain ground truth; evaluation records keep true and predicted labels in separate fields. No model result in this document is a measured PKLot result.

## Setup and real-data commands

Use Python 3.11 or newer and an environment with compatible PyTorch/torchvision builds. To use an NVIDIA GPU, install the matching CUDA build using the [official PyTorch installer selector](https://pytorch.org/get-started/locally/) and confirm `torch.cuda.is_available()` is true; a CPU build will correctly fall back to CPU with `--device auto`. On Windows PowerShell, from `ai/`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[audit,train,dev]'
$env:PKLOT_DATASET_ROOT = (Resolve-Path .\data\raw\PKLot).Path
.\.venv\Scripts\python.exe .\scripts\prepare_dataset.py --camera UFPR04 --seed 42
.\.venv\Scripts\python.exe .\scripts\train.py --config .\configs\train.yaml --device auto
.\.venv\Scripts\python.exe .\scripts\evaluate.py --checkpoint .\runs\pklot\best.pt --device auto
```

Run the full dataset audit before preparation. The default extracted root is `ai/data/raw/PKLot/`, manifests are `ai/data/processed/pklot/`, and outputs are `ai/runs/pklot/`. All are ignored by Git. Override paths with `--dataset-root`, `--manifest-dir`, and `--output-dir` on the training command; evaluation accepts `--dataset-root`, `--manifest-dir`, and `--output`. Prepare one camera at a time. If the offline ImageNet weight cache is empty, the first **real** training run requires network access to fetch MobileNetV3-Small `IMAGENET1K_V1` weights. It fails explicitly if weights are unavailable; it does not silently switch to random initialization.

For Kaggle, install the same `.[audit,train]` extra, point `--dataset-root` to the **actual** mounted extracted PKLot directory, and write manifests/runs under `/kaggle/working/`. Use `--device cuda` only when a CUDA runtime is available. Do not hardcode a Kaggle input path in tracked configuration. Windows DataLoader workers default to zero; the script has a `__main__` guard if you increase `num_workers`.

## Configuration and outputs

`ai/configs/train.yaml` uses JSON syntax, which is valid YAML 1.2 and readable with the standard library. It controls seed, epochs, batch size, workers, learning rate, weight decay, scheduler, early stopping, image size, pretrained weights, mixed precision, and device (`auto`, `cpu`, `cuda`). The default is a pretrained MobileNetV3-Small with a two-logit head, `CrossEntropyLoss`, `AdamW`, and `ReduceLROnPlateau`. The scheduler and best checkpoint use **validation macro F1**; early stopping also observes validation macro F1. CUDA uses automatic mixed precision when enabled; CPU runs full precision. Random seeds and deterministic PyTorch kernels are configured for repeatability on the same supported software and hardware. Exact numerical identity across different devices or library versions is not promised.

Before training, the script rejects empty/invalid manifests, mixed cameras, shared capture days or source frames, and near-duplicate frame hashes across splits. It reads test manifest metadata for this leakage check and version hash, but **does not run test inference or use test metrics for selection**. Train-only augmentations and validation-only metric selection follow TASK-05 rules. The held-out test set is evaluated only by `scripts/evaluate.py` after a checkpoint exists.

| Output | Meaning |
| --- | --- |
| `experiment.json` | Saved config, seed, resolved paths, split hashes/version, class mapping, preprocessing, initial weights and software versions. |
| `epochs.jsonl` | One structured record per epoch with train/validation loss, metrics and learning rate. |
| `best.pt` | Best validation checkpoint: model state dict and safe metadata. Independent loading does not download ImageNet weights. |
| `training_summary.json` | Best epoch, validation macro F1, completed epochs, device and version. |
| `test_evaluation.json` | Held-out test accuracy, class precision/recall/F1, macro F1, true-row/predicted-column confusion matrix, forward-pass latency per image, false occupied/false empty counts and up to 20 example references for each. Also includes the majority-class baseline derived **only from train labels**. |

The dataset version is a SHA-256 of the three manifest files. Keep the original image/XML files immutable after preparation; the manifest hash alone cannot detect a later change to raw image bytes. Evaluation checks that the saved split version still matches before reading test images. The latency is hardware and batch dependent, measured around model forward passes (with CUDA synchronization), and is not end-to-end image-upload latency.

## Synthetic smoke test

When extracted PKLot files or an ImageNet weight cache are unavailable, run:

```powershell
cd ai
.\.venv\Scripts\python.exe .\scripts\train.py --smoke --device cpu
.\.venv\Scripts\python.exe .\scripts\evaluate.py --checkpoint .\runs\task06-smoke\best.pt --dataset-root .\data\smoke\task06\raw --manifest-dir .\data\smoke\task06\manifests --output .\runs\task06-smoke\independent_evaluation.json --device cpu --batch-size 2
```

The first command creates tiny, clearly synthetic images and annotations under ignored `ai/data/smoke/task06/`, prepares three day-grouped manifests, initializes **random weights** without downloading ImageNet weights, trains one epoch, then evaluates its held-out synthetic test split. Reports under `ai/runs/task06-smoke/` are engineering smoke artifacts, not PKLot performance or a usable parking model. Do not compare their numbers to a real benchmark.
