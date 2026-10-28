# SANKET — System Architecture

## 1. End-to-end pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                            WRIST (user)                               │
│                                                                        │
│     MPU6050 IMU  ──I²C 400 kHz──▶  ESP32-S3-N16R8                     │
│     (ax ay az gx gy gz)                                               │
└──────────────────────────────────────────────────────────────────────┘
                                      │
                                      │  921600 baud UART over USB
                                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                              DEV MACHINE                              │
│                                                                        │
│   DATA COLLECTION       TRAINING            HOST-SIDE INFER           │
│   ───────────────       ────────            ─────────────────         │
│   collector.py    →     train.py       →    infer_gui.py              │
│   (.npz files)          (TFLite + .h)       (debug/verify)            │
│                                                                        │
│                    exports → firmware_infer/model_data.h               │
└──────────────────────────────────────────────────────────────────────┘
                                      │
                            flash via `pio run -t upload`
                                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│          AFTER DEPLOYMENT — PRODUCT RUNS STAND-ALONE                   │
│                                                                        │
│   MPU6050 → ESP32-S3 (both cores) → UART → `P,ami,0.996`              │
│                                            `DETECTED,ami,0.996`        │
│                                                                        │
│   No Mac, no cloud, no internet. On-chip inference @ ~17 KB model.    │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. Dual-core firmware (`firmware_infer/`)

The ESP32-S3 has two Xtensa LX7 cores. SANKET pins work to specific cores so
sampling stays rock-solid at 100 Hz even while the model is computing.

| Core | Task              | Priority | What it does                                                                 |
|------|-------------------|----------|------------------------------------------------------------------------------|
|  1   | `loop()`          | default  | Reads IMU every 10 ms, applies IIR low-pass, writes to ring buffer.         |
|  1   | `loop()` cont.    | default  | Every 30 samples: `memcpy` ring → snapshot (under mutex), notify infer task. |
|  0   | `inferTask`       | 1        | Waits for notify → normalize + quantize snapshot → `interpreter->Invoke()` → print result. |

### Why dual-core matters

Inference (`Invoke()`) takes 30–100 ms. If this blocked the main loop,
IMU samples would be dropped and the ring buffer would get time-compressed —
the gesture pattern would drift from the training distribution. With
two cores, sampling is **never blocked** and the model always sees
genuine 100 Hz data.

### Ring-buffer design

```
MODEL_WINDOW = 600 samples = 6 seconds at 100 Hz
MODEL_CHANNELS = 6 (ax ay az gx gy gz, physical units)

g_ring[600][6]        ← FIFO ring, newest sample overwrites oldest
g_ring_ptr            ← next write index = oldest sample
g_ring_total          ← monotonic sample counter
INFER_STRIDE_SMPL = 30  ← inference triggers every 300 ms
```

The snapshot is a chronological copy of the ring, so inference sees a
coherent 6 s window ending at "now".

## 3. Model architecture

```
Input:  (600, 6)  float32   per-channel normalized
   │
   ▼
Conv1D(16, 7, stride=2) → BN → ReLU   ──▶  (300, 16)
   │
   ▼
Conv1D(32, 5, stride=2) → BN → ReLU   ──▶  (150, 32)
   │
   ▼
Conv1D(48, 3, stride=2) → BN → ReLU   ──▶  (75, 48)
   │
   ▼
GlobalAveragePooling1D                ──▶  (48,)
   │
   ▼
Dropout(0.3) → Dense(K, softmax)      ──▶  K probabilities
```

- **Parameters:** ~5 K
- **Flash (INT8 TFLite):** 17 KB
- **Tensor arena at runtime:** 27 KB of a 90 KB budget
- **Inference latency on ESP32-S3 @ 240 MHz (esp-nn):** typically 30–60 ms

## 4. Serial protocol

### Data logger (`firmware/`)
```
H,SANKET-logger,v5,100hz,oneshot,600
C,START
C,DONE,<offsets as g and °/s>
L,<ax>,<ay>,<az>,<gx>,<gy>,<gz>          live preview @100 Hz
R,START                                   recording started (SPACE or BOOT edge)
D,<ax>,<ay>,<az>,<gx>,<gy>,<gz>          600 of these per recording
R,STOP,<sample_count>                     recording ended (auto at 600)
E,<reason>                                error
```

Host → Device:
```
T\n                                       trigger one-shot recording
```

### Inference (`firmware_infer/`)
```
H,SANKET-infer,v1,100hz,on-device
C,START
C,DONE,<offsets>
I,ready
P,<class_name>,<confidence>               every ~300 ms (top class)
DETECTED,<class_name>,<confidence>        after 2 consecutive >0.75
E,<reason>                                error
```

## 5. Why this architecture

| Decision                   | Why                                                                           |
|----------------------------|-------------------------------------------------------------------------------|
| Wrist (watch) form factor  | Natural for daily wear, no stigma, zero extra hardware worn.                   |
| MPU6050 only               | $1 part, 6-axis IMU is enough for connected air-writing gestures.             |
| 6-second one-shot window   | Fits slow deliberate writers (3–4 s gesture + rest). Firmware counts, so no "when to stop" bug. |
| Position × Style collection| Captures user variability — different arm poses + writing speeds.             |
| 1D-CNN (not RNN)           | Smaller, faster, quantizes cleanly to INT8, no need for state across windows. |
| INT8 full quantization     | 2× smaller, uses esp-nn SIMD on ESP32-S3, ~2× faster inference.                |
| Dual-core on ESP32-S3      | Keeps IMU sampling pure 100 Hz regardless of inference time.                   |
| Air-written full word      | Short, memorable, consistent, more distinct from random motion than letters.   |
