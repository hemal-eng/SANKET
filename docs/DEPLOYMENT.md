# SANKET — Deployment Guide

How to build and flash SANKET onto an ESP32-S3-DevKitC-1, and how to read
what it prints while it recognises air-written Bangla words, shows them on
the OLED and speaks them through the DFPlayer.

## 1. Two firmwares, one board

| Folder | Role | Serial baud | When to flash |
|---|---|---|---|
| `firmware/` | **Data logger.** Streams IMU data and records fixed 6 s samples on command from `python/collector.py`. No ML on-chip. | **921600** | While collecting training data |
| `firmware_infer/` | **On-device inference.** Motion-triggered capture → INT8 model → OLED + audio. | **115200** | The finished device |

Both use the same board and the same MPU6050 wiring. Flashing one replaces
the other.

## 2. Toolchain

| Item | Value |
|---|---|
| Build system | PlatformIO, **pioarduino** core in `~/.platformio/penv` |
| Platform | `espressif32` (Arduino-ESP32 3.x) |
| Board | `esp32-s3-devkitc-1`, 16 MB flash, OPI PSRAM, `default_16MB.csv` partitions |
| TensorFlow Lite Micro | **The copy bundled with the Arduino-ESP32 framework** (`framework-arduinoespressif32-libs/esp32s3`: `espressif__esp-tflite-micro` + `esp-nn`, precompiled). It is **not** listed in `lib_deps` — a second copy causes header and link conflicts (see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)). |
| Libraries (`lib_deps`) | `mamunul/BanglaText`, `adafruit/Adafruit SSD1306`, `adafruit/Adafruit GFX Library`, `dfrobot/DFRobotDFPlayerMini` |

Check you are using the pioarduino core:

```bash
which pio && pio --version
```

It should print `~/.platformio/penv/bin/pio`. If an old copy exists in
`/usr/local/bin`, remove it (see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)).

## 3. Before flashing

1. Wire everything as in [`../hardware/WIRING.md`](../hardware/WIRING.md).
2. Insert the prepared microSD card into the DFPlayer
   ([`AUDIO_AND_DISPLAY.md`](AUDIO_AND_DISPLAY.md)).
3. Plug the USB cable into the **UART** port.
4. Lay the device **flat, face-up and still** — calibration runs at boot.

## 4. Build and flash `firmware_infer`

```bash
cd firmware_infer
pio run --target upload --target monitor
```

The first build downloads the libraries and compiles everything
(2–4 minutes). Later builds take ~25 seconds. A successful build ends with:

```
RAM:   [=======   ]  73.9% (used 242124 bytes from 327680 bytes)
Flash: [=         ]  13.3% (used 873811 bytes from 6553600 bytes)
========================= [SUCCESS] =========================
```

To open only the serial monitor later:

```bash
cd firmware_infer
pio device monitor --baud 115200
```

## 5. Resource usage

| Resource | Value |
|---|---|
| RAM | 73.9 % (≈ 242 KB of 320 KB) |
| Flash | 13.3 % |
| INT8 model (`model_data.h`) | ≈ 149 KB |
| Tensor arena | 168 KB reserved, 150.8 KB used (`150764/172032`) |
| Inference time | ~39–42 ms per word |
| Sampling | 100 Hz, uninterrupted (inference runs on the other core) |

## 6. Boot sequence

```
power on / RST
   │
   ├─ H,...        handshake line
   ├─ C,START      MPU6050 calibration (keep still, ~2.5 s)
   ├─ C,DONE,...   offsets (az ≈ +0.97 when flat and face-up)
   ├─ OLED init    "SANKET boot..."  (non-fatal if missing)
   ├─ DFPlayer     I,audio_ok,...    (non-fatal if missing, ~2.5 s)
   ├─ TFLite       I,arena_used=...
   ├─ I,ready,...  configuration summary
   └─ STATE,IDLE   OLED shows লিখুন — ready to write
```

## 7. Serial protocol (`firmware_infer`, 115200 baud)

### Example log

```
H,SANKET-infer,v4,motion-trigger+oled+audio,100hz
C,START
C,DONE,0.0147,-0.1618,0.9702,-2.37,1.35,0.10
I,audio_ok,files=7,volume=25
I,arena_used=150764/172032
I,ready,thresh=80.0,maxcap=3.50s,mincap=0.50s,settle=0.40s,cooldown=1.00s,classes=8
I,class_order=idle,ami,haan,dhonnobad,pani,khabar,shahajjo,salam
STATE,IDLE
LIVE,energy=2.2
LIVE,energy=1.9
STATE,CAPTURING,energy=92.8
CAP,n=50,elapsed=0.50s,energy=301.8,settled=0
CAP,n=100,elapsed=1.00s,energy=164.2,settled=0
CAP,n=150,elapsed=1.50s,energy=31.5,settled=21
STATE,FINISH,n=172,elapsed=1.72s,reason=settled
STATE,COOLDOWN
INFER,top=pani,conf=0.918,infer_ms=42,probs=[idle:0.016,ami:0.008,haan:0.004,dhonnobad:0.023,pani:0.918,khabar:0.012,shahajjo:0.008,salam:0.008]
DETECTED,pani,0.918
AUDIO,play=4,pani
AUDIO,done
STATE,IDLE
```

### Line reference

| Line | Meaning |
|---|---|
| `H,SANKET-infer,v4,...` | Handshake: firmware name and version |
| `C,START` / `C,DONE,ax,ay,az,gx,gy,gz` | Boot calibration; offsets in g and °/s |
| `I,audio_ok,files=N,volume=V` | DFPlayer answered; `files` = files it sees on the card (`-1` = card not ready yet) |
| `I,arena_used=used/total` | TFLite tensor arena usage in bytes |
| `I,ready,...` | Trigger threshold (°/s), max/min capture, settle time, cooldown, class count |
| `I,class_order=...` | Class index order (index = DFPlayer track number) |
| `STATE,IDLE` | Armed, waiting for wrist motion |
| `LIVE,energy=E` | Once per second while idle: current gyro energy (°/s) |
| `STATE,CAPTURING,energy=E` | Motion crossed the threshold; recording started |
| `CAP,n=,elapsed=,energy=,settled=` | Every 0.5 s while recording; `settled` = samples below threshold |
| `STATE,FINISH,n=,elapsed=,reason=` | Recording ended. `settled` = wrist still 0.4 s, `max_cap` = hit 3.5 s, `short_discard` = under 0.5 s (ignored) |
| `STATE,COOLDOWN` | Waiting for the result and audio before re-arming |
| `INFER,top=,conf=,infer_ms=,probs=[...]` | Model output for every capture |
| `DETECTED,word,conf` | Top class is not idle and confidence ≥ 0.75 |
| `AUDIO,play=N,word` | DFPlayer told to play `/mp3/000N.mp3` |
| `AUDIO,done` | Playback finished (BUSY pin went HIGH) |
| `W,oled_not_found_continuing_without_display` | No OLED — runs without display |
| `W,dfplayer_not_found_continuing_without_audio` | No DFPlayer — runs display-only |
| `E,mpu_init_fail`, `E,who_am_i=0x..` | MPU6050 not found — device halts (check wiring) |
| `E,allocate_tensors_failed`, `E,tflite_init_fail` | Model could not be loaded — device halts |
| `E,read_fail`, `E,invoke_failed`, `E,snap_mutex_busy` | Runtime errors (recoverable) |

## 8. Switching back to the data logger

```bash
cd firmware
pio run --target upload
```

Then run `python/collector.py`, which talks to the logger at **921600**
baud. Flash `firmware_infer` again when you are done collecting.

## 9. Backup and test sketches (`firmware_infer/src/test/`)

`platformio.ini` contains `build_src_filter = +<*> -<test/>`, so files in
`src/test/` are **never compiled** with the main firmware. They are kept
as working references:

| File | Purpose |
|---|---|
| `main_dfplayer_phase1_test.cpp` | **Audio-only test.** Plays all 7 MP3s, reads BUSY, serial keys `1`–`7`, `a`, `+`, `-`, `s`, `?` (115200 baud). Use it to check DFPlayer wiring and the SD card. |
| `main_oled_bangla270_working.cpp` | Motion-trigger + model + OLED with Bangla rotated 270°, before audio was added |
| `main_oled_full.cpp` | First OLED + BanglaText integration |
| `main_motion_trigger_working.cpp` | Motion-trigger + model, serial output only (no OLED, no audio) |

To run one of them, swap it in temporarily:

```bash
cd firmware_infer
cp src/main.cpp src/test/main_current_backup.cpp
cp src/test/main_dfplayer_phase1_test.cpp src/main.cpp
pio run --target upload --target monitor
# restore afterwards:
cp src/test/main_current_backup.cpp src/main.cpp
```

## 10. If something goes wrong

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — every problem met while
building SANKET is listed there with its cause and fix.
