# SANKET — Gesture Design Guide

Which Bangla words SANKET recognises, why these words were chosen, and how
to add new ones.

## 1. The current word set (7 words + idle)

| id | Word | Meaning | How it is made | Voice file |
|---:|---|---|---|---|
| 1 | **আমি** (ami) | I / me | air-written word, connected like a signature | `0001.mp3` |
| 2 | **হ্যাঁ** (haan) | yes | air-written word | `0002.mp3` |
| 3 | **ধন্যবাদ** (dhonnobad) | thank you | long air-written word | `0003.mp3` |
| 4 | **পানি** (pani) | water | air-written word | `0004.mp3` |
| 5 | **খাবার** (khabar) | food | gesture-style signature motion | `0005.mp3` |
| 6 | **সাহায্য** (shahajjo) | help | gesture-style signature motion | `0006.mp3` |
| 7 | **সালাম** (salam) | greeting — spoken as **আস-সালামু আলাইকুম** | gesture-style signature motion | `0007.mp3` |
| 0 | idle | (nothing) | everyday hand movement / rest | silent |

The set focuses on daily survival needs (water, food, help), courtesy
(thank you, greeting) and short answers (I, yes).

## 2. How the set evolved — and why

| Word | Decision | Reason |
|---|---|---|
| **তুমি (tumi)** | removed | Its ending strokes and আমি's opening strokes produce almost the same wrist motion, so the two were constantly confused. Removing tumi gave a clean diagonal confusion matrix. |
| **না (na)** | removed | Very short and simple, so too little motion signal; it was unreliable live even after pruning its data. |
| **ডাক্তার (daktar)** | dropped | Not collected; kept the set small and reliable. |
| **ভালো (bhalo)** | replaced by **সালাম** | Its slot became the greeting, which is more useful in daily conversation. |

Removed data is kept in `python/data/_archive_variable_duration/`.

## 3. What makes a word easy or hard to recognise

The MPU6050 sees **wrist motion**, not letters. What matters is how distinct
the motion is.

| Type | Examples | Reliability | Why |
|---|---|---|---|
| **Gesture-style signatures** — long, distinctive motions | খাবার, সাহায্য, সালাম | highest | Big, unique motion energy that nothing else resembles |
| **Long air-written words** | ধন্যবাদ | high | Many strokes give a long, unique signal |
| **Short air-written words** | আমি, হ্যাঁ, পানি | good, needs care | Fewer strokes, so they need consistent writing and more samples |
| **Very short words** | না | poor | Too little signal; easily mistaken for idle |

Rules of thumb for a new word:

1. **Make it long enough** — at least ~1 second of deliberate motion.
2. **Make it different** — if a stroke sequence resembles an existing word,
   exaggerate or change it.
3. **Write it the same way every time** inside a style.

## 4. Recipe — adding a new word

Example: adding **ডাক্তার** (daktar, doctor) as class id **8**.

### Step 1 — collector label

`python/collector.py` → `LABELS` (keep `idle` last):

```python
{"id": 7, "name": "daktar", "bangla": "ডাক্তার (doctor)", "target": True,
 "default_duration_s": 6.0, "hint": "air-write ডাক্তার then hold still until 6 s"},
{"id": 8, "name": "idle",   "bangla": "(random / rest)",  "target": False,
 "default_duration_s": 6.0, "hint": "random hand movements for the full 6 s"},
```

### Step 2 — collect samples

Flash the logger (`firmware/`), run the collector, and record
**3 positions × 3 styles × 5+ reps** (45+ samples). See
[`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md).

### Step 3 — training label

`python/train.py` → `LABELS` (append; the id becomes the class number):

```python
{"id": 8, "name": "daktar", "bangla": "ডাক্তার"},
```

### Step 4 — host GUI colour

`python/infer_gui.py` → `CLASS_COLORS`:

```python
"daktar": "#7e57c2",
```

### Step 5 — train and check

```bash
cd python
.venv/bin/python train.py
```

Look at the confusion matrix. If the new word is confused with an existing
one, go back to Section 3.

### Step 6 — firmware

1. Copy the model and regenerate `model_norm.h` (exact commands in
   [`TRAINING.md`](TRAINING.md) § 10).
2. `firmware_infer/src/main.cpp` → add the Bangla text to `CLASS_BANGLA[]`
   **in the same order** as `MODEL_CLASS_NAMES`:
   ```cpp
   "ডাক্তার",      // daktar
   ```

### Step 7 — voice file

Record the word on a phone, save it as `Daktar.aac` in `The_Audios/`, and add
`"Daktar"` to `ORDER` in `python/prepare_audio.py`. Then:

```bash
cd python
.venv/bin/python prepare_audio.py
```

That creates `0008.mp3`. Copy the `mp3/` folder to the SD card again.

### Step 8 — flash and test

```bash
cd firmware_infer
pio run -t upload -t monitor
```

Air-write ডাক্তার → expect `DETECTED,daktar,0.8x`, the word on the OLED, and
the voice from the speaker.

## 5. How many words can SANKET hold?

| Classes | Difficulty |
|---|---|
| 2 (first smoke test) | trivial |
| 8 (current) | reliable with ~70–130 samples per class |
| 10–15 | feasible; choose very distinct motions, 60+ samples per class |
| 20+ | needs data from several users and possibly a larger model |

The INT8 model is ~149 KB and the ESP32-S3 has 16 MB of flash, so storage is
never the limit. The limit is how distinct the wrist motions are.
