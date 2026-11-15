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
  <img src="https://img.shields.io/badge/language-Bangla-orange" alt="Language: Bangla">
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

**SANKET** (সংকেত — Bangla for *signal / gesture*) is a wrist-worn device
that lets a Deaf or speech-impaired person **write a Bangla word in the
air with the wrist** and have it **shown on a screen and spoken aloud** —
recognised entirely on a microcontroller, with no phone, no cloud and no
internet.

```
   wrist writes "পানি" in the air
             │
             ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ MPU6050 ─► ESP32-S3 ─► INT8 neural network (≈40 ms on-chip)   │
   │                 │                                            │
   │                 ├─► OLED shows   পানি   (DETECTED 92%)        │
   │                 └─► speaker says "পানি"                       │
   └──────────────────────────────────────────────────────────────┘
```

### Why it matters

Millions of people in Bangladesh are Deaf or hard of hearing. Existing
sign-language tools are built around English/ASL, need a phone, a camera
or a sensor glove, and often an internet connection. SANKET works in
**Bangla**, is built from low-cost hobby parts, runs **fully offline**,
and is meant to be **worn like a watch**.

### Recognised words

| | Word | Meaning | Spoken as |
|---|---|---|---|
| 1 | আমি | I / me | আমি |
| 2 | হ্যাঁ | yes | হ্যাঁ |
| 3 | ধন্যবাদ | thank you | ধন্যবাদ |
| 4 | পানি | water | পানি |
| 5 | খাবার | food | খাবার |
| 6 | সাহায্য | help | সাহায্য |
| 7 | সালাম | greeting | আস-সালামু আলাইকুম |
| — | *idle* | everyday movement — ignored | — |

---

## ✨ Features

- **Air-written Bangla word recognition** with a 6-axis IMU on the wrist
- **On-device INT8 1D-CNN** (149 KB) with TensorFlow-Lite-Micro + esp-nn, ~40 ms per inference
- **Motion-triggered capture** — no button: the device starts recording when the wrist moves and stops when it settles
- **Bangla text on a 0.96″ OLED** with correct conjuncts (BanglaText renderer)
- **Natural voice output** through a DFPlayer Mini, recorded in a real human voice
- **Dual-core design** — sampling never pauses for inference or the display
- **Safe behaviour** — low-confidence results stay silent; no re-trigger while speaking
- Complete toolchain: data collector GUI, training pipeline, host test GUI, audio preparation

---

## 🧰 Hardware

| Component | Role |
|---|---|
| ESP32-S3-DevKitC-1 (N16R8) | Brain: sensing, recognition, display, audio |
| MPU6050 (GY-521) | 6-axis motion sensor |
| SSD1306 0.96″ 128×64 I²C OLED | Shows the Bangla word |
| DFPlayer Mini + microSD card | Plays the recorded word |
| 3 W 4–8 Ω speaker | Voice output |
| 1 kΩ resistor, 100–470 µF capacitor, wires | Signal and power hygiene |
| **Total** | **≈ ৳1,670 / ≈ $16** |

**Pin map**

| Device | ESP32-S3 pins |
|---|---|
| MPU6050 | SDA **GPIO 8**, SCL **GPIO 9** (I²C bus 0) |
| OLED | SDA **GPIO 41**, SCL **GPIO 42** (I²C bus 1) |
| DFPlayer | TX **GPIO 17** → 1 kΩ → RX, RX **GPIO 18** ← TX, BUSY **GPIO 16** |

Full parts list with prices → [`hardware/BOM.md`](hardware/BOM.md) ·
wiring diagram and power notes → [`hardware/WIRING.md`](hardware/WIRING.md)

---

## 📂 Repository layout

```
SANKET/
├── README.md                     ← you are here
├── LICENSE                       MIT
├── docs/
│   ├── ARCHITECTURE.md           system design, state machine, resources, protocol
│   ├── DEVELOPMENT_LOG.md        how the project was built, decisions, lessons
│   ├── SETUP.md                  installing the tools
│   ├── DATA_COLLECTION_GUIDE.md  recording gesture samples
│   ├── TRAINING.md               model, augmentation, results, export
│   ├── DEPLOYMENT.md             flashing the wearable, serial log reference
│   ├── AUDIO_AND_DISPLAY.md      Bangla OLED rendering, voice files, SD card
│   ├── GESTURE_DESIGN_GUIDE.md   choosing and adding new words
│   ├── TROUBLESHOOTING.md        every problem met so far, with fixes
│   └── FUTURE_WORK.md            roadmap
├── hardware/
│   ├── BOM.md                    bill of materials
│   └── WIRING.md                 complete wiring + power
├── firmware/                     PlatformIO — data-logger firmware (dataset recording)
├── firmware_infer/               PlatformIO — the wearable firmware
│   └── src/
│       ├── main.cpp              sensing, motion trigger, inference, OLED
│       ├── audio.h / audio.cpp   DFPlayer module
│       ├── model_data.h          INT8 model (C array)
│       ├── model_norm.h          normalisation + class names
│       ├── BanglaMNRegular_25pt.h  Bangla font
│       └── test/                 stand-alone test sketches
├── python/
│   ├── collector.py              data-collection GUI
│   ├── train.py                  training + INT8 export
│   ├── infer_gui.py              host-side test GUI
│   ├── prepare_audio.py          voice recordings → DFPlayer MP3s
│   ├── requirements.txt
│   └── models/                   trained model artifacts
├── The_Audios/SD_CARD/mp3/       ready-to-copy voice files 0001–0007.mp3
├── references/BanglaText-main/   vendored Bangla text library (MIT)
└── zenodo/                       defensive-publication package
```

---

## 🚀 Quick start

```bash
# 1. Get the code
git clone https://github.com/hemal-eng/SANKET.git
cd SANKET

# 2. Python tools (data collection, training, testing, audio)
cd python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# 3. Firmware toolchain: PlatformIO (pioarduino core) — see docs/SETUP.md

# 4. Prepare the SD card: copy The_Audios/SD_CARD/mp3/ to the card root
#    (FAT32, MBR) — see docs/AUDIO_AND_DISPLAY.md

# 5. Wire the hardware — see hardware/WIRING.md

# 6. Flash the wearable firmware (pre-trained 8-class model included)
cd firmware_infer
pio run -t upload
pio device monitor -b 115200
```

> ⚠️ **Power on with the device flat, face-up and still.** The sensor
> calibrates at boot; a tilted boot shifts the readings and the words will
> not be recognised.

Then write a word in the air, pause, and watch:
```
STATE,CAPTURING,energy=91.3
STATE,FINISH,n=182,elapsed=1.82s,reason=settled
INFER,top=pani,conf=0.918,infer_ms=42,probs=[...]
DETECTED,pani,0.918
AUDIO,play=4,pani
```
The OLED shows **পানি** and the speaker says it.

---

## 📊 Results

| Metric | Value |
|---|---|
| Dataset | 778 samples (7 words + idle), fixed 6 s each, 3 positions × 3 writing styles |
| Validation accuracy | **100 %** on 117 held-out samples |
| Live on-device test | 6/6 words detected at 72–92 % confidence; accidental movements → idle |
| Model size | 149 KB (INT8) |
| Inference time | ~40 ms on ESP32-S3 |
| RAM / flash use | 73.9 % / 13.3 % |

---

## 📚 Documentation

| Guide | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, signal pipeline, state machine, dual-core layout, resources, serial protocol |
| [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md) | Step-by-step history: what was built, what failed, why decisions were made |
| [`docs/SETUP.md`](docs/SETUP.md) | Installing Python, PlatformIO and drivers |
| [`docs/DATA_COLLECTION_GUIDE.md`](docs/DATA_COLLECTION_GUIDE.md) | Recording clean gesture samples |
| [`docs/TRAINING.md`](docs/TRAINING.md) | Model, augmentation, training results, exporting to the firmware |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Building, flashing, reading the serial log |
| [`docs/AUDIO_AND_DISPLAY.md`](docs/AUDIO_AND_DISPLAY.md) | Bangla OLED rendering, recording and preparing voice files, SD card |
| [`docs/GESTURE_DESIGN_GUIDE.md`](docs/GESTURE_DESIGN_GUIDE.md) | Choosing good words and adding new ones |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Symptoms, causes and fixes |
| [`docs/FUTURE_WORK.md`](docs/FUTURE_WORK.md) | Roadmap |
| [`hardware/BOM.md`](hardware/BOM.md) · [`hardware/WIRING.md`](hardware/WIRING.md) | Parts and wiring |
| [`firmware/README.md`](firmware/README.md) · [`firmware_infer/README.md`](firmware_infer/README.md) · [`python/README.md`](python/README.md) | Component details |

---

## 🙏 Acknowledgements

- [BanglaText](https://github.com/mamunul/BanglaText) by Mamunul Mazid (MIT) — Bangla text rendering on embedded displays
- [esp-tflite-micro](https://github.com/espressif/esp-tflite-micro) and esp-nn by Espressif — on-chip inference
- Adafruit SSD1306 / GFX and DFRobot DFPlayer Mini libraries

---

## 🛡️ Defensive Publication / Prior Art

This project is published as a **defensive publication** to establish
worldwide prior art. The full technical disclosure is permanently
archived on Zenodo with a citeable DOI:

**DOI:** [10.5281/zenodo.23762217](https://doi.org/10.5281/zenodo.23762217)

See [`zenodo/SANKET_disclosure.pdf`](zenodo/SANKET_disclosure.pdf) for the
technical disclosure, and [`zenodo/README.md`](zenodo/README.md) for details.

### 📖 Suggested citation

> Hemal, H. (2026). *SANKET: A Wrist-Worn ESP32-S3 TinyML System for Bangla
> Deaf-Aid Air-Written Gesture Recognition* (v1.0.0) [Software].
> Zenodo. https://doi.org/10.5281/zenodo.23762217

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
CC BY 4.0. Voice recordings in `The_Audios/` are the author's own voice and
are provided for use with this project.
