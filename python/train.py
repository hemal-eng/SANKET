"""
SANKET — Train a tiny 1D-CNN on collected gesture .npz files.

A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written
Gesture Recognition.

Reads every `data/<label>/pos*_rep*.npz` under this directory, trains a
small Keras CNN, exports:
  - models/sanket.keras          (full Keras model)
  - models/sanket_float32.tflite (host inference)
  - models/sanket_int8.tflite    (ESP32-S3 deployment)
  - models/model_data.h          (same int8 model, as a C array)
  - models/norm.json             (per-channel mean/std used in training)
  - models/labels.json           (id → name mapping)

Datasets are small, so training leans HARD on augmentation.

Run:
    source .venv/bin/activate
    python train.py
"""
from __future__ import annotations
import json
import glob
import os
import sys
from pathlib import Path

import numpy as np

# Keep TF logs quiet
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import tensorflow as tf
from tensorflow.keras import layers, models, callbacks  # type: ignore
from sklearn.metrics import classification_report, confusion_matrix  # type: ignore


# ---------- Config ----------
HERE          = Path(__file__).resolve().parent
DATA_DIR      = HERE / "data"
OUT_DIR       = HERE / "models"
OUT_DIR.mkdir(exist_ok=True)

WINDOW        = 600          # samples (6 s @ 100 Hz) — must match firmware
CHANNELS      = 6            # ax,ay,az,gx,gy,gz
LABELS        = [            # order sets integer class ids
    {"id": 0, "name": "idle", "bangla": "(idle)"},
    {"id": 1, "name": "ami",  "bangla": "আমি"},
]
NAME_TO_ID    = {L["name"]: L["id"] for L in LABELS}

AUG_PER_SAMPLE = 30          # synthetic copies per real training sample
VAL_FRAC       = 0.20
EPOCHS         = 80
BATCH          = 32
SEED           = 1337


# ---------- Data loading ----------
def load_dataset() -> tuple[np.ndarray, np.ndarray, list[str]]:
    xs, ys, srcs = [], [], []
    for L in LABELS:
        # Match BOTH legacy (pos*_rep*.npz) and new (pos*_style*_rep*.npz) files
        files = sorted(set(
            glob.glob(str(DATA_DIR / L["name"] / "pos*_rep*.npz")) +
            glob.glob(str(DATA_DIR / L["name"] / "pos*_style*_rep*.npz"))
        ))
        if not files:
            print(f"⚠️  no files for class '{L['name']}' under {DATA_DIR / L['name']}")
            continue
        for fp in files:
            z = np.load(fp)
            x = z["data"].astype(np.float32)   # (N, 6)
            if x.shape[0] < WINDOW:
                x = np.pad(x, ((0, WINDOW - x.shape[0]), (0, 0)))
            else:
                x = x[:WINDOW]
            xs.append(x)
            ys.append(L["id"])
            srcs.append(fp)
    if not xs:
        print("❌  No data found. Record samples first with collector.py.")
        sys.exit(1)
    X = np.stack(xs, axis=0)         # (N, 300, 6)
    y = np.asarray(ys, dtype=np.int64)
    return X, y, srcs


# ---------- Normalization ----------
def fit_norm(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel mean & std across the training set."""
    flat = X.reshape(-1, X.shape[-1])
    mu   = flat.mean(axis=0).astype(np.float32)
    sd   = flat.std(axis=0).astype(np.float32)
    sd   = np.where(sd < 1e-6, 1.0, sd).astype(np.float32)
    return mu, sd


def apply_norm(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return ((X - mu) / sd).astype(np.float32)


# ---------- Augmentation ----------
rng = np.random.default_rng(SEED)

def augment(x: np.ndarray) -> np.ndarray:
    """Augment a (WINDOW, 6) float32 window IN PHYSICAL UNITS (pre-normalization).

    Air-writing is slower and more variable than table-tap, so this is more
    aggressive — bigger time warps (handwriting-speed variation), bigger shift
    (gesture may start anywhere in the 6s window), small "pause insertion"
    (holds samples constant for a stretch) to simulate thinking mid-stroke.
    """
    x = x.copy()
    # 1) random time shift (bigger — gesture may start anywhere in 6s)
    shift = int(rng.integers(-80, 81))
    if shift != 0:
        x = np.roll(x, shift, axis=0)
        if shift > 0:
            x[:shift] = x[shift:shift + 1] if shift < len(x) else 0.0
        else:
            x[shift:] = x[shift - 1:shift] if -shift < len(x) else 0.0
    # 2) per-channel gaussian noise
    noise_scale_acc  = rng.uniform(0.005, 0.03)
    noise_scale_gyro = rng.uniform(0.5,   2.5)
    noise = np.concatenate([
        rng.normal(0, noise_scale_acc,  (x.shape[0], 3)),
        rng.normal(0, noise_scale_gyro, (x.shape[0], 3)),
    ], axis=1).astype(np.float32)
    x = x + noise
    # 3) amplitude scale
    acc_scale  = rng.uniform(0.90, 1.10)
    gyro_scale = rng.uniform(0.90, 1.10)
    x[:, :3] *= acc_scale
    x[:, 3:] *= gyro_scale
    # 4) BIGGER time warp (handwriting-speed variability: ±25%)
    warp = rng.uniform(0.75, 1.25)
    new_len = max(1, int(round(x.shape[0] * warp)))
    if new_len != x.shape[0]:
        idx = np.linspace(0, x.shape[0] - 1, new_len)
        x = np.stack([np.interp(idx, np.arange(x.shape[0]), x[:, c])
                      for c in range(x.shape[1])], axis=1).astype(np.float32)
        if x.shape[0] >= WINDOW:
            start = int(rng.integers(0, x.shape[0] - WINDOW + 1))
            x = x[start:start + WINDOW]
        else:
            pad = WINDOW - x.shape[0]
            x = np.pad(x, ((0, pad), (0, 0)))
    # 5) with 25% chance insert a "thinking pause" (hold samples constant)
    if rng.random() < 0.25:
        pause_len   = int(rng.integers(10, 80))              # 100 ms – 800 ms
        pause_start = int(rng.integers(0, max(1, WINDOW - pause_len)))
        hold_vec    = x[pause_start].copy()
        x[pause_start:pause_start + pause_len] = hold_vec
    return x


def expand_with_aug(X: np.ndarray, y: np.ndarray, k: int):
    out_X, out_y = [X], [y]
    for _ in range(k):
        aug = np.stack([augment(x) for x in X], axis=0)
        out_X.append(aug)
        out_y.append(y)
    return np.concatenate(out_X, axis=0), np.concatenate(out_y, axis=0)


# ---------- Model ----------
def build_model() -> tf.keras.Model:
    inp = layers.Input(shape=(WINDOW, CHANNELS), name="imu")
    x = layers.Conv1D(16, 7, strides=2, padding="same", use_bias=False)(inp)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(32, 5, strides=2, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(48, 3, strides=2, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(len(LABELS), activation="softmax", name="probs")(x)
    m = models.Model(inp, out, name="banglasign")
    m.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
              loss="sparse_categorical_crossentropy",
              metrics=["accuracy"])
    return m


# ---------- Train / val split (stratified) ----------
def stratified_split(X: np.ndarray, y: np.ndarray, frac: float):
    rng_split = np.random.default_rng(SEED)
    val_idx, trn_idx = [], []
    for cid in np.unique(y):
        idxs = np.where(y == cid)[0]
        rng_split.shuffle(idxs)
        n_val = max(1, int(round(len(idxs) * frac)))
        val_idx.extend(idxs[:n_val].tolist())
        trn_idx.extend(idxs[n_val:].tolist())
    return np.array(trn_idx), np.array(val_idx)


# ---------- Export helpers ----------
def tflite_bytes_to_c_header(buf: bytes, var_name: str) -> str:
    lines = []
    lines.append("// Auto-generated by train.py — do not edit by hand.")
    lines.append("#pragma once")
    lines.append("#include <cstdint>")
    lines.append(f"constexpr unsigned int {var_name}_len = {len(buf)};")
    lines.append(f"alignas(16) const unsigned char {var_name}[] = {{")
    row = []
    for i, b in enumerate(buf):
        row.append(f"0x{b:02x}")
        if (i + 1) % 16 == 0:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row))
    lines.append("};")
    return "\n".join(lines) + "\n"


# ---------- Main ----------
def main():
    tf.random.set_seed(SEED)
    np.random.seed(SEED)

    print(f"📂 Loading data from {DATA_DIR}")
    X_raw, y, srcs = load_dataset()
    print(f"   Loaded {X_raw.shape[0]} samples; per-class counts:")
    for L in LABELS:
        n = int((y == L["id"]).sum())
        print(f"     • {L['name']:8s} (id={L['id']}) : {n}")

    print(f"\n🎲 Stratified split, val_frac={VAL_FRAC}")
    trn_idx, val_idx = stratified_split(X_raw, y, VAL_FRAC)
    X_trn_raw, y_trn = X_raw[trn_idx], y[trn_idx]
    X_val_raw, y_val = X_raw[val_idx], y[val_idx]
    print(f"   train={len(trn_idx)}  val={len(val_idx)}")

    print(f"\n🔀 Augmenting training set ×{AUG_PER_SAMPLE + 1}")
    X_trn_raw, y_trn = expand_with_aug(X_trn_raw, y_trn, AUG_PER_SAMPLE)
    print(f"   effective train size: {X_trn_raw.shape[0]}")

    print("\n📏 Fitting per-channel normalization on train split")
    mu, sd = fit_norm(X_trn_raw)
    print(f"   mu = {mu.tolist()}")
    print(f"   sd = {sd.tolist()}")

    X_trn = apply_norm(X_trn_raw, mu, sd)
    X_val = apply_norm(X_val_raw, mu, sd)

    print("\n🧠 Building model")
    model = build_model()
    model.summary(line_length=90)

    # Class weighting (inverse frequency, lightly smoothed)
    class_counts = np.bincount(y_trn)
    class_weight = {int(c): float(len(y_trn) / (len(class_counts) * cnt))
                    for c, cnt in enumerate(class_counts)}
    print(f"\n⚖️  class weights: {class_weight}")

    cbs = [
        callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=5, min_lr=1e-5),
        callbacks.EarlyStopping(monitor="val_loss", patience=15, restore_best_weights=True),
    ]

    print("\n🚂 Training")
    hist = model.fit(
        X_trn, y_trn,
        validation_data=(X_val, y_val),
        epochs=EPOCHS, batch_size=BATCH,
        class_weight=class_weight,
        callbacks=cbs,
        verbose=2,
    )

    # ---------- Evaluate ----------
    print("\n📊 Validation report")
    val_pred = model.predict(X_val, verbose=0).argmax(axis=1)
    target_names = [L["name"] for L in LABELS]
    print(classification_report(y_val, val_pred, target_names=target_names, zero_division=0))
    print("Confusion matrix (rows=true, cols=pred):")
    print(confusion_matrix(y_val, val_pred, labels=[L["id"] for L in LABELS]))

    # ---------- Save Keras model ----------
    keras_path = OUT_DIR / "sanket.keras"
    model.save(keras_path)
    print(f"\n💾 Saved Keras model → {keras_path}")

    # ---------- Export float32 TFLite (for host inference) ----------
    print("\n⚙️  Converting to TFLite (float32)")
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_f32 = conv.convert()
    (OUT_DIR / "sanket_float32.tflite").write_bytes(tflite_f32)
    print(f"   float32 size: {len(tflite_f32)/1024:.1f} KB")

    # ---------- Export int8 TFLite (for ESP32 later) ----------
    print("\n⚙️  Converting to TFLite (int8 fully-quantized)")

    def rep_dataset():
        for i in range(min(200, X_trn.shape[0])):
            yield [X_trn[i:i+1].astype(np.float32)]

    conv_q = tf.lite.TFLiteConverter.from_keras_model(model)
    conv_q.optimizations = [tf.lite.Optimize.DEFAULT]
    conv_q.representative_dataset = rep_dataset
    conv_q.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv_q.inference_input_type  = tf.int8
    conv_q.inference_output_type = tf.int8
    tflite_i8 = conv_q.convert()
    (OUT_DIR / "sanket_int8.tflite").write_bytes(tflite_i8)
    print(f"   int8 size:    {len(tflite_i8)/1024:.1f} KB")

    header = tflite_bytes_to_c_header(tflite_i8, "sanket_model")
    (OUT_DIR / "model_data.h").write_text(header)
    print(f"   wrote C header → models/model_data.h")

    # ---------- Save norm + labels sidecars ----------
    (OUT_DIR / "norm.json").write_text(json.dumps({
        "mu": mu.tolist(),
        "sd": sd.tolist(),
        "window": WINDOW,
        "channels": CHANNELS,
    }, indent=2))
    (OUT_DIR / "labels.json").write_text(json.dumps(LABELS, ensure_ascii=False, indent=2))
    print("💾 Saved norm.json and labels.json")

    print("\n✅ Done. Next: run infer_gui.py to see live predictions.")


if __name__ == "__main__":
    main()
