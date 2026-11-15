# SANKET — Wiring Guide

Complete wiring for the current device: MPU6050 (motion), SSD1306 OLED
(Bangla display) and DFPlayer Mini (spoken audio), all on one
ESP32-S3-DevKitC-1 N16R8.

## 1. Master pin table

| Device | Device pin | ESP32-S3 pin | Bus / function |
|---|---|---|---|
| **MPU6050** | SDA | **GPIO 8** | I²C bus 0 (`Wire`), 400 kHz |
| | SCL | **GPIO 9** | I²C bus 0 (`Wire`) |
| | VCC | 3V3 | 3.3 V |
| | GND | GND | ground |
| **SSD1306 OLED** | SDA | **GPIO 41** | I²C bus 1 (`Wire1`), 400 kHz, addr 0x3C |
| | SCL | **GPIO 42** | I²C bus 1 (`Wire1`) |
| | VCC | 3V3 | 3.3 V |
| | GND | GND | ground |
| **DFPlayer Mini** | RX | **GPIO 17** (TX) **via 1 kΩ** | UART2, 9600 baud |
| | TX | **GPIO 18** (RX) | UART2 |
| | BUSY | **GPIO 16** | LOW while playing |
| | VCC | **5V** | 5 V (from USB) |
| | GND | GND | ground |
| | SPK_1, SPK_2 | — | speaker (3 W, 4–8 Ω) |

All grounds are connected together (common ground).

> **OLED pin history:** during early display tests the OLED was on
> GPIO 19/20. Those two pins are the ESP32-S3's **native USB D− / D+**
> lines, so the firmware now uses **GPIO 41 / 42**, which are free
> general-purpose pins. `firmware_infer/src/main.cpp` uses 41/42.

## 2. Wiring diagram

```
                       ESP32-S3-DevKitC-1 (N16R8)
                  ┌───────────────────────────────────┐
                  │  [UART USB port — use this one]   │
                  │                                   │
  MPU6050         │                                   │
  ┌────────┐      │                                   │
  │ VCC ◀──┼──────┤ 3V3                               │
  │ GND ◀──┼──────┤ GND                               │
  │ SDA ◀──┼──────┤ GPIO 8                            │
  │ SCL ◀──┼──────┤ GPIO 9                            │
  └────────┘      │                                   │
                  │                                   │
  SSD1306 OLED    │                                   │
  ┌────────┐      │                                   │
  │ VCC ◀──┼──────┤ 3V3                               │
  │ GND ◀──┼──────┤ GND                               │
  │ SDA ◀──┼──────┤ GPIO 41                           │
  │ SCL ◀──┼──────┤ GPIO 42                           │
  └────────┘      │                                   │
                  │                                   │
  DFPlayer Mini   │                                   │
  ┌──────────┐    │                                   │
  │ VCC  ◀───┼────┤ 5V ──────┬────────┐               │
  │ GND  ◀───┼────┤ GND ─────┼──┐     │               │
  │ RX   ◀───┼─[1kΩ]─────────┼──┼─────┤ GPIO 17 (TX)  │
  │ TX   ────┼───────────────┼──┼────▶│ GPIO 18 (RX)  │
  │ BUSY ────┼───────────────┼──┼────▶│ GPIO 16       │
  │ SPK_1 ───┼──┐            │  │     └───────────────┘
  │ SPK_2 ───┼─┐│          ┌─┴──┴─┐
  └──────────┘ ││          │ 100–470 µF  (+ to 5V, − to GND,
               ││          └──────┘      placed close to DFPlayer)
             ┌─┴┴─┐
             │SPKR│  3 W, 4–8 Ω
             └────┘
```

## 3. DFPlayer rules (important)

| Rule | Why |
|---|---|
| Power the DFPlayer from **5V**, not 3V3 | It draws current spikes while playing; on 3.3 V it browns out and resets |
| Put a **100–470 µF** capacitor across VCC/GND, close to the module | Prevents clicks, pops and random resets |
| Put a **1 kΩ resistor** in the ESP32 TX → DFPlayer RX line | Removes the buzzing noise in the speaker |
| Connect the speaker **only to SPK_1 and SPK_2** | Never connect either speaker wire to GND — it destroys the on-board amplifier |
| microSD card formatted **FAT32 / MBR**, files in `/mp3/` | See [`../docs/AUDIO_AND_DISPLAY.md`](../docs/AUDIO_AND_DISPLAY.md) |

## 4. Power budget

| Load | Rail | Typical current |
|---|---|---|
| ESP32-S3 (both cores active) | 3V3 (on-board LDO) | ~100–150 mA |
| MPU6050 | 3V3 | ~4 mA |
| SSD1306 OLED | 3V3 | ~10–20 mA (depends on lit pixels) |
| DFPlayer Mini idle | 5V | ~20 mA |
| DFPlayer Mini playing (3 W speaker) | 5V | ~200–500 mA peaks |
| **Total** | USB 5V | **≈ 0.4–0.7 A peak** |

A normal computer USB port or a 5 V / 1 A adapter is enough. The on-board
3.3 V LDO only supplies the ESP32, MPU6050 and OLED (well under its limit);
the DFPlayer is fed directly from 5 V.

## 5. Pins to avoid on the N16R8

| Pins | Reason |
|---|---|
| GPIO 43 / 44 | UART0 — the USB serial monitor |
| GPIO 26–37 | Connected to the internal flash and octal PSRAM on N16R8 |
| GPIO 19 / 20 | Native USB D− / D+ |
| GPIO 0, 3, 45, 46 | Strapping pins (boot mode) — avoid for peripherals |

## 6. Notes

### Use the UART USB port

The dual-USB board has two ports. Use the **UART** port (CH343/CP2102
USB-serial bridge). On macOS it appears as `/dev/cu.wchusbserial…`. The
native USB-OTG port is not used by SANKET firmware.

### I²C addresses and pull-ups

- MPU6050: **0x68** (AD0 to GND). If your board is jumpered to 0x69,
  change `MPU_ADDR` in the firmware.
- SSD1306: **0x3C**. Some 128×64 panels use 0x3D.
- Both breakout boards include their own pull-up resistors — no external
  pull-ups needed. MPU6050 and OLED are on **separate** I²C buses, so
  they never conflict.

## 7. Mounting on the wrist

1. Place the ESP32-S3 flat on the back of the wrist.
2. Fix the MPU6050 flat on top of (or beside) it so its axes never move
   relative to the wrist.
3. Secure with a Velcro strap or soft cloth band.
4. Keep the USB cable loose so it does not tug mid-gesture.

> ⚠️ **Keep the MPU6050 orientation identical** between data collection
> and real use. The model learns each word as seen from that orientation.

## 8. ⚠️ CRITICAL — power on flat, face-up and still

At every power-on (or RST press) the firmware runs a **2-second
calibration** and subtracts the measured accelerometer and gyroscope
offsets from every later reading. That offset **includes gravity** in
whatever position the board is in at that moment.

All training data was recorded with the board calibrated **flat and
face-up**. If the device boots tilted or upside-down, every accelerometer
reading is shifted by up to ~2 g compared with training, and recognition
confidence collapses.

| Boot position | Calibration offsets (ax, ay, az in g) | Result |
|---|---|---|
| Flat, face-up | `0.015, -0.162, 0.970` | Words detected at 82–92 % |
| Tilted / upside-down | `-0.109, -0.401, -0.939` | **No detections** (everything classified as idle) |

**Always:** lay the device flat and face-up, power on (or press RST), and
keep it completely still for ~3 seconds until the ready screen appears.
Check the serial line `C,DONE,…`: the third value (az) should be close to
**+0.97**.
