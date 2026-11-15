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

CHANNELS      = 6            # ax,ay,az,gx,gy,gz
# WINDOW is now AUTO-DISCOVERED from the dataset (longest .npz across every
# class). Variable-duration collection means each word can have a different
# natural length; we train on a single padded window = max observed length,
# rounded up to the nearest 50 samples for cleaner shapes.
WINDOW        = None         # filled in by load_dataset() at runtime

LABELS        = [            # order sets integer class ids — classes present in data/
    {"id": 0, "name": "idle",      "bangla": "(idle / rest)"},
    {"id": 1, "name": "ami",       "bangla": "আমি"},
    {"id": 2, "name": "haan",      "bangla": "হ্যাঁ"},
    {"id": 3, "name": "dhonnobad", "bangla": "ধন্যবাদ"},
    {"id": 4, "name": "pani",      "bangla": "পানি"},
    {"id": 5, "name": "khabar",    "bangla": "খাবার"},
    {"id": 6, "name": "shahajjo",  "bangla": "সাহায্য"},
    {"id": 7, "name": "salam",     "bangla": "সালাম"},
]
NAME_TO_ID    = {L["name"]: L["id"] for L in LABELS}

AUG_PER_SAMPLE = 24          # synthetic copies per real target sample (random-position + idle-fill)
VAL_FRAC       = 0.15
EPOCHS         = 80
BATCH          = 64
SEED           = 1337
LABEL_SMOOTHING= 0.05        # soft targets — helps when two classes share features


# ---------- Data loading ----------
def load_dataset():
    """Scan data/<label>/*.npz, load each sample as-is, zero-pad to the
    longest sample. No mixing, no random position. Raw samples straight in."""
    all_entries = []
    for L in LABELS:
        files = sorted(set(
            glob.glob(str(DATA_DIR / L["name"] / "pos*_rep*.npz")) +
            glob.glob(str(DATA_DIR / L["name"] / "pos*_style*_rep*.npz"))
        ))
        if not files:
            print(f"⚠️  no files for class '{L['name']}' under {DATA_DIR / L['name']}")
            continue
        for fp in files:
            z = np.load(fp)
            x = z["data"].astype(np.float32)
            all_entries.append((x, L["id"], fp))

    if not all_entries:
        print("❌  No data found."); sys.exit(1)

    lengths = [e[0].shape[0] for e in all_entries]
    raw_max = max(lengths)
    window = ((raw_max + 49) // 50) * 50
    print(f"\n📏 Natural sample lengths: min={min(lengths)}  "
          f"median={int(np.median(lengths))}  max={raw_max}")
    print(f"   → WINDOW set to {window} samples ({window/100:.1f} s @ 100 Hz)")

    xs, ys, srcs = [], [], []
    for x, cid, fp in all_entries:
        if x.shape[0] < window:
            pad = np.zeros((window - x.shape[0], 6), dtype=np.float32)
            x = np.concatenate([x, pad], axis=0)
        elif x.shape[0] > window:
            x = x[:window]
        xs.append(x); ys.append(cid); srcs.append(fp)
    X = np.stack(xs, axis=0)
    y = np.asarray(ys, dtype=np.int64)
    globals()["WINDOW"] = window
    return X, y, srcs, window


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
    """Standard augmentation: noise, scale, time warp, small shift."""
    x = x.copy()
    # time shift
    shift = int(rng.integers(-60, 61))
    if shift != 0:
        x = np.roll(x, shift, axis=0)
        if shift > 0:
            x[:shift] = 0.0
        else:
            x[shift:] = 0.0
    # noise
    noise = np.concatenate([
        rng.normal(0, rng.uniform(0.005, 0.03), (x.shape[0], 3)),
        rng.normal(0, rng.uniform(0.5,  2.5),   (x.shape[0], 3)),
    ], axis=1).astype(np.float32)
    x = x + noise
    # scale
    x[:, :3] *= rng.uniform(0.90, 1.10)
    x[:, 3:] *= rng.uniform(0.90, 1.10)
    # time warp
    warp = rng.uniform(0.80, 1.20)
    new_len = max(2, int(round(x.shape[0] * warp)))
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
    """Bigger 1D-CNN — ~2× channel width + extra conv stage at full temporal
    resolution. Adds capacity to tell apart confusable classes whose IMU
    signatures share endpoints. Still ESP32-S3 friendly after int8."""
    inp = layers.Input(shape=(WINDOW, CHANNELS), name="imu")
    x = layers.Conv1D(32, 7, strides=2, padding="same", use_bias=False)(inp)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(64, 5, strides=2, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(96, 3, strides=2, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(128, 3, strides=2, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.Conv1D(160, 3, strides=1, padding="same", use_bias=False)(x)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dropout(0.4)(x)
    out = layers.Dense(len(LABELS), activation="softmax", name="probs")(x)
    m = models.Model(inp, out, name="sanket")
    # one-hot + categorical CE with label smoothing (sparse CE has no smoothing).
    def smoothed_loss(y_true, y_pred):
        y_oh = tf.one_hot(tf.cast(tf.squeeze(y_true), tf.int32), depth=len(LABELS))
        return tf.keras.losses.categorical_crossentropy(
            y_oh, y_pred, label_smoothing=LABEL_SMOOTHING)
    m.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
              loss=smoothed_loss,
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
    X_raw, y, srcs, _window = load_dataset()
    print(f"   Loaded {X_raw.shape[0]} samples; per-class counts:")
    for L in LABELS:
        n = int((y == L["id"]).sum())
        print(f"     • {L['name']:10s} (id={L['id']}) : {n}")

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
