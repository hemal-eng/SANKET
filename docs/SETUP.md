# SANKET — Setup Guide

One-time setup to get your machine ready for data collection, training,
flashing and preparing the voice files.

## 1. Prerequisites

### Operating system
- **macOS 11+** (Intel or Apple Silicon) — the primary development platform
- **Linux** — Ubuntu 20.04+ or any recent distro
- **Windows 10/11** (WSL2 works too)

### Install Python 3.10 or 3.11

```bash
# macOS (Homebrew)
brew install python@3.11

# Ubuntu
sudo apt update && sudo apt install -y python3.11 python3.11-venv

# Windows
# Download from https://www.python.org/downloads/  (check "Add to PATH")
```

Verify:
```bash
python3 --version        # should print 3.10.x or 3.11.x
```

### Install PlatformIO (pioarduino core)

SANKET is built with the **pioarduino** flavour of PlatformIO, which ships
the current Arduino-ESP32 3.x framework for the ESP32-S3. The easiest way is
the **pioarduino IDE** extension in VS Code; it installs its own core into a
private Python environment:

```
~/.platformio/penv/bin/pio
```

Make sure that is the `pio` your shell uses:

```bash
which pio                 # should print /Users/<you>/.platformio/penv/bin/pio
pio --version
```

> ⚠️ **Only keep ONE PlatformIO core installed.** A second copy (for example
> a system-wide `pip install platformio` in `/usr/local/lib/python3.x/` or a
> Homebrew `platformio`) gets picked up by VS Code tasks and causes errors
> such as *"Obsolete PIO Core v6.1.x is used"* or
> *"ModuleNotFoundError: No module named 'littlefs'"*. Remove the extra copy:
>
> ```bash
> which -a pio platformio            # list every copy on your PATH
> pip3 uninstall platformio          # if it was pip-installed system-wide
> brew uninstall platformio          # if it was Homebrew-installed
> ```

### TensorFlow Lite Micro — nothing to install

The on-device firmware uses **TensorFlow Lite Micro (TFLM)**. It comes
**precompiled inside the Arduino-ESP32 framework** (component
`espressif__esp-tflite-micro`, together with the `esp-nn` ESP32-S3 vector
kernels). Do **not** add `esp-tflite-micro` to `lib_deps` — a second copy
collides with the bundled one at compile time.

### Install the USB-UART driver

The ESP32-S3-DevKitC-1 (N16R8, dual-USB black board) uses a **CH343** or
**CP2102** USB-UART bridge on its "UART" port.

- **macOS**: usually works out of the box; if not, install the CH34x
  Mac VCP driver from WCH.
- **Linux**: works out of the box (`cdc-acm` kernel module).
- **Windows**: install the WCH CH343 Windows driver.

## 2. Clone the repository

```bash
git clone https://github.com/hemal-eng/SANKET.git
cd SANKET
```

## 3. Set up the Python environment

The project's virtual environment lives at `python/.venv`.

```bash
cd python
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

This installs:

| Package | Why |
|---|---|
| **tensorflow** 2.15.1 | Model training + TFLite export |
| **scikit-learn** | Classification metrics (confusion matrix, F1) |
| **PySide6** | Qt GUIs (collector + host inference tester) |
| **pyqtgraph** | Live scrolling IMU plots |
| **pyserial** | Reads the MPU6050 stream from the ESP32-S3 |
| **numpy** | Signal processing + `.npz` dataset storage |
| **lameenc** | MP3 encoding of the DFPlayer voice files (`prepare_audio.py`) |
| **fpdf2** | Builds the Zenodo disclosure PDF |

> ⚠️ **Intel Mac tip** — TensorFlow 2.16+ dropped Intel-macOS wheels.
> `tensorflow==2.15.1` is the last version that works on x86_64 Macs.
> `requirements.txt` already pins it.

Verify:
```bash
python -c "import tensorflow as tf, lameenc; print(tf.__version__)"
# → 2.15.1
```

You can always run the tools without activating the venv:

```bash
cd python
.venv/bin/python collector.py
```

## 4. Wire the hardware

See [`../hardware/WIRING.md`](../hardware/WIRING.md) for the full device
(MPU6050 + SSD1306 OLED + DFPlayer Mini). For data collection only the
MPU6050 is needed:

| ESP32-S3 pin | MPU6050 pin |
|---|---|
| GPIO 8 | SDA |
| GPIO 9 | SCL |
| 3V3 | VCC |
| GND | GND |

Use the **UART** USB port on the dev board (not the native USB port).

## 5. Verify the serial port appears

Plug in the ESP32-S3 (UART port). Then:

```bash
ls /dev/cu.* 2>/dev/null | grep -Ei "wch|usbserial|usbmodem|SLAB|CP210"
# macOS example:
# /dev/cu.wchusbserial5AE70219441
```

```bash
# Linux
ls /dev/ttyUSB* /dev/ttyACM*
```

```powershell
# Windows (PowerShell)
Get-WmiObject Win32_SerialPort | Select-Object Name, DeviceID
```

If nothing shows up: install the driver (step 1) and try a different cable
(many USB cables are power-only). On macOS, Bluetooth ports such as
`/dev/cu.Bluetooth-Incoming-Port` are **not** the board.

## 6. You're ready

| Goal | Go to |
|---|---|
| **Flash the full device firmware** | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| **Collect your own data** | [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md) |
| **Train the model** | [`TRAINING.md`](TRAINING.md) |
| **Add new Bangla words** | [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md) |
| **Prepare voice files / SD card** | [`../python/README.md`](../python/README.md) → `prepare_audio.py` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| *Obsolete PIO Core* / `No module named 'littlefs'` | Two PlatformIO cores installed — remove the non-pioarduino one (see above) |
| `pio run` fails: *framework not found* | `pio pkg install --platform espressif32` |
| Compile errors about `Register_IRFFT` / `tflm_signal` conflicts | `esp-tflite-micro` was added to `lib_deps` — remove it and delete `.pio/libdeps/*/esp-tflite-micro` |
| Port appears but upload fails | Close any serial monitor or GUI holding the port |
| `ModuleNotFoundError: PySide6` | Activate the venv, or run with `.venv/bin/python` |
| GUI window larger than the screen | Both GUIs are resizable and scrollable — drag the window edge |
| Mac Terminal can't read `~/Documents/` | Grant Full Disk Access to Terminal in System Settings → Privacy & Security |
| USB port disappears after a reset storm | Unplug + replug the cable; wait 2 seconds |
