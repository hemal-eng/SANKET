# SANKET — Setup Guide

One-time setup to get your machine ready for data collection, training,
and flashing.

## 1. Prerequisites

### Operating system
- **macOS 11+** (Intel or Apple Silicon)
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

### Install PlatformIO Core

```bash
# Recommended — Homebrew
brew install platformio

# Or via pip (any OS)
pip install -U platformio
```

Verify:
```bash
pio --version            # should print 6.x or newer
```

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
| **tensorflow** 2.15.x | Model training + TFLite export |
| **scikit-learn** | Classification metrics (confusion matrix, F1) |
| **PySide6** | Qt-based GUI (collector + inference viewer) |
| **pyqtgraph** | Live scrolling IMU plots |
| **pyserial** | Reads MPU6050 stream from the ESP32-S3 |
| **numpy** | Signal processing + .npz dataset storage |

> ⚠️ **Intel Mac tip** — TensorFlow 2.16+ dropped Intel-macOS wheels.
> `pip install tensorflow==2.15.1` is the last version that works on x86_64 Macs.
> `requirements.txt` already pins this.

Verify TensorFlow installed:
```bash
python -c "import tensorflow as tf; print(tf.__version__)"
# → 2.15.1
```

## 4. Wire the hardware

See [`../hardware/WIRING.md`](../hardware/WIRING.md).

Quick summary:

| ESP32-S3 pin | MPU6050 pin |
|---|---|
| GPIO 8 | SDA |
| GPIO 9 | SCL |
| 3V3 | VCC |
| GND | GND |

Use the **UART** USB port on the dev board (not the native USB port) — the
firmware is configured for UART-CDC.

## 5. Verify serial port appears

Plug in the ESP32-S3 (UART port). Then:

```bash
ls /dev/cu.* 2>/dev/null | grep -Ei "wch|usbserial|usbmodem|SLAB|CP210"
# macOS examples:
# /dev/cu.wchusbserial5AE70219441
# /dev/cu.SLAB_USBtoUART
```

```bash
# Linux
ls /dev/ttyUSB* /dev/ttyACM*
# → /dev/ttyUSB0  (typically)
```

```powershell
# Windows (PowerShell)
Get-WmiObject Win32_SerialPort | Select-Object Name, DeviceID
# → look for "USB-SERIAL CH343" or similar
```

If nothing shows up: install the driver (step 1) and try a different cable
(many micro-USB cables are power-only).

## 6. You're ready

Next step depends on your goal:

| Goal | Go to |
|---|---|
| **Just try the pre-trained model** | [`DEPLOYMENT.md`](DEPLOYMENT.md) → "Flashing the inference firmware" |
| **Collect your own data and train** | [`DATA_COLLECTION_GUIDE.md`](DATA_COLLECTION_GUIDE.md) |
| **Add new Bangla words** | [`GESTURE_DESIGN_GUIDE.md`](GESTURE_DESIGN_GUIDE.md) |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pio run` fails: *framework not found* | `pio pkg install --platform espressif32` |
| Port appears but `pio run -t upload` fails | Close any serial monitor holding the port |
| `ModuleNotFoundError: PySide6` | Activate venv (`source .venv/bin/activate`) then `pip install PySide6` |
| Mac Terminal can't read `~/Documents/` for PlatformIO | Grant Full Disk Access to Terminal in System Settings → Privacy & Security |
| USB port disappears after reset storm | Unplug + replug the USB cable; wait 2 seconds |
