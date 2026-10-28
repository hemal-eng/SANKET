# SANKET — Data Collection Guide

How to collect clean gesture samples for training.

## 1. Prerequisites

- Hardware wired per [`../hardware/WIRING.md`](../hardware/WIRING.md).
- Python environment set up per [`SETUP.md`](SETUP.md).
- Data-logger firmware flashed:
  ```bash
  cd firmware
  pio run -t upload
  ```

## 2. Launch the collector GUI

```bash
cd python
source .venv/bin/activate            # Windows: .venv\Scripts\activate
python collector.py
```

A window opens with:

1. **Port** dropdown → pick the ESP32-S3 serial device
2. **Label** dropdown → the Bangla word being recorded (hard-coded list)
3. **Position** radio → P1 / P2 / P3 (arm position)
4. **Style** radio → S1 (normal) / S2 (slow-careful) / S3 (quick-sloppy)
5. **Counter row** → shows how many samples per (label, position, style) you already have
6. **Big green button + SPACE shortcut** → fires one 6-second one-shot recording
7. **Live plots** → accel (g) and gyro (°/s)
8. **Preview panel** → appears after a recording with duration + peak metrics
9. **Save (S) / Redo (R)** → keyboard shortcuts for the preview

## 3. The recording protocol — THE EXACT SEQUENCE

For **every single sample** you record, follow this:

```
┌───────────────────────────────────────────────────────────────┐
│  BEFORE EACH SAMPLE                                            │
│  1. Set Label (e.g. "ami")                                     │
│  2. Set Position (P1 / P2 / P3)                                │
│  3. Set Style   (S1 / S2 / S3)                                 │
│  4. Click the GUI window so SPACE goes to it                   │
│  5. Hold your wrist still, ready to start                      │
│                                                                 │
│  RECORDING                                                      │
│  6. Press SPACE          ← status flips to red "● RECORDING…"  │
│  7. Air-write the word   ← full connected sweep, ~3–4 seconds  │
│  8. Hold still            ← device keeps sampling to 6 s mark   │
│  9. Device auto-stops    ← preview appears                     │
│                                                                 │
│  AFTER                                                          │
│ 10. Look at the plot      ← does it look like other samples?    │
│ 11. Press S to save, or R to redo if it was messy              │
│ 12. Change Position or Style for the NEXT batch of 5           │
└───────────────────────────────────────────────────────────────┘
```

### How the firmware actually works
- Press SPACE → GUI sends `T\n` over serial.
- Firmware ignores anything until the one-shot completes (so a stray tap can't
  stop it mid-gesture).
- Firmware captures **exactly 600 samples @ 100 Hz = 6.000 s**, then stops.
- GUI receives samples, builds the preview, offers Save / Redo.

### Why 6 seconds?
A deliberate air-written word takes 2–4 seconds. The 6-second window gives:
- Breathing room if you pause mid-gesture to think,
- Flexibility for slow vs fast writers,
- Still-time at the end that the model learns to ignore.

## 4. The sampling plan (per Bangla word)

The dataset structure that produced our 100 % smoke-test result:

```
Per word:  3 Positions × 3 Styles × 5 reps = 45 samples
```

| Position | Where your wrist is |
|---|---|
| **P1** | Natural / neutral — in front of body at waist height |
| **P2** | Raised — shoulder/head height (gesturing at someone) |
| **P3** | Low / resting — hand near hip or on table edge |

| Style | How you write the word |
|---|---|
| **S1 — normal** | Natural pace, how you'd write it in real life |
| **S2 — slow-careful** | Deliberate, exaggerated, pauses between letters allowed |
| **S3 — quick-sloppy** | Fast, messy, abbreviated — like you're in a hurry |

> **Keep the shape consistent inside each style.** All 5 reps of S1 should
> look alike; all 5 of S2 should look alike (just slower); etc.

### Idle class

Record **~30–50 idle samples** per user. Random hand movements, resting the
wrist, picking up a cup, scratching your head — anything that's NOT the
target word. Spread across P1/P2/P3. These are the "reject" class.

> Idle doesn't need a style — all idle samples go under `data/idle/`.

## 5. File naming and storage

Samples are saved as:
```
python/data/<label>/pos<P>_style<S>_rep<NNN>.npz
```

Example:
```
python/data/ami/pos1_style1_rep001.npz
python/data/ami/pos1_style1_rep002.npz
...
python/data/idle/pos1_rep001.npz
```

Each `.npz` carries:

| Key | Type | Meaning |
|---|---|---|
| `data` | float32 (600, 6) | ax, ay, az in g; gx, gy, gz in °/s |
| `label` | str | English name, e.g. "ami" |
| `label_bangla` | str | Bangla text, e.g. "আমি (air-written)" |
| `position` | int | 1 / 2 / 3 |
| `style` | int | 1 / 2 / 3 |
| `sample_rate_hz` | int | 100 |
| `duration_s` | float | should be ~6.00 |
| `peak_a`, `peak_g` | float | signal strength |
| `quality` | str | GUI auto-tag |
| `timestamp_iso` | str | UTC ISO-8601 timestamp |

> **Keep `python/data/` out of git** — it's user-personal and large.
> `.gitignore` already excludes it.

## 6. Tips for clean data

| Do | Don't |
|---|---|
| Wear the dev board on the **same spot** on your wrist for every sample | Rotate the board between samples (changes the IMU axes relative to the gesture) |
| Keep the USB cable loose so it doesn't tug your arm | Let the cable yank the board mid-gesture |
| Pause between samples (deep breath, reset posture) | Rush — fatigue bleeds consistency |
| Collect in sets of 5 (one style × one position) | Mix styles randomly — you'll forget which was which |
| Redo any sample that felt off (phone rang, elbow bumped) | Save messy samples hoping the model "will figure it out" |
| Collect 20–30 % idle samples total | Only collect target words (model has no "no" class) |

## 7. What the model expects

For good classification you want:
- **Minimum ~15 samples per class** (we achieved 100 % val with 45 ami + 89 idle)
- **Diverse Positions and Styles** inside each class
- **An "idle" / rest class** that's at least as big as the smallest target class

See [`TRAINING.md`](TRAINING.md) for what happens next.
