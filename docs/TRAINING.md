# SANKET — Training Guide

How to train the model on your collected `.npz` files and export the artifacts
that the ESP32-S3 firmware needs.

## 1. Minimum system requirements

| Resource | Minimum | Recommended |
|---|---|---|
| **OS** | macOS 11+, Ubuntu 20.04+, Windows 10+ | macOS 13+ / Ubuntu 22.04+ |
| **CPU** | any 64-bit x86_64 / ARM64 | 4+ cores |
| **RAM** | 4 GB | 8+ GB |
| **Disk free** | 2 GB (TensorFlow + venv) | 5 GB |
| **Python** | 3.10 or 3.11 | 3.11 |
| **GPU** | *NOT required* | not useful — model is too small |
| **Training time** | 2–5 minutes CPU | — |
| **Internet** | one-time (pip install) | — |

> You don't need a GPU. The model is ~5 K parameters; TensorFlow runs it fine
> on any laptop CPU. A full training run on 100–500 samples takes 2–5 minutes.

## 2. Prerequisites

- Python environment set up per [`SETUP.md`](SETUP.md).
- At least ~15 samples per class collected via `collector.py`
  (see [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md)).

Verify data:
```bash
cd python
ls data/
# → ami  idle  (and more if you added classes)
ls data/ami | wc -l
# → number of samples for the "ami" class
```

## 3. Run training

```bash
cd python
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python train.py
```

That's it. Everything is in `train.py`.

## 4. What `train.py` does — step by step

```
1. Load every .npz under data/<label>/*.npz into memory
   → X: (N, 600, 6)  float32,  Y: (N,) int
2. Stratified split: 20 % validation, 80 % train
3. Augment the training set 30×:
     • Random time shift     (±80 samples)
     • Per-channel Gaussian noise
     • Amplitude scale        (±10 %)
     • Big time-warp          (±25 %, simulates handwriting speed variation)
     • Random "pause insert"  (25 % chance, 0.1–0.8 s hold)
   → effective size: 30× original train split
4. Fit per-channel mean/std on the augmented train split
5. Build 1D-CNN  (Conv1D×3 → GlobalAvgPool → Dropout → Dense)
6. Compile: Adam, sparse CE, class-weighted (handles imbalance)
7. Train up to 80 epochs with ReduceLROnPlateau + EarlyStopping
8. Report precision / recall / F1 + confusion matrix on the val split
9. Export artifacts to models/:
     sanket.keras                 full Keras model
     sanket_float32.tflite        FP32 TFLite — host inference
     sanket_int8.tflite           INT8 TFLite — ESP32 deployment
     model_data.h                 same INT8 as a C header (for firmware_infer/)
     norm.json                    per-channel µ/σ (for GUI + firmware)
     labels.json                  id → name mapping
```

Expected output on 138 samples (49 ami + 89 idle):

```
📊 Validation report
              precision    recall  f1-score   support
        idle       1.00      1.00      1.00        18
         ami       1.00      1.00      1.00        10
    accuracy                           1.00        28

Confusion matrix:
[[18  0]
 [ 0 10]]

💾 Saved → sanket.keras / sanket_float32.tflite / sanket_int8.tflite (~17 KB)
```

## 5. Augmentation strategy — why

The dataset is small by design (you're one user collecting your own
samples). Without augmentation the model memorizes the exact training
examples and generalizes poorly. Each augmentation attacks a specific
real-world variability:

| Augmentation | Simulates |
|---|---|
| Time shift (±80) | You start writing earlier or later within the 6 s window |
| Gaussian noise | MPU6050 clone noise, electrical interference |
| Amplitude scale (±10 %) | Writing bigger or smaller gestures |
| Time warp (±25 %) | Writing faster or slower |
| Pause insert | Thinking mid-stroke, hesitating |

Together they turn 100 real samples into ~3000 synthetic variations.

## 6. Updating the firmware with your new model

After `train.py` finishes, copy the generated C array into the inference
firmware:

```bash
cp python/models/model_data.h   firmware_infer/src/model_data.h
```

Also copy the normalization constants into a C header (if your µ/σ changed):

```bash
# Open python/models/norm.json, copy the arrays into
# firmware_infer/src/model_norm.h (the MODEL_MU / MODEL_SD arrays).
```

> If `labels.json` changed (you added a class), update
> `firmware_infer/src/model_norm.h` → `MODEL_CLASSES` and `MODEL_CLASS_NAMES`
> to match the new label order (same order as `labels.json`).

Then flash:
```bash
cd firmware_infer
pio run -t upload
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full deployment flow.

## 7. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `❌ No data found` | `data/` is empty | Collect samples first ([`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md)) |
| Val accuracy < 80 % | Not enough samples OR inconsistent gestures | Collect more; focus on consistency inside each style |
| Val accuracy 100 % but on-device feels weak | Overfitting | Collect more varied samples (more P × S cells, more users) |
| TFLite int8 conversion warning about statistics | Representative dataset too small | More samples helps; usually harmless |
| `train.py` crashes `OutOfMemory` on huge datasets | 32-bit augmentation copies | Reduce `AUG_PER_SAMPLE` in `train.py` (default 30 → try 15) |
