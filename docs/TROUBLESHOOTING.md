# SANKET — Troubleshooting

Every real problem met while building SANKET, written as
**symptom → cause → fix**. Grouped by area.

---

## 1. Build and toolchain

### 1.1 `ModuleNotFoundError: No module named 'littlefs'` / "Obsolete PIO Core"

**Symptom**

```
Obsolete PIO Core v6.1.19 is used (previous was 6.2.0)
ModuleNotFoundError: No module named 'littlefs'
  File ".../platforms/espressif32/builder/main.py", line 54
```

**Cause** — two PlatformIO installations. VS Code was running an old
pip-installed copy in `/usr/local` that lacks the `littlefs` module the
espressif32 platform needs.

**Fix** — keep only the **pioarduino** core (`~/.platformio/penv`) and
remove the old one:

```bash
rm /usr/local/bin/pio /usr/local/bin/platformio
rm -rf /usr/local/lib/python3.11/site-packages/platformio /usr/local/lib/python3.11/site-packages/platformio-*.dist-info
which -a pio
```

`which -a pio` must list only `~/.platformio/penv/bin/pio`. (pioarduino
reports `6.1.19` at runtime while pip shows `6.2.0` — that is normal.)

### 1.2 `fatal error: kiss_fft.c: No such file or directory`

**Cause** — `esp-tflite-micro` was pulled from GitHub as a library. Its
`signal/` DSP sources include `kiss_fft.c` through a path PlatformIO cannot
resolve.

**Fix** — see 1.4 (do not use the GitHub copy at all).

### 1.3 `multiple definition of 'tflite::Register_FULLY_CONNECTED()'` (and SOFTMAX, MUL, POOL, `ticks_per_second` …)

**Cause** — the GitHub copy ships both generic kernels and their ESP-NN
versions; PlatformIO compiled both.

**Fix** — see 1.4.

### 1.4 `Register_IRFFT() conflicts with a previous declaration`

**Symptom**

```
micro_ops.h:178: error: 'tflite::micro::tflm_signal::Register_IRFFT()'
conflicts with a previous declaration
.../framework-arduinoespressif32-libs/esp32s3/include/espressif__esp-tflite-micro/signal/micro/kernels/irfft.h
```

**Cause** — **two different copies of TensorFlow Lite Micro**: one from
GitHub in `.pio/libdeps/…/esp-tflite-micro`, and one already bundled
(precompiled, with esp-nn) inside the Arduino-ESP32 framework. The unpinned
GitHub copy changed version; its headers then mixed with the framework's
headers, which use a different namespace. Earlier workarounds (a prebuild
script that deleted `signal/` and duplicate kernels) made it worse.

**Fix (permanent)** — use only the framework's bundled TFLM:

1. Remove `https://github.com/espressif/esp-tflite-micro.git` from
   `lib_deps` in `firmware_infer/platformio.ini`.
2. Remove the `extra_scripts` prebuild hook and the script.
3. Remove `-DTF_LITE_STATIC_MEMORY` and `-DESP_NN` from `build_flags`
   (the framework already defines them).
4. Delete the stale copy and rebuild clean:

```bash
cd firmware_infer
rm -rf .pio/libdeps/esp32-s3-devkitc-1/esp-tflite-micro .pio/build
pio run
```

### 1.5 `region 'dram0_0_seg' overflowed by 10272 bytes`

**Cause** — adding the OLED framebuffer and BanglaText pushed static RAM
over 320 KB. The tensor arena was reserved at 220 KB but the model only
uses ~150.8 KB.

**Fix** — arena trimmed to **168 KB** (`kTensorArenaSize = 168 * 1024`).
RAM is now 73.9 %. If you train a bigger model and see
`E,allocate_tensors_failed`, raise it or move the arena to PSRAM.

---

## 2. Sensor and serial

### 2.1 Graph flat, all values zero (`L,0.0000,0.0000,…`)

**Cause** — the firmware runs but the MPU6050 does not answer on I²C.

**Fix** — check VCC (3.3 V), GND, SDA → GPIO 8, SCL → GPIO 9, loose
breadboard rows, and that SDA/SCL are not swapped.

### 2.2 GUI connects to a Bluetooth port

**Cause** — macOS lists Bluetooth ports (`/dev/cu.AWEIG83BL`,
`/dev/cu.BLTH`) before the ESP32's port.

**Fix** — choose `/dev/cu.wchusbserial…` (the collector ranks it first
automatically).

### 2.3 Serial monitor shows garbage

**Cause** — baud mismatch. `firmware_infer` uses **115200**; the data
logger `firmware/` and the Python GUIs use **921600**.

**Fix** — `monitor_speed` in `platformio.ini` must equal `Serial.begin()`
in `main.cpp`.

### 2.4 "Port busy" / cannot open port

**Cause** — another program (VS Code monitor, a GUI) has the port open.

**Fix** — close it, or stop all Python processes:

```bash
pkill -f collector.py; pkill -f infer_gui.py
```

---

## 3. Recognition

### 3.1 Everything classified as `idle`, confidence ~0.4–0.6

**Cause** — the device was powered on **tilted or upside-down**. Boot
calibration subtracts gravity in that position, so every accelerometer
reading is shifted by up to ~2 g versus training.

| Boot | `C,DONE` (ax, ay, az) | Result |
|---|---|---|
| Flat, face-up | `0.015, -0.162, 0.970` | 82–92 % detections |
| Tilted | `-0.109, -0.401, -0.939` | 0 detections in 20 captures |

**Fix** — lay the device flat, face-up, press RST, keep still ~3 s.
Check `C,DONE`: az ≈ **+0.97**.

### 3.2 Short motions give `idle ≈ 0.5`

**Cause** — normal. A capture of 0.5–1.5 s is mostly zero-padding, which
the model recognises as rest.

**Fix** — write the whole word in one continuous motion, then hold still.

### 3.3 Two words confuse each other

**Cause** — similar wrist trajectories (e.g. the end of আমি matched the
start of তুমি). `tumi` and `na` were removed from the vocabulary for this
reason.

**Fix** — design gestures with distinct motion
([`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md)) or collect more
samples of the confused pair.

---

## 4. OLED display

### 4.1 I²C scan finds 0x3C, `init_ok`, but the screen stays blank

**Cause** — some SSD1306 clones start with the charge pump off or contrast
at 0, or wiring/power is marginal.

**Fix** — the diagnostic sketch sends charge pump ON (`0x8D,0x14`),
contrast `0xFF` and `DISPLAYON` (`0xAF`) and fills the screen white; if
still dark, check VCC/GND.

### 4.2 Bangla text appears rotated relative to English text

**Cause** — the BanglaText renderer lays each word out **along the Y
axis** (top to bottom), while Adafruit GFX text runs along X.

**Fix** — Bangla is rendered into an off-screen `GFXcanvas1(40, 128)`,
its bounding box is measured, and it is copied to the screen **rotated
270°** and centred. English header/footer text is left untouched. See
[`AUDIO_AND_DISPLAY.md`](AUDIO_AND_DISPLAY.md).

### 4.3 Long words (ধন্যবাদ, সাহায্য, লিখছেন) cut in half

**Cause** — the off-screen canvas was `192 × 64`. Long words need up to
81 px along Y (ধন্যবাদ 73 px, লিখছেন 81 px), so their ends were clipped
before rotation.

**Fix** — canvas changed to **`40 × 128`** (tall). After rotation the
longest word is ~81 px wide — fits the 128 px screen.

### 4.4 OLED wired to GPIO 19/20

**Cause** — those are the ESP32-S3 native-USB D−/D+ pins.

**Fix** — the OLED now uses **GPIO 41 (SDA) / 42 (SCL)**.

---

## 5. Audio (DFPlayer Mini)

### 5.1 `E,dfplayer_not_responding` / `W,dfplayer_not_found…`

**Fix** — check: VCC on **5V**, common GND, ESP32 GPIO 17 → 1 kΩ →
DFPlayer RX, GPIO 18 ← DFPlayer TX, SD card inserted. Test with
`src/test/main_dfplayer_phase1_test.cpp`.

### 5.2 `files=-1` or `W,file_count_mismatch`

**Cause** — `files=-1`: the card was still initialising right after the
module reset. Mismatch: macOS adds hidden files (`._*`, `.Spotlight-V100`,
`.fseventsd`) that the DFPlayer counts.

**Fix** — usually harmless (playback is by number from `/mp3/`). Clean
the card:

```bash
mdutil -i off /Volumes/SANKET
dot_clean -m /Volumes/SANKET
find /Volumes/SANKET -name "._*" -delete
rm -rf /Volumes/SANKET/.fseventsd /Volumes/SANKET/.Trashes
```

### 5.3 Word shows on OLED but no sound

**Cause** — audio only plays for a **detection**: top class not idle **and**
confidence ≥ 0.75. The OLED shows the top word for every capture,
including `unclear` results under 0.75.

**Fix** — check serial: no `DETECTED` / `AUDIO,play` line means low
confidence (see 3.1). If `AUDIO,play` appears but nothing is heard, check
the speaker wires, volume (`AUDIO_VOLUME`, 0–30) and the 5 V supply.

### 5.4 Buzzing, clicks, or the DFPlayer resets while playing

**Fix** — add the 1 kΩ series resistor on RX and a 100–470 µF capacitor
across VCC/GND near the module; power from 5 V, never 3.3 V.

---

## 6. Python GUIs

### 6.1 GUI exits with code 134 (`QThread: Destroyed while thread is still running`)

**Cause** — the serial reader thread was still running when the window
closed.

**Fix** — `closeEvent()` stops the reader and waits up to 2 s before
closing (in both `collector.py` and `infer_gui.py`). Exit code 139 on
Intel Macs after closing is a harmless Qt cleanup crash — data is already
saved.

### 6.2 GUI does not fit on a small Mac screen

**Fix** — both GUIs open at a laptop-friendly size (~980 × 640–680), can
be shrunk (minimum 560 × 420 for `infer_gui.py`, 640 × 480 for
`collector.py`), and wrap their content in scroll areas.

### 6.3 Training: `no files for class '…'`

**Cause** — the class name in `train.py` `LABELS` has no matching folder
in `python/data/`.

**Fix** — names in `collector.py`, `train.py` and the folder names must
match exactly.
