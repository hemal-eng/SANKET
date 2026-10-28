# SANKET
## A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written Gesture Recognition

**Technical Disclosure & Defensive Publication**

---

**Author:** Hassan Hemal (Embedded Systems Engineer)
**Contact:** hemalkhan987.1234@gmail.com &middot; +88 01856514404
**Repository:** https://github.com/hemal-eng/SANKET
**Date of first public disclosure:** 2026-10-29
**License:** MIT (code) &middot; CC BY 4.0 (this document)

> **Statement of authorship and rights.** The invention described in this
> document — including its concept, hardware architecture, firmware design,
> data-collection methodology, machine-learning pipeline, model architecture,
> and on-device deployment approach — is the **original work of the author,
> Hassan Hemal**. This document is published for *defensive publication*
> purposes: to establish prior art and prevent subsequent patenting of the
> same ideas by third parties. All rights not expressly granted under the
> stated licenses are reserved by the author.

---

## Abstract

**SANKET** (Bangla: *সংকেত*, "signal / gesture") is a wrist-worn embedded
AI system that enables a Deaf person to **air-write a Bangla word with
their wrist** and have the device **recognize it on-chip** in real time,
without any phone, cloud service, camera, or glove.

The hardware consists of a single ESP32-S3-DevKitC-1 (N16R8) microcontroller
and a single MPU6050 6-axis inertial measurement unit (IMU) — a bill of
materials under **US $7**. The firmware runs a quantized int8 1D
convolutional neural network via `esp-tflite-micro` with `esp-nn`
ESP32-S3 vector-ISA acceleration, consuming only ~17 KB of flash and
~27 KB of a 90 KB tensor arena. A novel **dual-core sampling + inference
architecture** guarantees uninterrupted 100 Hz IMU sampling by pinning
sampling to one Xtensa LX7 core and `interpreter->Invoke()` to the other
via FreeRTOS, communicated through a mutex-protected snapshot buffer.
Boot-time calibration, software IIR low-pass filtering, and a fixed
6-second one-shot recording protocol together yield robust gestures
from inexpensive MPU6050 clones.

On the author's smoke-test dataset of 138 samples (49 air-written আমি
+ 89 idle, collected across 3 wrist positions × 3 writing styles),
the trained int8 model achieves **100 % validation accuracy** on 28
held-out samples. The device detects the গেস্চার in real time with
sustained-detection confirmation.

To the author's knowledge, this is the **first open-source Bangla
air-written gesture recognition system that runs entirely on an edge
microcontroller**, and the first to apply the dual-core
sampling-plus-inference architecture to a wrist-worn deaf-aid context.

---

## 1. Problem Statement and Motivation

Bangladesh has over **three million Deaf and hard-of-hearing citizens**.
Existing assistive technologies for sign-language or air-writing
recognition are built around:

- **English/ASL-centric** phone apps (do not generalize to Bangla),
- **Camera-based** systems (require costly setup, poor privacy, fail at
  night, require a free line-of-sight),
- **Glove-based** systems (expensive flex-sensor arrays, cumbersome,
  socially stigmatizing),
- **Cloud ML** services (require continuous internet, violate privacy,
  often don't support Bangla).

**No prior work** addresses the specific intersection of (i) **Bangla**
language, (ii) **air-written** gesture recognition with a single
wrist-mounted IMU, (iii) **on-device** inference on a microcontroller,
and (iv) **ultra-low cost** (under $10 BOM).

**SANKET** fills this gap. It is designed from first principles as a
*deaf-aid for daily, dignified use*: worn like a watch, works offline,
costs almost nothing to manufacture, and preserves user privacy
(no data ever leaves the device).

---

## 2. Prior Art Review

| Approach | Representative work | Limitations addressed by SANKET |
|---|---|---|
| ASL glove with flex sensors | Pyarali *et al.*, Pandey *et al.* (various) | Expensive sensors (~$30+), social stigma, English only |
| Camera-based sign recognition | Google MediaPipe hands, Microsoft Kinect-based | Requires phone/PC/line-of-sight, high power, Bangla rarely supported |
| Smartphone IMU air-writing | *Air-Writing* lineage (English/digits) | Phone must be in hand; not Bangla; not wearable; needs an app |
| Cloud-based speech-to-sign | Various apps | Requires internet, no Deaf-to-hearing direction |
| TinyML wrist-worn gesture | TensorFlow Lite Micro "Magic Wand" demo | Only 4 simple non-linguistic gestures; English-centric; no on-device Bangla work |

Bangla is largely absent from the TinyML literature as of this disclosure
date. SANKET is believed to be the first system to combine on-microcontroller
TFLite-Micro inference with Bangla air-written gestures for Deaf
communication.

---

## 3. System Architecture

### 3.1 Overview

```
Wrist (user wears SANKET)
   │
   ▼ air-writes a Bangla word (e.g. "আমি")
MPU6050 IMU — 6-axis (ax,ay,az,gx,gy,gz) @ 100 Hz over I²C
   │
   ▼
ESP32-S3-N16R8 (dual-core Xtensa LX7 @ 240 MHz)
   ├── Core 1 (loop)       : IMU sampling + IIR filter + ring buffer
   ├── Core 1 (loop)       : every 30 samples → mutex-guarded snapshot
   │                         → notify core 0
   └── Core 0 (inferTask)  : normalize + quantize snapshot → INT8 1D-CNN
                           → esp-tflite-micro + esp-nn SIMD on S3
                           → softmax → P,<class>,<confidence> over UART
```

### 3.2 Hardware

| Component | Specification | Role |
|---|---|---|
| ESP32-S3-DevKitC-1 (N16R8) | 240 MHz dual-core Xtensa LX7, 512 KB SRAM, 8 MB PSRAM, 16 MB flash | Compute + inference |
| MPU6050 | 6-axis IMU, ±4 g accel, ±500 °/s gyro, I²C @ 0x68 | Motion sensing |
| Jumper wires (4) | — | SDA / SCL / 3V3 / GND |

**Total BOM:** ≈ US $6–7.

### 3.3 Firmware

Two PlatformIO Arduino projects share the same wiring:

**(a) Data-logger firmware (`firmware/`)** — Streams IMU over USB-UART
(921600 baud) and performs 6-second one-shot captures on command.
Protocol (host → device: `T\n`; device → host: `H…C…L…R,START…D×600…
R,STOP,600`). Novel protocol detail: all recordings are **fixed length**
(600 samples at 100 Hz = 6.000 s) with no "when to stop" trigger — the
firmware counts samples. This eliminates the entire class of recording-cut
bugs that plague button-triggered IMU capture during vigorous motion.

**(b) Inference firmware (`firmware_infer/`)** — Loads a quantized
int8 TFLite model via `esp-tflite-micro` with `esp-nn`-accelerated kernels
(CONV_2D, EXPAND_DIMS, FULLY_CONNECTED, MEAN, RESHAPE, SOFTMAX).
Boot-time calibration subtracts the gyro/accel bias. IIR low-pass
(α = 0.30) filters each sample. A 600-slot ring buffer rolls at 100 Hz.
Every 30 new samples, the ring is snapshotted and inference runs on
the other core (details in §4).

### 3.4 Dual-core sampling + inference (novel)

Prior single-core implementations of TFLM on ESP32 encounter a subtle
pathology: `interpreter->Invoke()` blocks the main loop for 30–100 ms,
during which no IMU samples are read. When the loop resumes, it
rapid-fires catch-up samples at ≈1 ms spacing (not 10 ms), producing
*stutter clumps* in the ring buffer. Over successive inferences, the
ring buffer effectively represents 7.5 s of wall-clock time compressed
into its 6-second training-distribution shape, degrading recognition
of subtle gestures on all but the first inference after boot.

SANKET's firmware eliminates this by:

1. Pinning `loop()` to core 1 to do **only** sampling + ring-buffer writes.
2. Running `inferTask` on core 0 (FreeRTOS task, priority 1).
3. Communicating via a `memcpy`'d snapshot buffer protected by a
   `xSemaphoreTake`-held mutex. The critical section is ≈140 µs — a
   fraction of the 10 ms sample interval, so sampling is never blocked.
4. Triggering `inferTask` with `xTaskNotifyGive` from `loop()`.

After this change, the model's performance on *repeated* gestures matches
its performance on the *first* gesture after boot. On the author's
dataset this restored sustained-detection reliability from "occasionally
works" to "every gesture detected".

---

## 4. Data Collection Methodology (novel)

### 4.1 Fixed-duration one-shot capture

Each sample is **exactly** 600 IMU rows (6.0 s at 100 Hz). The host
GUI (`collector.py`, PySide6) sends a `T\n` trigger; the firmware
auto-stops when the sample counter hits 600. This eliminates
"when to release" ambiguity and defeats the mechanical-shock problem
of button-held captures during table-slamming gestures.

### 4.2 Position × Style protocol (novel)

For each target word, samples are collected across a Cartesian product:

| Factor | Values | Rationale |
|---|---|---|
| **Position (P)** | P1 natural, P2 raised, P3 low | Arm pose variability |
| **Style (S)** | S1 normal, S2 slow-careful, S3 quick-sloppy | Writing-speed variability |
| **Repetitions** | ≥ 5 per (P, S) cell | Within-user variability |

Target: **3 P × 3 S × 5 reps = 45 samples per word**. Combined with an
**idle class** (random/rest, 30–50 samples) the dataset forces the model
to learn the gesture *shape* rather than any particular pose or tempo.

### 4.3 Air-written full-word gesture (novel)

Unlike letter-by-letter air-writing (which produces inter-letter pauses
indistinguishable from random motion), SANKET's gestures are **connected
signature-style sweeps**. Each word becomes a single fluid motion with
clear start, body, and end. Empirically this yields more distinct and
more repeatable IMU signatures than letter decomposition.

---

## 5. Machine-Learning Pipeline

### 5.1 Model architecture

```
Input         (600, 6)  float32  (per-channel normalized)
Conv1D(16, 7, s=2) + BN + ReLU  → (300, 16)
Conv1D(32, 5, s=2) + BN + ReLU  → (150, 32)
Conv1D(48, 3, s=2) + BN + ReLU  → ( 75, 48)
GlobalAveragePooling1D          → ( 48,)
Dropout(0.3)
Dense(K, softmax)               → ( K,)   K = number of classes
```

Parameters: ≈ 5 K. INT8 TFLite size: ≈ 17 KB.

### 5.2 Augmentation strategy

To combat small-dataset overfitting, training applies 24–30 synthetic
variants per real sample:

| Augmentation | Range | Simulates |
|---|---|---|
| Time shift | ± 80 samples | Early/late gesture start inside the 6 s window |
| Gaussian noise | σ_a ∈ [0.005, 0.03] g; σ_g ∈ [0.5, 2.5] °/s | MPU clone noise |
| Amplitude scale (per group) | 0.90 – 1.10 | Larger/smaller gestures |
| Time warp (interpolation) | 0.75 – 1.25 | Fast / slow writers |
| Pause insertion | 100 – 800 ms, p = 0.25 | Thinking mid-stroke |

### 5.3 Training

Stratified split (20 % val), Adam optimizer, sparse categorical
cross-entropy, class-weighted (inverse-frequency). `ReduceLROnPlateau`
+ `EarlyStopping` on `val_loss`. Up to 80 epochs. Full INT8 quantization
with a representative dataset drawn from the augmented training split.

---

## 6. Experimental Results

### 6.1 Dataset

| Class | Samples | Across Positions | Across Styles |
|---|---|---|---|
| ami (air-written আমি) | 49 | P1 / P2 / P3 | S1 / S2 / S3 |
| idle (random / rest) | 89 | P1 / P2 / P3 | — |
| **Total** | **138** | — | — |

### 6.2 Validation metrics

Stratified 20 % validation split (10 ami + 18 idle):

| Metric | idle | ami | overall |
|---|---|---|---|
| Precision | 1.00 | 1.00 | — |
| Recall | 1.00 | 1.00 | — |
| F1 | 1.00 | 1.00 | — |
| Accuracy | — | — | **1.00 (28/28)** |

Confusion matrix (rows = true, cols = pred):
```
      idle  ami
idle  [ 18    0 ]
 ami  [  0   10 ]
```

### 6.3 On-device performance

| Property | Value |
|---|---|
| Flash occupied by model | ≈ 17 KB |
| Tensor arena used | ≈ 27 KB of 90 KB allocated |
| Inference latency (ESP32-S3 @ 240 MHz, esp-nn) | ≈ 30–60 ms per inference |
| Inference frequency | ≈ 3.3 Hz (every 30 samples / 300 ms) |
| Sustained-detection latency | ≈ 600 ms (2 consecutive high-confidence frames) |
| IMU sampling rate (while inferring) | 100.0 Hz, uninterrupted |

### 6.4 Live demonstration

In repeated real-time runs, air-writing আমি triggers a `DETECTED,ami,0.9x`
message within one inference cycle after the gesture completes, and the
device returns to `P,idle,0.9+` state within one further 6-second window
as the gesture rolls out of the sliding buffer. Multiple consecutive
gestures (post-dual-core fix) all detect reliably.

---

## 7. Novelty Claims

The following elements, individually and in combination, constitute the
author's original contribution and are hereby disclosed to the public:

1. A **wrist-worn Bangla air-written gesture recognition system** running
   entirely on an ESP32-S3 microcontroller with a single MPU6050 IMU,
   with a bill of materials under US $10.

2. A **fixed-duration one-shot gesture-capture protocol** (6.0 s at 100 Hz)
   that eliminates stop-trigger reliability failures during physically
   vigorous gestures.

3. A **dual-core sampling + inference architecture** on ESP32-S3 wherein
   sampling runs continuously on core 1 and TFLite-Micro inference runs
   in parallel on core 0, communicated through a mutex-guarded ring-buffer
   snapshot, specifically to prevent inference-induced sample stutter from
   degrading recognition of subtle motion gestures.

4. A **Position × Style × Repetition data-collection protocol** (3 P ×
   3 S × ≥ 5 reps = 45 samples/word) tailored to the within-user
   variability of air-written Bangla.

5. **Air-written full-word connected gesture encoding** (signature-style
   sweeps) in place of letter-by-letter decomposition, for improved
   distinctness and reproducibility of Bangla word gestures on a single
   wrist-mounted IMU.

6. A **TinyML pipeline for Bangla** combining per-channel normalization,
   24–30× data augmentation (shift / noise / scale / time-warp / pause),
   a ~5K-parameter 1D-CNN, full INT8 quantization, and
   `esp-tflite-micro`/`esp-nn` deployment, producing a <20 KB on-chip
   model with sustained-detection confidence > 0.9.

7. The use of this complete pipeline **as a Deaf-aid communication device**
   for Bangla speakers, allowing a Deaf user to express words through air
   motion that are then output over serial for subsequent text/audio
   display (audio output is described as a planned extension; see §8).

---

## 8. Future Work (planned extensions)

The following are planned extensions and are also disclosed to establish
their derivation from the above work:

- **Audio output via DFPlayer Mini + speaker.** On a `DETECTED,<word>,
  <conf>` event the firmware will play a pre-recorded MP3 of the word
  via UART-controlled DFPlayer, converting the Deaf user's silent gesture
  into audible Bangla speech for a hearing listener.
- **Expanded vocabulary** to the 10 survival words most needed by Deaf
  Bangladeshis: আমি, তুমি, হ্যাঁ, না, ধন্যবাদ, পানি, খাবার, সাহায্য, ডাক্তার, ভালো.
- **SSD1306 OLED display** for simultaneous visual output of the detected
  Bangla word.
- **Battery + wearable enclosure** (18650 + TP4056 + buck + 3D-printed strap).
- **Multi-user data collection and per-user calibration** for productization.
- **BLE companion app** forwarding transcriptions to a phone for TTS and logging.

---

## 9. License

- **Code:** MIT License &copy; 2026 Hassan Hemal
- **This document:** Creative Commons Attribution 4.0 International (CC BY 4.0)

Both licenses are irrevocable and establish this work as prior art
worldwide as of the publication date (2026-10-29).

---

## 10. Suggested Citation

> Hemal, H. (2026). *SANKET: A Wrist-Worn ESP32-S3 TinyML System for
> Bangla Deaf-Aid Air-Written Gesture Recognition* (Version 1.0.0)
> [Technical disclosure]. Zenodo. https://doi.org/10.5281/zenodo.XXXXXXX

(Replace `XXXXXXX` with the DOI assigned by Zenodo upon upload.)

---

**End of disclosure.**
