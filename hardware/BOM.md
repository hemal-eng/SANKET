# SANKET — Bill of Materials

Everything needed to build the current SANKET device: motion sensing,
on-chip recognition, a Bangla text display and spoken audio output.

## 1. Core parts

| # | Component | Qty | Approx price (BDT) | Approx price (USD) | Notes |
|---|---|---|---|---|---|
| 1 | ESP32-S3-DevKitC-1 **N16R8** (dual-USB, black board) | 1 | ৳550 | $5.00 | 16 MB flash, 8 MB PSRAM, dual-core 240 MHz |
| 2 | MPU6050 6-axis IMU breakout (GY-521 or clone) | 1 | ৳100 | $1.00 | I²C address 0x68 |
| 3 | SSD1306 0.96" 128×64 I²C OLED | 1 | ৳250 | $2.50 | I²C address **0x3C**, 4-pin (GND, VCC, SCL, SDA) |
| 4 | DFPlayer Mini MP3 module | 1 | ৳180 | $1.80 | Plays MP3s from microSD, 3 W mono amplifier built in |
| 5 | Speaker, 3 W, 4–8 Ω | 1 | ৳80 | $0.80 | Small round or oval speaker |
| 6 | microSD card, 16 GB | 1 | ৳350 | $3.50 | Formatted FAT32 / MBR. Any card **≤ 32 GB** works |
| 7 | Resistor, 1 kΩ | 1 | ৳2 | $0.02 | In series with the DFPlayer RX line (removes buzz) |
| 8 | Electrolytic capacitor, 100–470 µF (≥ 10 V) | 1 | ৳10 | $0.10 | Across DFPlayer VCC/GND (stops resets and clicks) |
| 9 | Breadboard + jumper wires (M-M, F-F) | 1 set | ৳150 | $1.50 | For prototyping |
| 10 | USB cable (USB-C / Micro-USB to match the board) | 1 | — | — | Most users already own one |
| | **Total** | | **≈ ৳1,670** | **≈ $16** | |

Prices are typical retail in Bangladesh (TechShop BD, Daraz) and
AliExpress/Amazon equivalents. Clone modules work fine.

## 2. What each part does

| Part | Role in the system |
|---|---|
| ESP32-S3 | Samples the IMU at 100 Hz, runs the INT8 neural network on-chip, drives the display and audio |
| MPU6050 | Measures wrist motion: 3-axis accelerometer (±4 g) + 3-axis gyroscope (±500 °/s) |
| SSD1306 OLED | Shows the detected word in Bangla script plus status text |
| DFPlayer Mini + speaker | Speaks the detected word aloud from a recorded MP3 |
| microSD card | Holds the 7 word recordings (`/mp3/0001.mp3` … `0007.mp3`) |
| 1 kΩ resistor | Limits current and noise on the 3.3 V → DFPlayer serial line |
| 100–470 µF capacitor | Buffers the DFPlayer's current spikes when the speaker plays |

## 3. Why so cheap

SANKET is designed as a **low-cost deaf-aid**:

- The ESP32-S3 is a ~$5 chip with a vector instruction set (esp-nn) that
  accelerates INT8 neural networks — no phone, cloud or internet needed.
- The MPU6050 is the cheapest 6-axis IMU available; clone boards work with
  SANKET's DLPF + boot calibration + IIR filter pipeline.
- No glove, no camera, no subscription — nothing recurring, nothing that
  invades privacy.

## 4. Current form factor

The prototype sits on the wrist (Velcro strap or tape), with the MPU6050
flat on top of the board. The OLED faces the user, and the DFPlayer +
speaker can sit on a small breadboard next to it. For a finished wearable
all parts could move onto one custom PCB the size of a wristwatch.

## 5. Not yet built (future additions)

These are **planned, not part of the current build**:

| Part | Purpose |
|---|---|
| 3.7 V LiPo cell (500–1000 mAh) or 18650 cell | Battery power |
| TP4056 charger module (with protection) | Safe USB charging of the cell |
| 3.3 V / 5 V boost or buck regulator | Supply rails from the battery |
| 3D-printed wrist enclosure + strap | Wearable housing |

See [`../docs/FUTURE_WORK.md`](../docs/FUTURE_WORK.md).
