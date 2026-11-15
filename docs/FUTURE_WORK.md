# SANKET — Roadmap & Future Work

## ✅ Done

| Feature | Where |
|---|---|
| Data-logger firmware + fixed 6 s collector GUI | `firmware/`, `python/collector.py` |
| 8-class INT8 model (7 Bangla words + idle), 100 % validation | `python/train.py`, `python/models/` |
| On-device inference on the ESP32-S3 (TFLM + esp-nn, ~40 ms per inference) | `firmware_infer/` |
| **Motion-triggered capture** — starts when the wrist moves (80 °/s), ends when it settles (0.4 s) or at 3.5 s | `firmware_infer/src/main.cpp` |
| **Bangla OLED display** — SSD1306 128×64, BanglaText renderer, word rotated to match the panel mounting | `firmware_infer/src/main.cpp` |
| **Voice output** — DFPlayer Mini speaks the detected word from the SD card | `firmware_infer/src/audio.cpp` |
| No re-trigger while the word is being spoken | `firmware_infer/src/main.cpp` |
| Host test GUI with automatic motion-bracketed capture | `python/infer_gui.py` |
| Voice-file preparation tool | `python/prepare_audio.py` |

## 🔜 Next

### 1. Orientation-independent calibration
At boot the firmware subtracts the accelerometer reading of the boot pose.
If the device boots upside-down, every reading is offset by almost 2 g and
confidence collapses. **Plan:** calibrate only the gyro bias at boot and use a
fixed accelerometer offset measured flat (≈ 0, 0, +0.97 g), matching the
training data. No retraining needed.

### 2. Boot experience
- Splash animation **সংকেত**
- Self-test checklist on the OLED: `IMU ✓  MODEL ✓  VOICE ✓`
- Calibration screen **স্থির রাখুন** with a progress bar
- Welcome greeting **আস-সালামু আলাইকুম** from the speaker
- 🔇 icon when the DFPlayer is missing (display-only mode)

### 3. Sticky result screen
Keep the detected word on the OLED until the next word starts, or for 15 s,
instead of returning to the ready screen after the cooldown. Show
`● ready` in the header once the device re-arms.

### 4. UI task + event queue
Move all OLED drawing and DFPlayer commands into one low-priority FreeRTOS
`uiTask` fed by a queue, so the 100 Hz sampling loop never waits on I²C or
UART. Split `main.cpp` into `imu`, `inference`, `ui_oled`, `audio` and
`config.h`.

### 5. Bluetooth presentation app
A large live view for a projector during demos.
- The ESP32-S3 supports **Bluetooth Low Energy only** (no Classic/SPP).
- Firmware: NimBLE-Arduino service `SANKET` sends a small notification per
  state change and result (word, confidence, probabilities), plus energy at
  ~5 Hz for a motion bar.
- Mac: Python app with `bleak` (BLE) + PySide6 (full-screen view).
- BLE needs ~50 KB of internal RAM. Move the tensor arena to the 8 MB PSRAM
  to make room.

### 6. Wearable hardware
- LiPo battery + charger (TP4056) + boost to 5 V for the DFPlayer
- Battery percentage on the OLED
- 3D-printed wrist enclosure with a speaker grille
- Custom PCB combining ESP32-S3, MPU6050, OLED connector and DFPlayer

### 7. More words, more users
- Grow toward 10–15 distinct words (see
  [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md))
- Collect data from several Deaf users so the model generalises beyond one writer
- Optional replay of the last word with a wrist flick or button
- Volume control button (low / mid / high)
