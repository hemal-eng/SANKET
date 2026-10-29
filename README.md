# SANKET

> **A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written Gesture Recognition**

<p align="center">
  <em>Giving silent hands a way to be understood.</em>
</p>

<p align="center">
  <a href="https://doi.org/10.5281/zenodo.23762217"><img src="https://zenodo.org/badge/DOI/10.5281/zenodo.23762217.svg" alt="DOI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platform-ESP32--S3-informational" alt="Platform: ESP32-S3">
  <img src="https://img.shields.io/badge/model-INT8%20TFLite-success" alt="Model: INT8 TFLite">
</p>

---

## 👤 Author

**Hassan Hemal** — Embedded Systems Engineer
📧 hemalkhan987.1234@gmail.com
📱 +88 01856514404

> This project, including its concept, architecture, dataset design, firmware,
> training pipeline, and on-device deployment, is the **original work of the
> author**. All rights reserved under the project's [LICENSE](LICENSE).

---

## 🎯 What is SANKET?

**SANKET** (সংকেত — Bangla for *signal / gesture*) is a wrist-worn embedded AI
system that lets a Deaf person **air-write a Bangla word with their wrist**
and have the device **recognize it on-chip** in real time — using nothing more
than:

- 1× **ESP32-S3** microcontroller
- 1× **MPU6050** 6-axis IMU

That's the entire BOM. Under **~$6** total. No phone, no cloud, no internet,
no camera, no glove. Just a wrist and a tiny chip running a 17 KB
quantized neural network.

### Why it matters

Over **3 million Bangladeshis are Deaf or hard-of-hearing**. Existing
sign-language solutions are built around English/ASL, require phone apps,
or need expensive cameras and gloves. SANKET is the first edge-ML system
in the Bangla language, costs almost nothing to build, and is designed to
be **worn like a watch** so it fits into daily life without stigma.

### How it works (high level)

```
┌───────────────────────────────────────────────────────────────┐
│  Deaf user wears SANKET on the wrist                           │
│         │                                                       │
│         ▼  air-writes a Bangla word (e.g. "আমি")               │
│  MPU6050 IMU streams 6-axis motion @100 Hz                     │
│         │                                                       │
│         ▼                                                       │
│  ESP32-S3  (dual-core)                                          │
│   ├─ Core 1: samples at 100 Hz into a 6 s ring buffer          │
│   ├─ Core 0: runs INT8 1D-CNN via esp-tflite-micro + esp-nn    │
│   │          (ESP32-S3 vector-ISA accelerated)                 │
│   └─ Serial output every 300 ms:                               │
│         P,ami,0.996   ← prediction + confidence                │
│         DETECTED,ami,0.996   ← fires on sustained detection    │
└───────────────────────────────────────────────────────────────┘
```

---

## 📂 Repository Layout

```
SANKET/
├── README.md                     ← you are here
├── LICENSE
├── docs/                         ← in-depth guides
│   ├── ARCHITECTURE.md           overall system design + diagrams
│   ├── SETUP.md                  one-time setup for Mac/Linux/Windows
│   ├── DATA_COLLECTION_GUIDE.md  how to collect clean gesture samples
│   ├── TRAINING.md               ML pipeline + system requirements
│   ├── DEPLOYMENT.md             how to flash + run on ESP32-S3
│   ├── GESTURE_DESIGN_GUIDE.md   how to add new words to the model
│   └── FUTURE_WORK.md            planned extensions
├── hardware/                     ← hardware references
│   ├── BOM.md                    bill of materials
│   └── WIRING.md                 ESP32-S3 ↔ MPU6050 pinout
├── references/                   ← vendored third-party libraries
│   └── BanglaText-main/          Mamunul Mazid's Bangla OLED rendering lib (MIT) — for future OLED work
├── firmware/                     ← PlatformIO: data logger firmware
│   ├── README.md
│   ├── platformio.ini
│   └── src/main.cpp
├── firmware_infer/               ← PlatformIO: on-device TFLM inference
│   ├── README.md
│   ├── platformio.ini
│   └── src/
│       ├── main.cpp              IMU + ring buffer + dual-core TFLM
│       ├── model_data.h          INT8 TFLite model as C array (17 KB)
│       └── model_norm.h          per-channel mean/std from training
└── python/                       ← ML pipeline + GUIs
    ├── README.md
    ├── requirements.txt
    ├── collector.py              PySide6 data-collection GUI
    ├── train.py                  1D-CNN + INT8 TFLite export
    ├── infer_gui.py              host-side inference GUI (debug tool)
    └── models/                   trained artifacts (small, versioned)
        ├── sanket.keras
        ├── sanket_float32.tflite
        ├── sanket_int8.tflite
        ├── model_data.h          same INT8 model as C array
        ├── labels.json           class id → name mapping
        └── norm.json             per-channel mean/std
```

---

## 🧰 Hardware Required

Minimum, this is the **entire shopping list**:

| Component                                | Qty | Approx cost |
|------------------------------------------|-----|-------------|
| ESP32-S3-DevKitC-1 (N16R8, dual-USB)     | 1   | ~$5         |
| MPU6050 breakout (clone OK)              | 1   | ~$1         |
| 4× female-female jumper wires            | 4   | <$1         |
| Micro-USB or USB-C cable                 | 1   | you own one |
| **Total**                                |     | **~$6–7**   |

Full details and wiring diagram → [`hardware/BOM.md`](hardware/BOM.md),
[`hardware/WIRING.md`](hardware/WIRING.md).

---

## 💻 Software Required

Minimum system to **train** the model yourself:

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | macOS 11+, Ubuntu 20.04+, Windows 10+ | macOS 13+ / Ubuntu 22.04+ |
| CPU | any 64-bit x86_64 or ARM64 | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 2 GB free (TensorFlow + venv) | 5 GB |
| Python | 3.10 or 3.11 | 3.11 |
| GPU | *not required* | not required (model is tiny) |
| Internet | one-time (pip + PlatformIO) | one-time |

Minimum system to **run** the pre-trained model: **just the ESP32-S3 itself**
(no laptop needed after flashing).

Full dependency list → [`python/requirements.txt`](python/requirements.txt)
and [`docs/SETUP.md`](docs/SETUP.md).

---

## 🚀 Quick Start — 5 steps from zero to detecting

> Full version in [`docs/SETUP.md`](docs/SETUP.md).

```bash
# 1. Clone
git clone https://github.com/hemal-eng/SANKET.git
cd SANKET

# 2. Install Python deps (TensorFlow, PySide6, pyqtgraph, pyserial)
cd python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# 3. Install PlatformIO
brew install platformio      # or: pip install -U platformio

# 4. Wire your hardware:
#    ESP32-S3 GPIO 8 → MPU6050 SDA
#    ESP32-S3 GPIO 9 → MPU6050 SCL
#    ESP32-S3 3V3   → MPU6050 VCC
#    ESP32-S3 GND   → MPU6050 GND
#    (see hardware/WIRING.md)

# 5a. OPTION A — run the included pre-trained model (ami + idle):
cd firmware_infer
pio run -t upload
pio device monitor --baud 921600
#    Air-write আমি in the air with your wrist → see DETECTED,ami,0.9x

# 5b. OPTION B — train your own words from scratch:
#    See docs/DATA_COLLECTION_GUIDE.md and docs/TRAINING.md
```

---

## 📋 What's Working Today

- ✅ Hardware: ESP32-S3 + MPU6050 wired on I²C @ GPIO 8/9
- ✅ Firmware (`firmware/`): one-shot 6-second gesture capture triggered from the GUI
- ✅ GUI (`python/collector.py`): PySide6-based data collector with Position × Style selectors
- ✅ Training (`python/train.py`): 1D-CNN with 24–30× augmentation, exports FP32 and INT8 TFLite + C array header
- ✅ Host-side inference (`python/infer_gui.py`): sliding-window probability bars + detection banner
- ✅ On-device inference (`firmware_infer/`): dual-core TFLM — Core 1 samples @ 100 Hz, Core 0 runs INT8 inference every 300 ms
- ✅ Trained smoke-test model: `ami` (আমি) + `idle` classes, 100 % validation accuracy on 28 held-out samples

> See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full system diagram and
> design rationale.

---

## 🧪 Reproducing the Results

With the included pre-trained model (`python/models/sanket_int8.tflite`):

1. Wire the hardware (above).
2. Flash the inference firmware: `cd firmware_infer && pio run -t upload`.
3. Open serial monitor at **921600 baud**.
4. **Keep wrist still for ~3 seconds** → log should show `P,idle,0.9x+`.
5. **Air-write আমি** (full connected word, like a signature) → log should flip to `P,ami,0.9x+` and print `DETECTED,ami,0.9x+`.
6. Return to stillness → log returns to `P,idle,...`.

---

## 📚 Guides

| Guide | What's in it |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | End-to-end system design, dual-core rationale, data flow |
| [`docs/SETUP.md`](docs/SETUP.md) | OS-by-OS install (macOS / Linux / Windows), toolchain, troubleshooting |
| [`docs/DATA_COLLECTION_GUIDE.md`](docs/DATA_COLLECTION_GUIDE.md) | How to collect clean gesture samples (positions, styles, counts) |
| [`docs/TRAINING.md`](docs/TRAINING.md) | ML pipeline, augmentation strategy, system requirements |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Flashing both firmwares, serial monitor, troubleshooting |
| [`docs/GESTURE_DESIGN_GUIDE.md`](docs/GESTURE_DESIGN_GUIDE.md) | How to add NEW Bangla words to the model |
| [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md) | Planned extensions (audio output, OLED, more words, …) |
| [`hardware/BOM.md`](hardware/BOM.md) | Bill of materials |
| [`hardware/WIRING.md`](hardware/WIRING.md) | Pinout + diagram |
| [`firmware/README.md`](firmware/README.md) | Data-logger firmware details |
| [`firmware_infer/README.md`](firmware_infer/README.md) | On-device inference firmware details |
| [`python/README.md`](python/README.md) | Python pipeline details |

---

## 🤝 Contributing / Extending

See [`docs/GESTURE_DESIGN_GUIDE.md`](docs/GESTURE_DESIGN_GUIDE.md) for the recipe
to add new Bangla words to SANKET.

---

## 🛡️ Defensive Publication / Prior Art

This project is published as a **defensive publication** to establish
worldwide prior art. The full technical disclosure is permanently
archived on Zenodo with a citeable DOI:

**DOI:** [10.5281/zenodo.23762217](https://doi.org/10.5281/zenodo.23762217)

See [`zenodo/SANKET_disclosure.pdf`](zenodo/SANKET_disclosure.pdf) for the
10-section technical disclosure, and [`zenodo/README.md`](zenodo/README.md)
for details.

### 📖 Suggested citation

> Hemal, H. (2026). *SANKET: A Wrist-Worn ESP32-S3 TinyML System for Bangla
> Deaf-Aid Air-Written Gesture Recognition* (v1.0.0) [Software].
> Zenodo. https://doi.org/10.5281/zenodo.23762217

BibTeX:
```bibtex
@software{hemal_sanket_2026,
  author       = {Hemal, Hassan},
  title        = {{SANKET: A Wrist-Worn ESP32-S3 TinyML System for
                   Bangla Deaf-Aid Air-Written Gesture Recognition}},
  version      = {1.0.0},
  year         = {2026},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.23762217},
  url          = {https://doi.org/10.5281/zenodo.23762217}
}
```

## 📜 License

See [LICENSE](LICENSE). Code is MIT-licensed. The technical disclosure in
[`zenodo/SANKET_disclosure.pdf`](zenodo/SANKET_disclosure.pdf) is licensed
CC BY 4.0.
