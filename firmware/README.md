# `firmware/` — SANKET Data Logger (v6)

PlatformIO + Arduino firmware for the ESP32-S3-DevKitC-1, used **during data
collection** and with the host test GUI. It streams the MPU6050 over USB
serial and records one-shot gesture captures on demand.

## When to flash this

- Collecting data with `python/collector.py`
- Testing a model on the laptop with `python/infer_gui.py`

For the standalone device (on-chip recognition + OLED + voice), flash
[`firmware_infer/`](../firmware_infer/) instead.

## What it does

- Boots → prints `H,SANKET-logger,v6,100hz,oneshot,100-2000`
- Waits 1.5 s, then averages **200 samples (2 s)** for the bias calibration
  (keep the board still, flat and face-up)
- Applies an IIR low-pass filter (**α = 0.30**) to all 6 channels
- Streams `L,ax,ay,az,gx,gy,gz` at **100 Hz** whenever it is not recording
- On `T<N>` records **exactly N samples** (one-shot), then stops by itself.
  The collector sends `T600` (6.0 s).
- Any trigger during a recording is ignored, so a recording can never be cut short
- **BOOT button** (GPIO 0) is a fallback trigger: debounced 40 ms, ignored for
  the first 1 s after boot, records the default 600 samples

## Sensor configuration

| Setting | Value |
|---|---|
| I²C | GPIO 8 SDA, GPIO 9 SCL, 400 kHz, address 0x68 |
| Sample rate | 100 Hz (`SMPLRT_DIV = 9`) |
| Digital low-pass filter | 44 Hz (`CONFIG = 0x03`) |
| Accelerometer range | ±4 g (8192 LSB/g) |
| Gyroscope range | ±500 °/s (65.5 LSB/°/s) |
| Software IIR | α = 0.30 |

## Serial protocol (921600 baud)

### Device → Host
```
H,SANKET-logger,v6,100hz,oneshot,100-2000   handshake
C,START                                      calibration started
C,DONE,ox,oy,oz,ogx,ogy,ogz                  offsets (g, °/s)
L,ax,ay,az,gx,gy,gz                          live stream @100 Hz
R,START,<N>                                  recording started (N samples)
D,ax,ay,az,gx,gy,gz                          recording sample
R,STOP,<count>                               recording ended
E,<reason>                                   error
```

### Host → Device
```
T\n        record the default 600 samples
T<N>\n     record N samples (clamped to 100 … 2000)
```

## Build + flash

```bash
cd firmware
pio run -t upload
pio device monitor -b 921600
```

## Configuration (`src/main.cpp`)

| Constant | Value | Meaning |
|---|---|---|
| `SAMPLES_DEFAULT` | 600 | recording length when no N is given |
| `SAMPLES_MIN` / `SAMPLES_MAX` | 100 / 2000 | clamp for `T<N>` |
| `FILTER_ALPHA` | 0.30 | IIR smoothing (smaller = smoother) |
| `CALIB_SAMPLES` | 200 | calibration length (2 s) |
| `CALIB_WARMUP_MS` | 1500 | wait before calibrating |
| `BTN_DEBOUNCE_MS` | 40 | BOOT button debounce |

The model window (600 samples) must agree across `collector.py`
(`FIXED_DURATION_S = 6.0`), `train.py` (`WINDOW`), `infer_gui.py` (read from
`norm.json`) and `firmware_infer/src/model_norm.h` (`MODEL_WINDOW`).

> The logger and the on-device firmware use the **same** filter, ranges and
> calibration, so the data the model was trained on matches what the device
> sees live.
