# `firmware/` — SANKET Data Logger

PlatformIO + Arduino firmware for the ESP32-S3-DevKitC-1 used **during
data collection**. Streams IMU over USB serial and captures one-shot
6-second gesture recordings on demand.

## When to flash this

Only during data collection. For deployment (recognizing gestures on-chip)
flash [`firmware_infer/`](../firmware_infer/) instead.

## What it does

- Boots → prints handshake `H,SANKET-logger,v5,100hz,oneshot,600`
- Runs a 200-sample MPU6050 auto-calibration (keep wrist still ~2 s)
- Streams `L,<ax>,<ay>,<az>,<gx>,<gy>,<gz>` at 100 Hz continuously
- Listens for `T\n` over serial (sent by the Python collector when you press SPACE):
  - Starts a **one-shot** recording of exactly 600 samples (6.0 s @ 100 Hz)
  - Prints `R,START` → 600× `D,...` → `R,STOP,600`
  - Any `T\n` received during a recording is ignored
- Also accepts a BOOT-button press as a fallback trigger

Also runs a software IIR low-pass filter (α=0.3) over the 6 raw IMU
channels before transmission, so what the GUI sees matches what the
model will see at inference time.

## Pin assignments

| Pin | Function |
|---|---|
| GPIO 8 | I²C SDA (MPU6050) |
| GPIO 9 | I²C SCL (MPU6050) |
| GPIO 0 | BOOT button (built-in, optional trigger) |

## Serial protocol

### Device → Host
```
H,SANKET-logger,v5,100hz,oneshot,600          handshake
C,START                                        calibration started
C,DONE,ox,oy,oz,ogx,ogy,ogz                   calibration done (offsets)
L,ax,ay,az,gx,gy,gz                           live stream @100 Hz
R,START                                        recording started
D,ax,ay,az,gx,gy,gz                           recording sample (600 total)
R,STOP,<sample_count>                         recording ended (count = 600)
E,<reason>                                    error
```

### Host → Device
```
T\n          trigger a one-shot recording (ignored if already recording)
```

## Build + flash

```bash
cd firmware
pio run -t upload
```

Then launch the collector GUI (see [`../python/README.md`](../python/README.md)).

## Configuration

Edit `src/main.cpp` constants to tune:

| Constant | Current | Meaning |
|---|---|---|
| `SAMPLE_RATE_HZ` | 100 | IMU sampling rate |
| `FIXED_RECORD_SAMPLES` | 600 | Length of each one-shot recording |
| `FILTER_ALPHA` | 0.30 | IIR low-pass smoothing (0..1, smaller = heavier smoothing) |
| `CALIB_SAMPLES` | 200 | Boot-time calibration average length (2 s @ 100 Hz) |

If you change `FIXED_RECORD_SAMPLES`, also update:
- `python/collector.py` → `FIXED_RECORD_S`, `FIXED_RECORD_SMPL`
- `python/train.py` → `WINDOW`
- `python/infer_gui.py` → `WINDOW`
- `firmware_infer/src/model_norm.h` → `MODEL_WINDOW`

They must all agree.
