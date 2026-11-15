# firmware_infer — SANKET wearable firmware

This is the firmware that runs on the wrist. It senses the air-written
word, classifies it on the ESP32-S3, shows it on the OLED in Bangla and
speaks it through the DFPlayer Mini. No laptop is needed after flashing.

Version string: `H,SANKET-infer,v4,motion-trigger+oled+audio,100hz`

---

## Files

```
firmware_infer/
├── platformio.ini                 build configuration
├── README.md                      this file
└── src/
    ├── main.cpp                   sensing, state machine, inference task, OLED
    ├── audio.h / audio.cpp        DFPlayer Mini module (UART2 + BUSY pin)
    ├── model_data.h               INT8 TFLite model as a C array (~149 KB)
    ├── model_norm.h               window size, class names, per-channel μ/σ
    ├── BanglaMNRegular_25pt.h     Bangla font for the BanglaText renderer
    └── test/                      stand-alone test sketches (not compiled)
        ├── main_dfplayer_phase1_test.cpp     DFPlayer-only test: plays 0001–0007, keyboard control
        ├── main_oled_bangla270_working.cpp   model + OLED version before audio was added
        ├── main_oled_full.cpp                first OLED integration
        └── main_motion_trigger_working.cpp   model only, serial output, no OLED
```

`platformio.ini` has `build_src_filter = +<*> -<test/>`, so the test
sketches are kept for reference but never compiled. To run one, copy it
over `src/main.cpp` (keep a backup of the real one first).

---

## What `main.cpp` does

| Section | Responsibility |
|---|---|
| **Pins & config** | Every pin, threshold and timing constant at the top of the file |
| **OLED helpers** | Header/footer in English (Adafruit GFX); Bangla word rendered off-screen, rotated 270° and centred |
| **MPU6050 helpers** | Register setup (100 Hz, DLPF 44 Hz, ±500 °/s, ±4 g), burst read, boot calibration |
| **TFLite setup** | Loads the model, registers 6 ops (Conv2D, ExpandDims, FullyConnected, Mean, Reshape, Softmax), allocates a 168 KB arena |
| **`inferTask` (core 0)** | Quantises the snapshot, runs the model, prints `INFER`, decides `DETECTED`, starts audio, draws the result |
| **`finishCapture()`** | Copies the capture into the snapshot (zero-padded to 600) and wakes core 0 |
| **`setup()`** | Serial → MPU → calibration → OLED → DFPlayer → model → task |
| **`loop()` (core 1)** | 100 Hz sampling, filter, motion energy, IDLE / CAPTURING / COOLDOWN state machine |

### Key constants

| Constant | Value | Meaning |
|---|---|---|
| `TRIG_THRESH_DPS` | 80.0 | Gyro energy that starts a capture |
| `MAX_CAPTURE_S` | 3.50 | Capture length cap |
| `MIN_CAPTURE_S` | 0.50 | Shorter captures are discarded |
| `STOP_SETTLE_S` | 0.40 | Stillness that ends a capture |
| `COOLDOWN_S` | 1.00 | Re-arm delay after the audio finishes |
| `DETECT_CONF` | 0.75 | Minimum confidence to show "DETECTED" and speak |
| `AUDIO_VOLUME` | 25 | DFPlayer volume, 0–30 |
| `kTensorArenaSize` | 168 KB | TFLite working memory (≈150.8 KB used) |

### Audio module (`audio.h`)

```cpp
bool audioInit(int rx_pin, int tx_pin, int busy_pin, uint8_t volume); // ~2.5 s, false if absent
bool audioReady();
int  audioFileCount();       // files seen on the card, -1 if offline
void audioPlay(int track);   // plays /mp3/000<track>.mp3
bool audioActive();          // true while playing (+0.5 s grace after the command)
```

The class id from the model **is** the track number, so `pani` (class 4)
plays `/mp3/0004.mp3`. If the DFPlayer is missing, the device keeps
working with the display only.

---

## Build & flash

```bash
cd firmware_infer
pio run                       # build only
pio run -t upload             # build + flash
pio device monitor -b 115200  # watch the serial log
```

- **TensorFlow-Lite-Micro is not in `lib_deps`.** The Arduino-ESP32
  framework already ships a precompiled `esp-tflite-micro` with esp-nn
  acceleration. Adding a second copy from GitHub causes header conflicts
  (see [`../docs/TROUBLESHOOTING.md`](../docs/TROUBLESHOOTING.md)).
- Libraries pulled automatically: BanglaText, Adafruit SSD1306,
  Adafruit GFX, DFRobotDFPlayerMini.
- Serial runs at **115200** baud (the data-logger firmware in
  `../firmware/` uses 921600).

Build result: RAM 73.9 %, flash 13.3 %.

---

## After retraining the model

1. Run `python/train.py` — it writes `python/models/model_data.h`,
   `norm.json` and `labels.json`.
2. Copy `python/models/model_data.h` → `firmware_infer/src/model_data.h`.
3. Update `firmware_infer/src/model_norm.h` with the new `MODEL_MU`,
   `MODEL_SD`, `MODEL_CLASSES` and `MODEL_CLASS_NAMES` (same order as
   `labels.json`).
4. If classes changed, update `CLASS_BANGLA[]` in `main.cpp` (same order)
   and the MP3 files on the SD card (class id = track number).
5. Rebuild and flash.

Details: [`../docs/TRAINING.md`](../docs/TRAINING.md) and
[`../docs/GESTURE_DESIGN_GUIDE.md`](../docs/GESTURE_DESIGN_GUIDE.md).
