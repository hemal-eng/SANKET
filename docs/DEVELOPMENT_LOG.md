# SANKET — Development Log

How the project was built, what was tried, what failed, and why each
design decision was made. This is the "story" of the system; the other
documents describe the result.

Author: **Hassan Hemal**

---

## Timeline at a glance

| Date (2026) | Milestone |
|---|---|
| Oct 29 | Concept, repository, MIT licence; defensive publication on Zenodo (DOI 10.5281/zenodo.23762217) |
| Oct 29 | Data-logger firmware + collector GUI; smoke test with **আমি + idle** reaches 100 % |
| Oct 29 | First on-device inference (dual-core TFLite-Micro) |
| Oct 30 | Expansion to 10 words; variable-length recording tried and abandoned; dataset re-recorded at a fixed 6 s |
| Oct 30 | Word set refined: ভালো → সালাম, then তুমি and না removed; bigger model |
| Nov 6 | Motion-triggered capture designed and proven on the host GUI |
| Nov 7 | **On-device milestone:** motion-trigger firmware detects 6/6 test words at 72–92 % confidence |
| Nov 7 | Bangla OLED display working on a second I²C bus |
| Nov 7 | Own-voice recordings converted and loaded on the DFPlayer SD card |
| Nov 15 | Voice output integrated; toolchain cleaned up; full documentation |

---

## Phase 1 — Collecting the first data

**Goal:** prove that a $6 ESP32-S3 + MPU6050 can tell an air-written
Bangla word apart from everyday movement.

- `firmware/` was written as a pure data logger: it samples the MPU6050
  at 100 Hz, calibrates at boot, low-pass filters, and streams `L,…`
  lines. On a `T<N>` command it records exactly N samples (`D,…` lines).
- `python/collector.py` (PySide6 + pyqtgraph) drives the logger: pick a
  word, a wrist **position** (P1–P3) and a writing **style** (S1 normal,
  S2 slow-careful, S3 quick-sloppy), press record, and each sample is
  saved as `posP_styleS_repNNN.npz`.
- First test set: **আমি** and **idle**, 6 s per sample.
- `python/train.py` trained a small 1D-CNN with ×24 augmentation and
  exported an INT8 TFLite model as a C header.

**Result:** 100 % validation accuracy, and the live demo detected আমি
reliably. This is the "Ami smoke test" every later step was compared to.

---

## Phase 2 — Running the model on the chip

- `firmware_infer/` loads the INT8 model with TensorFlow-Lite-Micro and
  esp-nn (ESP32-S3 vector instructions).
- A single-core version stuttered: `Invoke()` blocked the main loop and
  IMU samples were lost during gestures. The fix was a **dual-core**
  design — core 1 samples, core 0 infers in a FreeRTOS task, and a mutex
  protects a snapshot copy of the buffer.

---

## Phase 3 — From 2 words to many, and the padding lesson

**Target list:** আমি, তুমি, হ্যাঁ, না, ধন্যবাদ, পানি, খাবার, সাহায্য, ডাক্তার, ভালো.

1. Long words take longer to write, so the collector was given a 2–20 s
   **duration slider**. Samples now had different lengths and had to be
   zero-padded to the longest one.
2. Live detection got worse, and short words such as না never fired.
   The cause: the original আমি data was **all exactly 6 s**, so the
   model always saw "gesture, then stillness" in the same shape. Mixed
   lengths broke that consistency.
3. **Decision:** every sample is a fixed **6.0 s** again (the slider
   was locked). All words except আমি were re-recorded, and idle samples
   of other lengths were deleted (128 → 53 kept).
4. ডাক্তার was dropped; ভালো was replaced by **সালাম**, spoken as
   **আস-সালামু আলাইকুম**.

**Result:** 100 % validation on the re-recorded set.

---

## Phase 4 — Making live detection robust

Validation was perfect, but live use still wobbled on some words.

| Observation | Action |
|---|---|
| তুমি was constantly confused with আমি — the end strokes of one look like the start of the other | তুমি removed (data archived, not deleted) |
| না (a very short word) was unreliable | Pruned, then removed |
| খাবার, সাহায্য, সালাম, ধন্যবাদ never failed | They have long, distinctive motions — a useful design rule for new words |
| Few samples for the weak words | More samples recorded: dataset grew to **778** |

The model grew from 4 conv stages (24/48/72/96 filters, ~52 KB INT8) to
5 stages (32/64/96/128/160, ~149 KB INT8) with **label smoothing 0.05**
and 80 epochs. With 778 samples the larger model no longer overfits, and
label smoothing gives better-calibrated confidence. Final validation:
**100 % on 117 held-out samples.**

---

## Phase 5 — Motion-triggered capture (the key breakthrough)

**Problem:** the device ran the model on a continuously sliding 6 s
window. The gesture landed at a random position inside the window,
which never happens in training data (gesture always at the start).

**Idea:** start recording only when the wrist moves, and stop when it
settles — a "software button" that a wearable needs anyway.

1. Prototype in `python/infer_gui.py`: gyro-energy trigger, threshold
   slider, fixed 6 s capture, then a single inference.
2. Tuning on the wrist: 150 °/s worked on the host; **80 °/s** was best
   on the device. Waiting 6 s felt too slow, so capture now ends when
   the wrist is still for **0.4 s** (cap **3.5 s**, minimum 0.5 s) and is
   zero-padded to 600 samples — exactly how `train.py` pads.
3. The same state machine was ported to the firmware with detailed
   serial telemetry (`STATE`, `CAP`, `INFER`, `DETECTED`, `LIVE`).

**Result (Nov 7, on-device, no laptop):** khabar 84.8 %, shahajjo 85.2 %,
salam 72.3 %, ami 82.8 %, dhonnobad 84.4 %, pani 91.8 % — and every
accidental twitch correctly classified as idle. Inference: **42 ms**.

---

## Phase 6 — Toolchain clean-up

| Problem | Fix |
|---|---|
| Two PlatformIO installations (an old pip one in `/usr/local` and pioarduino in `~/.platformio/penv`); uploads failed with `No module named 'littlefs'` | Removed the old install; pioarduino is the only core |
| The GitHub `esp-tflite-micro` library failed to compile (`kiss_fft.c` missing, duplicate kernels, `Register_IRFFT` namespace conflicts) | It was a **second copy** of TFLite-Micro next to the one already bundled with the Arduino-ESP32 framework. Removed it from `lib_deps`; the framework's precompiled copy (with esp-nn) is used |

Every issue and its fix is collected in [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

---

## Phase 7 — Bangla on the OLED

1. **Library:** [mamunul/BanglaText](https://github.com/mamunul/BanglaText)
   (MIT) renders Unicode Bangla with proper conjuncts using a pre-built
   font header (`BanglaMNRegular_25pt.h`).
2. **Second I²C bus:** the OLED runs on `Wire1` so screen updates never
   delay the 100 Hz sensor reads on `Wire`. Pins moved from 19/20 (the
   S3's native-USB pins) to **41/42**.
3. **Blank screen:** an I²C scan plus a hello-world sketch showed the
   OLED answering on 0x3C, and a "force-on" test (charge pump on,
   maximum contrast, full-white fill) isolated the panel from the rest
   of the firmware. Once the panel lit up, the full firmware displayed
   correctly. An I²C scan followed by a minimal "fill the screen" test is
   the recommended first step for any new display.
4. **Sideways text:** the renderer lays words out along the Y axis.
   Each word is now drawn into an off-screen canvas, its bounding box is
   measured, and it is copied to the screen **rotated 270°** and centred.
   English header/footer text is unaffected.
5. **Half-cut long words:** host-side measurement showed ধন্যবাদ needs
   73 px and লিখছেন 81 px along the canvas Y axis, but the canvas was
   only 64 px tall. Changing the canvas from 192×64 to **40×128** fixed
   it — no smaller font needed, and it uses less RAM.

---

## Phase 8 — Voice output

1. Each word was recorded on a phone in the author's own voice (`.aac`).
2. `python/prepare_audio.py` decodes, trims silence, normalises loudness
   and encodes 44.1 kHz mono MP3 named `0001.mp3`–`0007.mp3` — the
   number equals the model's class id.
3. The SD card (FAT32, MBR) holds them in `/mp3/`; macOS hidden files
   are removed so the DFPlayer only sees the real tracks.
4. **Phase 1 test:** a DFPlayer-only sketch played all 7 files.
5. **Integration:** `audio.h/.cpp` module; the inference task speaks
   confident results; the cooldown waits for the BUSY pin so arm
   movement during playback cannot trigger a false capture.

---

## Phase 9 — The boot-orientation finding

After integration, a test session produced no detections at all
(best: khabar 57 %). The boot log showed accelerometer offsets of
`-0.109, -0.401, -0.939` — the board had been reset while upside-down.
Calibration subtracts gravity measured at boot, so every accelerometer
reading was shifted by almost 2 g relative to the training data.
Booting flat and face-up restores normal behaviour. A permanent fix
(fixed accelerometer offset, gyro-only calibration) is listed in
[`FUTURE_WORK.md`](FUTURE_WORK.md).

---

## Lessons learned

1. **Consistency beats cleverness.** Uniform 6 s samples did more for
   accuracy than any augmentation or padding trick.
2. **Match training and live conditions exactly** — alignment (motion
   trigger), padding (zeros), filtering and boot orientation.
3. **Pick words with distinctive motion.** Long, signature-like words
   are robust; short words and words that share strokes are not.
4. **Measure before redesigning.** The cut-off Bangla words were a
   buffer-size bug, not a font-size problem.
5. **Test each subsystem alone** (OLED hello world, DFPlayer-only
   sketch) before integrating — it isolates wiring from software.
6. **One copy of each library.** Duplicate SDKs cause confusing errors.

---

## Reproducing the project from scratch

| Step | Guide |
|---|---|
| 1. Buy parts and wire them | [`hardware/BOM.md`](../hardware/BOM.md), [`hardware/WIRING.md`](../hardware/WIRING.md) |
| 2. Install the tools | [`SETUP.md`](SETUP.md) |
| 3. Record gesture data | [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md) |
| 4. Train the model | [`TRAINING.md`](TRAINING.md) |
| 5. Prepare voice files and the SD card | [`AUDIO_AND_DISPLAY.md`](AUDIO_AND_DISPLAY.md) |
| 6. Flash the wearable | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| 7. Add your own words | [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md) |
| If something breaks | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
