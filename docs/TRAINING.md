# SANKET — Training Guide

How to train the model on the collected `.npz` files and export everything the
ESP32-S3 firmware needs.

## 1. System requirements

| Resource | Minimum | Recommended |
|---|---|---|
| **OS** | macOS 11+, Ubuntu 20.04+, Windows 10+ | macOS 13+ / Ubuntu 22.04+ |
| **CPU** | any 64-bit x86_64 / ARM64 | 4+ cores |
| **RAM** | 4 GB | 8+ GB |
| **Disk free** | 2 GB (TensorFlow + venv) | 5 GB |
| **Python** | 3.10 or 3.11 | 3.11 |
| **GPU** | not required | not useful at this model size |
| **Training time** | ~10–15 min on a laptop CPU (778 samples, 80 epochs) | — |

## 2. Prerequisites

- Python environment set up per [`SETUP.md`](SETUP.md).
- Samples collected per [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md).

```bash
cd python
ls data/
# → ami  dhonnobad  haan  idle  khabar  pani  salam  shahajjo  (+ _archive_… ignored)
```

## 3. Run training

```bash
cd python
.venv/bin/python train.py
```

Training a bigger model can take longer than a terminal tool's 10-minute
limit. Run it in its own terminal window and let it finish.

## 4. The classes

The order sets the integer class id. It must match `labels.json`, the firmware
and the SD-card file numbers:

| id | name | Bangla | Voice file |
|---:|---|---|---|
| 0 | idle | (rest / random) | — (silent) |
| 1 | ami | আমি | `0001.mp3` |
| 2 | haan | হ্যাঁ | `0002.mp3` |
| 3 | dhonnobad | ধন্যবাদ | `0003.mp3` |
| 4 | pani | পানি | `0004.mp3` |
| 5 | khabar | খাবার | `0005.mp3` |
| 6 | shahajjo | সাহায্য | `0006.mp3` |
| 7 | salam | সালাম (আস-সালামু আলাইকুম) | `0007.mp3` |

## 5. What `train.py` does — step by step

```
1. Load every data/<label>/pos*_style*_rep*.npz          → raw (600, 6) samples
2. WINDOW = longest sample rounded up to 50 = 600
   Shorter samples are zero-padded at the end, longer ones truncated.
   (With the fixed 6 s dataset every sample is already 600 — no padding.)
   Raw samples only: no mixing, no random re-positioning of gestures.
3. Stratified split: 15 % validation per class (seed 1337)
4. Augment the training split ×24 extra copies:
     • time shift        ±60 samples (zero-filled edge)
     • Gaussian noise    accel σ 0.005–0.03 g, gyro σ 0.5–2.5 °/s
     • amplitude scale   ±10 % (accel and gyro separately)
     • time warp         0.80–1.20 × (re-sampled, then cropped/padded to 600)
5. Fit per-channel mean / std on the augmented train split → normalise
6. Class weights to balance class sizes
7. Build the 1D-CNN (below), Adam lr 1e-3, batch 64, up to 80 epochs
   ReduceLROnPlateau (×0.5, patience 5) + EarlyStopping (patience 15, best weights)
8. Validation report: precision / recall / F1 + confusion matrix
9. Export to models/
```

## 6. Model architecture

```
input (600, 6)
 → Conv1D 32,  k7, stride 2 → BatchNorm → ReLU
 → Conv1D 64,  k5, stride 2 → BatchNorm → ReLU
 → Conv1D 96,  k3, stride 2 → BatchNorm → ReLU
 → Conv1D 128, k3, stride 2 → BatchNorm → ReLU
 → Conv1D 160, k3, stride 1 → BatchNorm → ReLU
 → GlobalAveragePooling1D
 → Dropout 0.4
 → Dense 8, softmax
```

| Setting | Value |
|---|---|
| Loss | categorical cross-entropy with **label smoothing 0.05** |
| Optimiser | Adam, lr 1e-3 |
| Epochs / batch | 80 / 64 |
| Validation | 15 % stratified, seed 1337 |
| Augmentation | ×24 per training sample |

**Label smoothing** trains on soft targets (0.95 instead of 1.0). The model's
confidence then means something, which matters because the device only speaks
a word at ≥ 75 % confidence.

## 7. Outputs (`python/models/`)

| File | Size | Used by |
|---|---:|---|
| `sanket.keras` | ~1.6 MB | full Keras model (re-training, inspection) |
| `sanket_float32.tflite` | ~517 KB | host inference (`infer_gui.py`) |
| `sanket_int8.tflite` | ~149 KB | fully-quantised INT8 model for the ESP32-S3 |
| `model_data.h` | ~930 KB text | the INT8 model as a C array (`sanket_model[]`) |
| `norm.json` | tiny | per-channel `mu`, `sd`, `window`, `channels` |
| `labels.json` | tiny | id → name + Bangla |

## 8. Current result

778 samples, 117 held out for validation:

```
              precision    recall  f1-score   support
        idle       1.00      1.00      1.00        19
         ami       1.00      1.00      1.00        14
        haan       1.00      1.00      1.00        12
   dhonnobad       1.00      1.00      1.00        11
        pani       1.00      1.00      1.00        17
      khabar       1.00      1.00      1.00        16
    shahajjo       1.00      1.00      1.00        13
       salam       1.00      1.00      1.00        15
    accuracy                           1.00       117
```

The confusion matrix is a pure diagonal. On the device, real air-written words
are detected at roughly 72–92 % confidence (see
[`DEPLOYMENT.md`](DEPLOYMENT.md)).

> Validation is 100 % because it comes from the same person, the same sensor
> and the same sessions. Accuracy on live use depends mainly on writing
> consistently and on calibrating in the same pose as during collection.

## 9. Why this model — design history

| Stage | Model | INT8 size | Notes |
|---|---|---:|---|
| Smoke test (ami vs idle) | Conv1D 24/48/72/96, 4 stages | ~17 KB → 52 KB | 100 % on 2 classes |
| 9–10 classes, ~490 samples | small 4-stage model | ~52 KB | 99–100 % val, but some words wobbled live |
| Big model, ~490 samples | 5-stage 32…160 + label smoothing | ~149 KB | no clear gain — too little data for its size |
| **Big model, 778 samples (current)** | 5-stage 32…160 + label smoothing | **~149 KB** | **chosen**: enough data to use the extra capacity; sharper decisions on similar words |

The small model is still a valid option. To switch back, use 4 Conv1D stages
(24/48/72/96), dropout 0.3, plain cross-entropy and 60 epochs in `build_model()`.

## 10. Deploy a newly trained model to the device

After `train.py` finishes, do two things.

**1. Copy the C array into the firmware:**

```bash
cp python/models/model_data.h firmware_infer/src/model_data.h
```

**2. Regenerate `firmware_infer/src/model_norm.h`** (window, mu/sd and class
order) from `norm.json` and `labels.json`:

```bash
python/.venv/bin/python - << 'EOF'
import json
norm   = json.load(open('python/models/norm.json'))
labels = sorted(json.load(open('python/models/labels.json')), key=lambda L: L['id'])
f = lambda vals: ',\n'.join('    %.10ff' % v for v in vals)
names = ',\n'.join('    "%s"' % L['name'] for L in labels)
open('firmware_infer/src/model_norm.h', 'w').write(f'''// SANKET — model normalization + labels (from norm.json / labels.json).
#pragma once

constexpr int   MODEL_WINDOW   = {norm['window']};
constexpr int   MODEL_CHANNELS = {norm['channels']};
constexpr int   MODEL_CLASSES  = {len(labels)};

// Order: ax, ay, az (g), gx, gy, gz (deg/s)
constexpr float MODEL_MU[6] = {{
{f(norm['mu'])}
}};
constexpr float MODEL_SD[6] = {{
{f(norm['sd'])}
}};

// Class names (index == softmax output id)
constexpr const char* MODEL_CLASS_NAMES[MODEL_CLASSES] = {{
{names}
}};
''')
print('model_norm.h updated for', len(labels), 'classes')
EOF
```

If you added or removed a class, also update `CLASS_BANGLA[]` in
`firmware_infer/src/main.cpp` (same order) and the voice files on the SD card.
See [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md).

Then build and flash:

```bash
cd firmware_infer
pio run -t upload
```

## 11. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `❌ No data found` | `data/` is empty | Collect samples first |
| Val accuracy < 90 % | inconsistent gestures or too few samples | Collect more; keep each style consistent |
| Two words confused | their motions share strokes (e.g. tumi ↔ ami) | Redesign one gesture or drop it |
| 100 % val, weak live detection | different calibration pose, or live writing differs from training | Calibrate flat & face-up; collect more varied samples |
| INT8 conversion warning about statistics | harmless | — |
| Out of memory | too many augmented copies | Lower `AUG_PER_SAMPLE` (24 → 12) |
