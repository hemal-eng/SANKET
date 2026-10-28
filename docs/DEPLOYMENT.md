# SANKET — Deployment Guide

How to flash SANKET onto an ESP32-S3-DevKitC-1 and watch it recognize
gestures over serial.

## 1. Two firmwares, one dev board

| Firmware folder | What it does | When to flash |
|---|---|---|
| `firmware/` | **Data logger**. Records 6 s one-shot gestures on SPACEBAR, no ML on-chip. | During data collection. |
| `firmware_infer/` | **On-device inference**. Runs the trained INT8 TFLite model on both cores, prints predictions on serial. | After training — the deployed product. |

The two firmwares use the **same wiring** and the **same board**. Flashing
one replaces the other — the user flashes whichever role they need now.

## 2. Prerequisites

- Setup done per [`SETUP.md`](SETUP.md): PlatformIO installed, drivers in place, Python venv.
- Trained artifacts in `python/models/` (either the included smoke-test
  model, or your own from [`TRAINING.md`](TRAINING.md)).

## 3. Flash the inference firmware

```bash
cd firmware_infer
pio run -t upload
```

First-time build pulls `espressif/esp-tflite-micro` + Arduino-ESP32 core —
this takes 3–8 minutes depending on bandwidth. Subsequent builds are
~10 seconds.

> **Note:** the inference firmware already includes a working INT8 model
> (`src/model_data.h`) built from the smoke-test dataset (ami + idle).
> You can try it immediately without training anything yourself.

Expected final lines of a successful build:
```
RAM:   [====      ]  39.9% (used 130732 bytes from 327680 bytes)
Flash: [=         ]   5.8% (used 381662 bytes from 6553600 bytes)
...
Hard resetting via RTS pin...
========================= [SUCCESS] Took 25.92 seconds =========================
```

## 4. Watch it work

```bash
pio device monitor --baud 921600
```

After reset you'll see:

```
H,SANKET-infer,v1,100hz,on-device
C,START
C,DONE,-0.37,-0.86,0.29,0.79,0.40,4.54
I,ready
P,idle,0.996
P,idle,0.996
P,idle,0.996
```

Air-write আমি (full connected signature-style sweep, ~3 seconds) and
you'll see:

```
P,idle,0.823
P,ami,0.942
P,ami,0.991
DETECTED,ami,0.991
P,ami,0.996
P,ami,0.996
P,idle,0.654
P,idle,0.996
```

| Line | Meaning |
|---|---|
| `H,...` | Handshake on boot (name, version, sample rate) |
| `C,START` / `C,DONE` | 2-second IMU calibration happening — keep wrist still |
| `I,ready` | TFLM allocated tensors successfully, inference running |
| `P,<class>,<conf>` | Prediction every ~300 ms. Confidence ∈ [0, 1] |
| `DETECTED,<class>,<conf>` | Fires when confidence > 0.75 for 2 consecutive frames |
| `E,<reason>` | Error (I²C read fail, invoke fail, etc.) |

Exit the serial monitor with **Ctrl+C**.

## 5. Switch back to data-logger firmware

```bash
# Close any open serial monitor (Ctrl+C) first
cd firmware
pio run -t upload
```

Now the device is a pure one-shot recorder again — launch the collector:
```bash
cd ../python
source .venv/bin/activate
python collector.py
```

## 6. Deploying your own trained model

If you re-trained with new data or new words:

```bash
# After train.py completes, update the firmware:
cp python/models/model_data.h  firmware_infer/src/model_data.h

# If labels.json changed (added a new class), also update
# firmware_infer/src/model_norm.h  →  MODEL_CLASSES + MODEL_CLASS_NAMES[]

cd firmware_infer
pio run -t upload
```

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `A fatal error occurred: Could not open /dev/...` | Serial monitor is still open — close it (Ctrl+C), re-run upload |
| `E,who_am_i=0x00` | MPU6050 wiring wrong or power missing — recheck [`../hardware/WIRING.md`](../hardware/WIRING.md) |
| `E,tflite_init_fail` | Model + firmware ops mismatch after retraining — regenerate `model_data.h` and `model_norm.h` |
| `E,allocate_tensors_failed` | Model too large for 90 KB arena — increase `kTensorArenaSize` in `firmware_infer/src/main.cpp` |
| Serial port disappears (`ls /dev/cu.*` empty) | Unplug + replug USB cable |
| Predictions stuck at idle 0.996 regardless of gesture | Calibration ran while your wrist was moving — unplug + replug, keep wrist still until `C,DONE` appears |
| Predictions degrade after first good detection | Should NOT happen on dual-core firmware — if it does, confirm you're on `firmware_infer/` (not an older build) |

## 8. What a successful on-device demo looks like

```
┌────────────────────────────────────────┐
│  Serial Monitor @ 921600               │
│                                         │
│  H,SANKET-infer,v1,100hz,on-device     │
│  C,DONE,...                            │
│  I,ready                               │
│  P,idle,0.996    ← wrist still         │
│  P,idle,0.996                          │
│  P,idle,0.998                          │
│                                         │
│  (user air-writes "আমি")                │
│                                         │
│  P,ami,0.712                           │
│  P,ami,0.942                           │
│  DETECTED,ami,0.942     ← ← SUCCESS     │
│  P,ami,0.996                           │
│  P,ami,0.996                           │
│  P,idle,0.654                          │
│  P,idle,0.996    ← wrist still again   │
└────────────────────────────────────────┘
```
