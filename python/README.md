# `python/` — SANKET ML Pipeline, GUIs and Tools

Everything that runs on the laptop: data collection, training, host-side
testing and voice-file preparation.

## Setup

```bash
cd python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Every tool can also be run without activating the venv:
`.venv/bin/python <tool>.py`.

## The four tools

| Tool | Needs firmware | Purpose |
|---|---|---|
| `collector.py` | `firmware/` (logger) | record fixed 6 s gesture samples |
| `train.py` | — | train the 1D-CNN, export FP32 / INT8 / C header |
| `infer_gui.py` | `firmware/` (logger) | test the trained model live on the laptop |
| `prepare_audio.py` | — | phone recordings → numbered MP3s for the DFPlayer SD card |

### `collector.py` — data collection GUI

```bash
.venv/bin/python collector.py
```

- Port dropdown lists ESP32 USB-UART bridges first, Bluetooth last
- Labels: ami, haan, dhonnobad, pani, khabar, shahajjo, salam, idle
- Position P1/P2/P3 × Style S1/S2/S3, scrollable counter grid
- Duration **locked at 6.0 s** (sends `T600` to the logger)
- SPACE = record, S = save, R = redo
- Saves to `data/<label>/pos<P>_style<S>_rep<NNN>.npz`

Full protocol: [`../docs/DATA_COLLECTION_GUIDE.md`](../docs/DATA_COLLECTION_GUIDE.md).

### `train.py` — training

```bash
.venv/bin/python train.py
```

8 classes, 5-stage Conv1D (32/64/96/128/160), label smoothing 0.05,
80 epochs, ×24 augmentation. Full details:
[`../docs/TRAINING.md`](../docs/TRAINING.md).

### `infer_gui.py` — host test GUI (auto motion-bracketed)

```bash
.venv/bin/python infer_gui.py
```

Runs the trained `models/sanket_float32.tflite` on the laptop against the live
IMU stream from the logger firmware. It works like the device does:

1. **Connect** → 2 s **calibration** (hold still). Trigger threshold =
   baseline + 6 σ of the gyro magnitude, minimum 40 °/s (fallback 150 °/s).
2. **IDLE** → waits for wrist motion above the threshold.
3. **RECORDING** → captures while you write; stops when the wrist has been
   still for **0.4 s**, or at the **max capture** time (default 3.0 s,
   adjustable 0.5–6 s in the UI).
4. Captures shorter than 0.5 s are discarded. Otherwise the capture is
   **zero-padded to 600 samples** (exactly like training) and classified
   **once**.
5. **COOLDOWN** (1 s) shows the result, then back to IDLE.

The window shows the state banner, the predicted Bangla word with
confidence, the live energy bar, the baseline/threshold, probability bars,
live accel/gyro plots and a log. It is resizable and scrollable for small
screens. **Recalibrate** and **Abort** buttons are included.

### `prepare_audio.py` — DFPlayer voice files

```bash
.venv/bin/python prepare_audio.py
# or with explicit folders:
.venv/bin/python prepare_audio.py --in ../The_Audios --out ../The_Audios/SD_CARD/mp3
```

Takes `Ami.aac, Haan.aac, Dhonnobad.aac, Pani.aac, Khabar.aac, Shahajjo.aac,
Salam.aac` (also `.m4a` / `.wav`) and writes `0001.mp3 … 0007.mp3`
(file number = class id):

1. decode to 16-bit mono 44.1 kHz (macOS `afconvert`, or `ffmpeg`)
2. trim silence below −40 dB of the peak (80 ms padding kept)
3. normalise the peak to −1 dBFS so all words are equally loud
4. encode MP3 128 kbps mono (`lameenc`)

Copy the resulting `mp3/` folder to the root of a FAT32 SD card. Full SD-card
steps: [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).

## `models/` — trained artifacts

| File | Size | Purpose |
|---|---:|---|
| `sanket.keras` | ~1.6 MB | full Keras model |
| `sanket_float32.tflite` | ~517 KB | host inference (`infer_gui.py`) |
| `sanket_int8.tflite` | ~149 KB | INT8 model deployed on the ESP32-S3 |
| `model_data.h` | ~930 KB (text) | INT8 model as C array `sanket_model[]` |
| `labels.json` | tiny | id → name + Bangla |
| `norm.json` | tiny | per-channel mean / std, window 600, 6 channels |

After retraining, copy `model_data.h` and regenerate `model_norm.h` for the
firmware (see [`../docs/TRAINING.md`](../docs/TRAINING.md) § 10).

## Stopping a GUI

Close the window, or from a terminal:

```bash
pkill -f collector.py
pkill -f infer_gui.py
```
