# `firmware_infer/` — SANKET On-Device Inference Firmware

PlatformIO + Arduino firmware for the ESP32-S3-DevKitC-1 that runs the
trained INT8 TFLite model **directly on the chip**. This is the deployed
product — no Mac, no cloud, no internet required at runtime.

## When to flash this

After training (or using the included pre-trained model). For data
collection, flash [`../firmware/`](../firmware/) instead.

## What it does

- Boots → prints `H,SANKET-infer,v1,100hz,on-device`
- Runs IMU auto-calibration
- Allocates TensorFlow Lite Micro tensors (~27 KB of a 90 KB arena)
- **Core 1 (`loop()`)**: samples MPU6050 at 100 Hz into a 600-sample ring buffer
- **Core 0 (`inferTask`)**: every 30 new samples (~300 ms), runs the INT8 1D-CNN via `esp-tflite-micro`+ `esp-nn`
- Outputs one `P,<class>,<confidence>\n` line per inference
- Outputs one `DETECTED,<class>,<confidence>\n` line when confidence > 0.75 for 2 consecutive inferences

## Why dual-core

The single-core version blocked IMU sampling during inference (~60 ms),
causing time-stretch in the ring buffer that degraded detection accuracy
on repeated gestures. The dual-core version keeps **100 Hz sampling
unbroken** while inference runs in parallel on the other core.

Communication is via:

- A snapshot buffer (`g_snapshot[600][6]`) that `loop()` memcpys the ring
  into at trigger time.
- A FreeRTOS mutex (`g_snap_mutex`) guarding the snapshot.
- An `xTaskNotifyGive`/`ulTaskNotifyTake` signal from `loop()` to the
  inference task.

Mutex contention is ~140 µs per 300 ms — completely invisible to the
10 ms sampling schedule.

## Model

| Property | Value |
|---|---|
| File | `src/model_data.h` |
| Variable | `const unsigned char sanket_model[]` |
| Length | `sanket_model_len` bytes (~17 KB for the included model) |
| Format | INT8 TFLite, full quantization |
| Input | `[1, 600, 6]` int8 (zp = 0, scale = 0.078) |
| Output | `[1, K]` int8 (zp = -128, scale ≈ 1/256), K = number of classes |

The ops registered in the resolver (`MicroMutableOpResolver<6>`):
`CONV_2D, EXPAND_DIMS, FULLY_CONNECTED, MEAN, RESHAPE, SOFTMAX`.
If you train a model with other ops (e.g. add `RELU` or `QUANTIZE`),
register them too in `src/main.cpp` → `setupTFLite()`.

## Serial protocol

```
H,SANKET-infer,v1,100hz,on-device
C,START
C,DONE,ox,oy,oz,ogx,ogy,ogz
I,ready
P,<class_name>,<confidence>          every ~300 ms
DETECTED,<class_name>,<confidence>   after 2 consecutive > 0.75
E,<reason>                           on error (invoke failure, I2C fail)
```

## Build + flash

```bash
cd firmware_infer
pio run -t upload
pio device monitor --baud 921600
```

First build pulls the `espressif/esp-tflite-micro` library from GitHub —
~3–8 minutes depending on bandwidth. Subsequent builds take ~10 seconds.

## PlatformIO config highlights

```ini
lib_deps =
    https://github.com/espressif/esp-tflite-micro.git

build_unflags = -fexceptions
build_flags =
    -O2
    -DBOARD_HAS_PSRAM
    -DARDUINO_USB_MODE=0
    -DARDUINO_USB_CDC_ON_BOOT=0
    -DTF_LITE_STATIC_MEMORY
    -DESP_NN
    -DCONFIG_IDF_TARGET_ESP32S3=1
    -fno-exceptions
    -fpermissive
```

- `esp-tflite-micro` is Espressif's official TFLite-Micro port with
  ESP32-S3 vector-ISA (`esp-nn`) acceleration — ~2× faster than generic
  kernels for INT8 Conv/FC/Softmax.
- `-fno-exceptions` is required because TFLite-Micro's placement-new in
  C++17 would otherwise fail to compile.
- `-fpermissive` downgrades the private-`operator delete` access error
  (deliberate in TFLM's `TF_LITE_REMOVE_VIRTUAL_DELETE` macro) to a warning.
- `-DBOARD_HAS_PSRAM`, `qio_opi` memory type → use the 8 MB PSRAM on
  the N16R8 board.

## Configuration

| Constant | Current | Meaning |
|---|---|---|
| `SAMPLE_RATE_HZ` | 100 | Hz |
| `INFER_STRIDE_SMPL` | 30 | Infer every N new samples (= 300 ms) |
| `CONF_THRESHOLD` | 0.75 | Minimum confidence to count toward a detection streak |
| `CONSEC_FRAMES` | 2 | Consecutive frames above threshold to fire `DETECTED` |
| `kTensorArenaSize` | 92 160 bytes | TFLM arena size |

Current model uses only ~27 KB of the arena; if you train a bigger model
and `AllocateTensors` fails, bump `kTensorArenaSize` to 128 KB or more.

## After retraining

See [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the full update
flow, in short:

```bash
cp python/models/model_data.h  firmware_infer/src/model_data.h
# update MODEL_CLASS_NAMES[] in firmware_infer/src/model_norm.h if classes changed
cd firmware_infer
pio run -t upload
```
