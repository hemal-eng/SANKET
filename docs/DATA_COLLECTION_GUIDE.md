# SANKET — Data Collection Guide

How to collect clean, uniform gesture samples for training.

## 1. Prerequisites

- MPU6050 wired per [`../hardware/WIRING.md`](../hardware/WIRING.md)
  (GPIO 8 = SDA, GPIO 9 = SCL).
- Python environment set up per [`SETUP.md`](SETUP.md).
- **Data-logger firmware** (`firmware/`, v6) flashed:
  ```bash
  cd firmware
  pio run -t upload
  ```
  The logger streams at **921600 baud** and accepts the one-shot command
  `T<N>` (record exactly N samples). Details:
  [`../firmware/README.md`](../firmware/README.md).

## 2. Launch the collector GUI

```bash
cd python
.venv/bin/python collector.py
```

To stop it, close the window (or `pkill -f collector.py` from a terminal).

The window shows:

1. **Port** dropdown — ESP32 USB-UART bridges (CH34x / CP210x) are listed
   first; Bluetooth ports are pushed to the bottom
2. **Label** — the word being recorded (fixed English names, no Bangla typing needed)
3. **Position** — P1 / P2 / P3 (arm position)
4. **Style** — S1 normal / S2 slow-careful / S3 quick-sloppy
5. **Duration** — `🔒 6 s (locked — uniform dataset)`
6. **Session panel** (scrollable) — counter grid of samples per
   label × position × style
7. **Big record button + SPACE** — fires one 6-second recording
8. **Live plots** — accelerometer (g) and gyroscope (°/s)
9. **Preview** — after each recording; **S** = save, **R** = redo

The window is resizable and the session panel scrolls, so it fits small
laptop screens.

## 3. Why every sample is exactly 6.0 s

Every sample is **600 samples @ 100 Hz = 6.000 s**. The duration is locked
in `collector.py` (`FIXED_DURATION_S = 6.0`), and the GUI sends `T600` to the
logger.

Earlier versions let each word use its own duration (2–20 s). That produced
samples of different lengths, which then had to be zero-padded to the longest
one. The padding did not match what the device sees live, and accuracy on the
short words dropped. The first smoke test (`ami` vs `idle`) used fixed 6-second
samples and reached 100 %, so the whole dataset was re-collected at a fixed
6 s. A uniform dataset needs no tricks at training time.

## 4. The recording protocol — exact sequence

```
┌───────────────────────────────────────────────────────────────┐
│  BEFORE EACH SAMPLE                                            │
│  1. Set Label (e.g. "pani")                                    │
│  2. Set Position (P1 / P2 / P3)                                │
│  3. Set Style   (S1 / S2 / S3)                                 │
│  4. Click the GUI window so SPACE goes to it                   │
│  5. Hold your wrist still, ready to start                      │
│                                                                 │
│  RECORDING                                                      │
│  6. Press SPACE          ← status turns red "● RECORDING…"     │
│  7. Air-write the word   ← full connected sweep, like a        │
│                            signature, usually 1–4 s            │
│  8. Hold still            ← until the 6 s mark                  │
│  9. Device auto-stops    ← preview appears                     │
│                                                                 │
│  AFTER                                                          │
│ 10. Check the plot        ← does it look like the others?      │
│ 11. S = save, R = redo                                         │
│ 12. Change Position or Style for the next batch                │
└───────────────────────────────────────────────────────────────┘
```

**Idle samples:** move your hand naturally for the **full 6 seconds** —
scratching your head, picking up a cup, resting, waving — anything that is
**not** one of the words. Idle is the model's "reject" class.

## 5. The sampling plan

```
Per word:  3 Positions × 3 Styles × 5+ reps  =  45+ samples
```

| Position | Where your wrist is |
|---|---|
| **P1** | Neutral — in front of the body at waist height |
| **P2** | Raised — shoulder/head height |
| **P3** | Low / resting — near the hip or on a table edge |

| Style | How you write the word |
|---|---|
| **S1 — normal** | Natural pace, how you'd write it in real life |
| **S2 — slow-careful** | Deliberate, exaggerated |
| **S3 — quick-sloppy** | Fast, messy, in a hurry |

> Keep the shape consistent inside each style. All S1 reps should look
> alike; S2 is the same shape, just slower.

Collect extra samples for any word that gets confused at test time. That is
how the current dataset grew past 45 per word.

## 6. Current dataset

All samples are 6.0 s. Total **778** samples:

| Class | Bangla | Samples |
|---|---|---:|
| idle | (rest / random) | 129 |
| ami | আমি | 90 |
| haan | হ্যাঁ | 79 |
| dhonnobad | ধন্যবাদ | 72 |
| pani | পানি | 114 |
| khabar | খাবার | 108 |
| shahajjo | সাহায্য | 84 |
| salam | সালাম (আস-সালামু আলাইকুম) | 102 |
| **Total** | | **778** |

Count your own data at any time:

```bash
cd python
for d in data/*/; do echo "$(basename $d) $(ls $d*.npz 2>/dev/null | wc -l)"; done
```

Removed or retired classes (tumi, na, and the old variable-duration
recordings) are kept in `data/_archive_variable_duration/`, which the trainer
ignores. Nothing was deleted.

## 7. File naming and storage

```
python/data/<label>/pos<P>_style<S>_rep<NNN>.npz
```

Example:
```
python/data/pani/pos1_style1_rep001.npz
python/data/pani/pos1_style2_rep004.npz
python/data/idle/pos2_style1_rep012.npz
```

Each `.npz` contains:

| Key | Type | Meaning |
|---|---|---|
| `data` | float32 (600, 6) | ax, ay, az in g; gx, gy, gz in °/s (IIR-filtered) |
| `label` | str | English name, e.g. `pani` |
| `label_bangla` | str | Bangla text |
| `position` | int | 1 / 2 / 3 |
| `style` | int | 1 / 2 / 3 |
| `sample_rate_hz` | int | 100 |
| `duration_s` | float | 6.00 |
| `peak_a`, `peak_g` | float | signal strength |
| `quality` | str | GUI tag |
| `timestamp_iso` | str | UTC ISO-8601 timestamp |

> `python/data/` is personal and large — `.gitignore` keeps it out of git.

## 8. Deleting a bad sample

If you saved a sample by mistake, delete the newest file in that word's folder:

```bash
cd python/data/pani
ls -t *.npz | head -1                 # shows the newest file
rm "$(ls -t *.npz | head -1)"         # deletes it
```

Restart the collector afterwards so its counters refresh.

## 9. Tips for clean data

| Do | Don't |
|---|---|
| Wear the board on the **same spot and orientation** every session | Rotate or flip the board between sessions |
| Power on / calibrate with the board **flat, face-up** | Calibrate in a random pose — the offsets are subtracted from every reading |
| Keep the USB cable loose | Let the cable tug the board mid-gesture |
| Record in sets of 5 (one style × one position) | Mix styles randomly |
| Redo anything that felt off | Save messy samples hoping the model copes |
| Keep idle about the size of the biggest word class | Skip idle — the model then has no "nothing" answer |

See [`TRAINING.md`](TRAINING.md) for the next step.
