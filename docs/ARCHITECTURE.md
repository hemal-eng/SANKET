# SANKET — System Architecture

This document describes how SANKET works end to end: the hardware, the
two firmwares, the machine-learning pipeline, and the runtime behaviour
of the wearable device.

---

## 1. The idea in one picture

```
 ┌───────────────────────── THE WEARABLE (no laptop, no internet) ─────────────────────────┐
 │                                                                                         │
 │   wrist air-writes "পানি"                                                                │
 │          │                                                                              │
 │          ▼                                                                              │
 │   MPU6050  ──I²C (GPIO 8/9)──►  ESP32-S3  ──I²C (GPIO 41/42)──►  SSD1306 OLED: "পানি"     │
 │   6-axis @100 Hz                 │   ├─ Core 1: sampling + motion-trigger state machine  │
 │                                  │   └─ Core 0: INT8 1D-CNN (TFLite-Micro + esp-nn)      │
 │                                  │                                                      │
 │                                  └──UART2 (GPIO 17/18, BUSY 16)──►  DFPlayer Mini        │
 │                                                                       │                 │
 │                                                                       ▼                 │
 │                                                       speaker says "পানি" (0004.mp3)    │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

A Deaf user writes a Bangla word in the air with the wrist. The device
detects the motion, records exactly that gesture, classifies it on the
chip in about 40 ms, shows the Bangla word on the OLED and speaks it
through the speaker — fully offline.

---

## 2. Project components

| Part | Folder | Role |
|---|---|---|
| **Data-logger firmware** | `firmware/` | Streams raw IMU data to the laptop and records fixed 6 s samples on command. Used only for building the dataset. |
| **Collector GUI** | `python/collector.py` | PySide6 app that drives the logger firmware and saves labelled samples to `python/data/`. |
| **Training pipeline** | `python/train.py` | Trains the 1D-CNN, quantises it to INT8 and exports a C header for the firmware. |
| **Host test GUI** | `python/infer_gui.py` | Runs the trained model on the laptop with the same motion-bracketed capture logic, for testing before flashing. |
| **Audio preparation** | `python/prepare_audio.py` | Converts voice recordings into the numbered MP3 files the DFPlayer plays. |
| **Inference firmware** | `firmware_infer/` | The wearable itself: sensing, triggering, on-chip inference, OLED display and voice output. |

```
   DEVELOPMENT (laptop)                                         DEPLOYMENT (wrist)
 ┌──────────────────────────────────────────────┐          ┌──────────────────────────┐
 │ firmware/ ──► collector.py ──► python/data/  │          │                          │
 │                                   │          │          │   firmware_infer/        │
 │                                   ▼          │  flash   │   + model_data.h         │
 │                              train.py ───────┼─────────►│   + model_norm.h         │
 │                                   │          │          │   + SD card /mp3/*.mp3   │
 │                                   ▼          │          │                          │
 │                           infer_gui.py (test)│          └──────────────────────────┘
 └──────────────────────────────────────────────┘
```

---

## 3. Hardware

| Device | Bus | ESP32-S3 pins | Notes |
|---|---|---|---|
| MPU6050 IMU | I²C bus 0 (`Wire`) | SDA 8, SCL 9 | 0x68, 400 kHz, ±4 g / ±500 °/s, DLPF 44 Hz |
| SSD1306 OLED 128×64 | I²C bus 1 (`Wire1`) | SDA 41, SCL 42 | 0x3C, 400 kHz |
| DFPlayer Mini | UART2 @ 9600 | TX 17 → RX (via 1 kΩ), RX 18 ← TX, BUSY 16 | 5 V supply, speaker on SPK_1/SPK_2 |

The two I²C devices are on **separate buses** so the 100 Hz sensor reads
never wait behind a slow OLED screen update. Full wiring, parts list and
power notes: [`hardware/WIRING.md`](../hardware/WIRING.md),
[`hardware/BOM.md`](../hardware/BOM.md).

---

## 4. Signal pipeline (identical in collector, trainer and firmware)

The same preprocessing runs everywhere, so the model sees the same kind
of numbers in training and on the device.

| Step | Detail |
|---|---|
| Sample rate | 100 Hz (one sample every 10 ms) |
| Channels | `ax, ay, az` in g, `gx, gy, gz` in °/s |
| Boot calibration | 200 samples while still; their mean is subtracted from every later sample |
| Low-pass filter | IIR, `y = 0.30·x + 0.70·y_prev` per channel |
| Model window | 600 samples × 6 channels (6.0 s) |
| Normalisation | per-channel `(x − μ) / σ` using `norm.json` from training |
| Quantisation | `q = round(norm / scale) + zero_point`, clamped to int8 |

> **Important — boot orientation.** Calibration subtracts the gravity
> direction measured at power-on. The training data was recorded with the
> board **flat and face-up** at boot. Booting tilted or upside-down shifts
> the accelerometer channels by up to 2 g and the model's confidence
> collapses. Always power on with the device flat and still.

---

## 5. Runtime state machine (inference firmware)

```
   ┌──────────────┐  energy ≥ 80 °/s   ┌───────────────┐  still 0.4 s  or  3.5 s cap   ┌──────────────┐
   │     IDLE     │───────────────────►│   CAPTURING   │─────────────────────────────►│    FINISH    │
   │  OLED: লিখুন  │                    │ OLED: লিখছেন   │  (< 0.5 s → discarded,        │ zero-pad to  │
   └──────▲───────┘                    └───────────────┘   back to IDLE)               │ 600, notify  │
          │                                                                            │ core 0       │
          │                                                                            └──────┬───────┘
          │                                                                                   │
   ┌──────┴──────────────────────────┐        ┌──────────────────────────────────────────────▼──────┐
   │            COOLDOWN             │◄───────│ INFER (core 0, ~40 ms)                              │
   │ waits until the result is out   │        │ top class ≠ idle and conf ≥ 0.75                    │
   │ AND the word finished playing,  │        │   → OLED "DETECTED 92%" + Bangla word               │
   │ then 1.0 s more → IDLE          │        │   → DFPlayer plays /mp3/000<class>.mp3              │
   └─────────────────────────────────┘        │ otherwise → OLED "unclear", no sound                │
                                              └─────────────────────────────────────────────────────┘
```

**Motion energy** is the rolling maximum, over the last 10 samples
(100 ms), of the filtered gyroscope magnitude `√(gx² + gy² + gz²)`.

| Parameter | Value | Why |
|---|---|---|
| Trigger threshold | 80 °/s | Tested on the wrist: ignores tremor, catches soft writing |
| Max capture | 3.5 s | Longest word fits; zero-padded to 6 s like the training data |
| Min capture | 0.5 s | Shorter bumps are discarded as noise |
| Settle time | 0.4 s | Wrist still this long ⇒ word finished |
| Detect confidence | 0.75 | Below this the device stays silent — a wrong spoken word is worse than none |
| Cooldown | 1.0 s after audio ends | Arm movement while the speaker talks cannot start a new capture |

### Why motion-bracketed capture?

Training samples always start with the gesture and end with stillness
(zero-padded to 6 s). An earlier design ran the model on a continuously
sliding 6 s window; there the gesture landed at a random position in the
window, which the model never saw in training, and detection wobbled.
Starting the capture at motion onset reproduces the training alignment
exactly, which is what made live detection reliable.

---

## 6. Dual-core task layout

| Core | Task | Job |
|---|---|---|
| **Core 1** | `loop()` | Reads the MPU6050 every 10 ms, filters, computes energy, runs the state machine, fills the capture buffer |
| **Core 0** | `inferTask` (FreeRTOS, 16 KB stack) | Waits for a notification, normalises + quantises the snapshot, runs `Invoke()`, prints the result, updates the OLED, starts audio |

The capture buffer is copied into a separate **snapshot** buffer under a
mutex, then core 0 is notified. Inference never blocks sampling.

---

## 7. The neural network

| Layer | Configuration |
|---|---|
| Input | 600 × 6 |
| Conv1D ×5 | 32 / 64 / 96 / 128 / 160 filters, kernels 7/5/3/3/3, strides 2/2/2/2/1, each + BatchNorm + ReLU |
| Pooling | GlobalAveragePooling1D |
| Regularisation | Dropout 0.4 |
| Output | Dense(8) softmax |

Classes (index = class id = audio track number):

| id | name | Bangla | audio file |
|---|---|---|---|
| 0 | idle | (rest / everyday movement) | — |
| 1 | ami | আমি | 0001.mp3 |
| 2 | haan | হ্যাঁ | 0002.mp3 |
| 3 | dhonnobad | ধন্যবাদ | 0003.mp3 |
| 4 | pani | পানি | 0004.mp3 |
| 5 | khabar | খাবার | 0005.mp3 |
| 6 | shahajjo | সাহায্য | 0006.mp3 |
| 7 | salam | সালাম | 0007.mp3 (spoken as আস-সালামু আলাইকুম) |

Training details and results: [`TRAINING.md`](TRAINING.md).

---

## 8. Resource budget (ESP32-S3 N16R8)

| Resource | Used | Notes |
|---|---|---|
| Flash | ~874 KB of 6.4 MB app partition (13.3 %) | INT8 model 149 KB + Bangla font ~228 KB + code |
| Internal RAM | ~242 KB of 320 KB (73.9 %) | Tensor arena 168 KB (150.8 KB actually used) |
| Inference time | ~39–42 ms | esp-nn vector kernels, precompiled in the Arduino-ESP32 framework |
| PSRAM | unused (8 MB available) | Reserved for future features such as Bluetooth |

---

## 9. Serial protocol (inference firmware, 115200 baud)

| Line | Meaning |
|---|---|
| `H,SANKET-infer,v4,...` | Boot banner |
| `C,START` / `C,DONE,ax,ay,az,gx,gy,gz` | Calibration offsets |
| `I,audio_ok,files=N,volume=25` | DFPlayer found |
| `I,arena_used=…` / `I,ready,…` / `I,class_order=…` | Model loaded, parameters, class order |
| `LIVE,energy=E` | Once per second while idle |
| `STATE,IDLE` / `STATE,CAPTURING,energy=E` / `STATE,COOLDOWN` | State changes |
| `CAP,n=…,elapsed=…,energy=…,settled=…` | Capture progress every 0.5 s |
| `STATE,FINISH,n=…,elapsed=…,reason=settled\|max_cap\|short_discard` | Capture ended |
| `INFER,top=…,conf=…,infer_ms=…,probs=[…]` | Full probability vector |
| `DETECTED,word,conf` | Confident non-idle result |
| `AUDIO,play=N,word` / `AUDIO,done` | Voice output |
| `W,…` / `E,…` | Warnings / errors |

Full example log and flashing steps: [`DEPLOYMENT.md`](DEPLOYMENT.md).
