# `python/` — SANKET ML Pipeline + GUIs

Everything that runs on the laptop: data collection, model training,
host-side verification. The product itself (the ESP32-S3) doesn't need
any of this at runtime.

## Files

| File | What it is |
|---|---|
| `requirements.txt` | pinned Python dependencies |
| `collector.py` | PySide6 GUI — fires one-shot 6 s recordings on SPACEBAR, saves `.npz` |
| `train.py` | 1D-CNN training + FP32/INT8 TFLite export + C header generation |
| `infer_gui.py` | Host-side live inference GUI (debugging / verification tool only) |
| `models/` | Trained artifacts (kept in git, small files) |
| `data/` | Collected recordings — **gitignored** (user-personal, large) |

## Trained artifacts (`models/`)

| File | What it is | Size |
|---|---|---|
| `sanket.keras` | Full Keras model (for continued training) | ~70 KB |
| `sanket_float32.tflite` | FP32 TFLite — used by `infer_gui.py` on the laptop | ~37 KB |
| `sanket_int8.tflite` | INT8 TFLite — deployed to ESP32-S3 | ~17 KB |
| `model_data.h` | Same INT8 model as a C array — copied into `firmware_infer/src/` | ~85 KB (source) |
| `norm.json` | Per-channel mean/std used during training | ~500 B |
| `labels.json` | `id → name` class mapping | ~200 B |

## Setup

See [`../docs/SETUP.md`](../docs/SETUP.md). TL;DR:

```bash
cd python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Workflow

```
┌────────────┐          ┌───────────┐          ┌──────────────┐
│ collector  │ ──.npz──▶│ train.py  │ ──.tflite▶│ firmware_infer│
│ (PySide6)  │          │ (TF 2.15) │ ──.h─────▶│ (ESP32-S3)   │
└────────────┘          └───────────┘          └──────────────┘
       ▲                                              │
       │              laptop verifies                 │  serial
       │              with infer_gui.py ◀─────────────┘
       │              (reads L lines)
       └── data lives here forever, in your repo
```

### 1. Collect

```bash
python collector.py
```
See [`../docs/DATA_COLLECTION_GUIDE.md`](../docs/DATA_COLLECTION_GUIDE.md).

### 2. Train

```bash
python train.py
```
See [`../docs/TRAINING.md`](../docs/TRAINING.md).

### 3. Verify on host (optional)

```bash
python infer_gui.py
```

Launches a window with:
- Live scrolling IMU plots
- Live class-probability bars
- Big banner that goes green on sustained ami detection

This GUI runs the FP32 model **on the laptop** — the ESP32-S3 is just
a sensor streamer here. Useful to A/B-compare host behavior against
on-device behavior.

### 4. Deploy

```bash
cp models/model_data.h ../firmware_infer/src/model_data.h
cd ../firmware_infer
pio run -t upload
pio device monitor --baud 921600
```
See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

## Configuration constants that must agree across the project

| Constant | File | Current | Must match … |
|---|---|---|---|
| Window length (samples) | `collector.py` → `FIXED_RECORD_SMPL` | 600 | train.py, infer_gui.py, firmware, firmware_infer |
| Window length (samples) | `train.py` → `WINDOW` | 600 | same |
| Window length (samples) | `infer_gui.py` → `WINDOW` | 600 | same |
| Window length (samples) | `firmware_infer/src/model_norm.h` → `MODEL_WINDOW` | 600 | same |
| Window length (samples) | `firmware/src/main.cpp` → `FIXED_RECORD_SAMPLES` | 600 | same |
| Sample rate (Hz) | all of the above | 100 | same |
| Channels | all of the above | 6 | same |
