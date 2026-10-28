# SANKET — Gesture Design Guide

How to add **new Bangla words** to the model so SANKET can recognize them.

## 1. Why this guide exists

The current model recognizes `ami` + `idle`. SANKET is extensible — you can
add any Bangla word (or any air-gesture) by:

1. Designing a motion for it,
2. Collecting ~45 samples,
3. Retraining,
4. Reflashing.

This guide covers how to **design** a good gesture so the model can learn
it well.

## 2. Gesture-design rules of thumb

### ✅ Make it short (2 – 4 seconds)

Fits inside the 6-second window with still-time at the end. Longer gestures
compress badly; shorter gestures leave more rest-time that the model has to
learn to ignore.

### ✅ Make it one continuous sweep (connected, not letter-by-letter)

Write the Bangla word like a cursive signature. One flowing motion.
Pros:
- More distinct from random hand movements
- Easier to repeat consistently
- Clear start and clear end

Letter-by-letter writing produces lots of brief pauses that look similar
across different words, making the model confuse them.

### ✅ Make it visually distinct from existing gestures

If two words have very similar motions, the model will confuse them.
Before committing to a gesture, do it slowly in air a few times and ask
yourself: *"Does this feel genuinely different from the words I already
have?"*

### ✅ Use the full wrist — rotation + translation

The MPU6050 captures both acceleration (translation) and angular velocity
(rotation). A gesture that uses both is much easier to recognize than a
one-axis motion (e.g. "straight up-down" is harder than "a diagonal curve
plus a twist").

### ✅ Starts and ends from rest

Begin with your wrist still. Make the gesture. Hold still at the end.
Gives the model clear boundary cues.

### ✅ Not easily triggered accidentally

Think about ambient wrist movements: picking up a cup, scratching your
head, waving hello. If your gesture resembles one of those, you'll get
false positives.

### ⚠️ Avoid these pitfalls

| Pitfall | Why bad |
|---|---|
| Very short gestures (<1 s) | Hard to distinguish from random bumps |
| Very long gestures (>5 s) | Gets cut by the 6 s window |
| Symmetric motions ("left-right-left-right") | Hard for the model to find a direction |
| Pure linear slides | Low gyro signal — IMU underused |
| Gestures that look like your target population's common movements | False positives in daily use |

## 3. Recommended first set of 10 Bangla words

A survival-oriented word set for Deaf-aid use:

| # | Bangla | Roman | Meaning | Suggested motion |
|---|---|---|---|---|
| 1 | **আমি** | ami | I | ✅ already trained |
| 2 | **তুমি** | tumi | you | signature-style sweep of তুমি |
| 3 | **হ্যাঁ** | haan | yes | nodding-like up-down + small twist |
| 4 | **না** | na | no | horizontal zigzag (shaking "no") |
| 5 | **ধন্যবাদ** | dhonnobad | thank you | large curve from heart outward |
| 6 | **পানি** | pani | water | drinking motion — tip wrist forward |
| 7 | **খাবার** | khabar | food | spoon-to-mouth motion |
| 8 | **সাহায্য** | shahajjo | help | wave-up (asking) |
| 9 | **ডাক্তার** | daktar | doctor | air-writing ড-কার |
| 10 | **ভালো** | bhalo | good / OK | thumbs-up motion + outward |

Idle (random / rest) is always the 11th class.

> Feel free to pick different motions. The ones above are starting points —
> what matters is consistency inside each class.

## 4. Workflow: adding word #N to the trained model

### Step 1 — register the label in Python

Edit `python/collector.py`:
```python
LABELS = [
    {"id": 0, "name": "ami",  "bangla": "আমি (air-written)", "target": True},
    {"id": 1, "name": "idle", "bangla": "(random / rest)",   "target": False},
    # add here:
    {"id": 2, "name": "tumi", "bangla": "তুমি (air-written)", "target": True},
]
```

Edit `python/train.py` the same way:
```python
LABELS = [
    {"id": 0, "name": "idle", "bangla": "(idle)"},
    {"id": 1, "name": "ami",  "bangla": "আমি"},
    {"id": 2, "name": "tumi", "bangla": "তুমি"},
]
```

> The two files use slightly different label orders — that's fine. Each
> normalizes to its own `id` space.

### Step 2 — collect 45 samples

Open the collector, set Label = "tumi", and go through:

```
Position P1 × Styles S1,S2,S3 × 5 reps each = 15 samples
Position P2 × Styles S1,S2,S3 × 5 reps each = 15 samples
Position P3 × Styles S1,S2,S3 × 5 reps each = 15 samples
                                      Total = 45 samples
```

See [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md) for the full
protocol.

### Step 3 — retrain

```bash
cd python
source .venv/bin/activate
python train.py
```

`train.py` auto-discovers every class folder under `data/`. You don't
need to tell it there's a new one.

### Step 4 — update the firmware's class list

Open `firmware_infer/src/model_norm.h` and update:
```cpp
constexpr int   MODEL_CLASSES = 3;        // was 2
constexpr const char* MODEL_CLASS_NAMES[MODEL_CLASSES] = {
    "idle",
    "ami",
    "tumi",     // NEW
};
```

> The order must match `python/models/labels.json` after training.

### Step 5 — update `MODEL_MU` / `MODEL_SD` if changed

Open `python/models/norm.json`, copy the `mu` and `sd` arrays into
`firmware_infer/src/model_norm.h`.

### Step 6 — copy the new C header + reflash

```bash
cp python/models/model_data.h  firmware_infer/src/model_data.h
cd firmware_infer
pio run -t upload
```

### Step 7 — verify

```bash
pio device monitor --baud 921600
```

Air-write তুমি → should see `P,tumi,0.9x` and `DETECTED,tumi,0.9x`.

## 5. Scaling tips

| Vocabulary size | What to watch |
|---|---|
| 2 classes (current) | Trivial — any model trains perfectly |
| 5 classes | Still easy; 15–20 samples/class is plenty |
| 10 classes | Need the full P × S × 5 protocol per word; collect in sessions, not one marathon |
| 20+ classes | Model capacity becomes relevant. Consider growing Conv1D filters: 16 → 24, 32 → 48, 48 → 64 |
| 50+ classes | Model stays well under 100 KB. Flash is nowhere near full on the ESP32-S3 (6 MB free). |

## 6. If a new word is being confused with an existing one

1. **Collect more varied samples** for both — different Positions and Styles.
2. **Redesign the motion** so it's more different (if ami is a sweeping arc, don't make tumi also a sweeping arc).
3. **Check for leakage** — look at your `.npz` files in a plot; if two classes' plots look similar, the gestures are too similar.
