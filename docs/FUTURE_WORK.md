# SANKET — Future Work

Planned extensions. Not implemented yet — this document is a roadmap.

## 1. Audio output (voice for the Deaf)

The headline next step. A **DFPlayer Mini + small speaker** will be added
so that when the device detects a word, it plays a pre-recorded Bangla
audio clip of that word — turning the Deaf user's silent gestures into
audible speech for hearing people around them.

Rough plan:
- UART1 (TX = GPIO 17, RX = GPIO 18) to the DFPlayer Mini.
- MicroSD on the DFPlayer carries `0001.mp3` through `000N.mp3`,
  one per class, recorded in Bangla.
- Firmware: when `DETECTED,<word>,<conf>` fires, send a UART play
  command for the matching file index.

## 2. On-wrist OLED

Add an SSD1306 128×64 OLED (I²C) on the same bus as the MPU6050 so the
device also **displays** the detected Bangla word (useful when the
environment is too loud for the speaker, or the hearer is also Deaf).

Bangla font rendering is handled by Mamunul Mazid's **BanglaText**
library (pre-generated font headers already downloaded in parent
project).

## 3. Larger vocabulary

Expand from 2 classes to **10+ essential survival words**:

> আমি, তুমি, হ্যাঁ, না, ধন্যবাদ, পানি, খাবার, সাহায্য, ডাক্তার, ভালো

See [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md) for the recipe.
Model stays well under 50 KB even at 20 classes.

## 4. Battery + enclosure (wearable form factor)

- 18650 Li-ion cell (3.7 V, 2500 mAh)
- TP4056 charging module
- MP1584 or similar buck converter down to 3.3 V
- 3D-printed wrist strap enclosure

Target: 24 h continuous runtime on a charge (ESP32-S3 light-sleep between
inferences could push this to a week).

## 5. Multi-user adaptation

Current dataset is one user's handwriting style. For a product:

- Collect data from 10+ Deaf volunteers per word.
- Add per-user calibration (user writes 2–3 reps on first boot; model is
  fine-tuned on-chip).
- Explore federated learning so users' data never leaves their device.

## 6. BLE / Wi-Fi companion app

- Pair SANKET to a phone via BLE.
- Phone app shows the live transcript, speaks words aloud via its own
  TTS, logs conversations.
- Pure-local option: no cloud, no privacy exposure.

## 7. Alternative input modalities

- **EMG sensor** (muscle signals) in addition to IMU — differentiates
  intent-to-write from random motion more cleanly.
- **Flex sensors** for finger shapes — enables full BdSL (Bangla Sign
  Language), not just air-writing.

## 8. Research directions

- Compare quantized 1D-CNN vs TinyTransformer vs 1D-TCN on the same
  Bangla air-writing task.
- Dataset release: publish an open Bangla air-writing dataset for
  reproducibility.
- Benchmark INT8 inference latency across ESP32-C3 / S3 / P4 using
  esp-nn vs. generic kernels.
