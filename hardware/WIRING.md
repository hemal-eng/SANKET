# SANKET — Wiring Guide

## Pinout

| ESP32-S3-DevKitC-1 pin | MPU6050 pin | Function |
|---|---|---|
| **GPIO 8**  | **SDA** | I²C data |
| **GPIO 9**  | **SCL** | I²C clock |
| **3V3**     | **VCC** | 3.3 V power |
| **GND**     | **GND** | ground |

That's four wires. There is nothing else to connect.

## Diagram (ASCII)

```
     ESP32-S3-DevKitC-1 (N16R8, black, dual-USB)              MPU6050 (GY-521)
   ┌───────────────────────────────────────────┐             ┌──────────────┐
   │                                           │             │              │
   │        [ UART USB port — use this ]       │             │   VCC  ◀─────┼──── 3V3  ◀┐
   │                                           │             │              │           │
   │                                           │             │   GND  ◀─────┼──── GND  ◀┤
   │                                           │             │              │           │
   │   GPIO 8 (SDA)  ──────────────────────────┼──── SDA ────▶              │           │
   │                                           │             │              │           │
   │   GPIO 9 (SCL)  ──────────────────────────┼──── SCL ────▶              │           │
   │                                           │             │              │           │
   └───────────────────────────────────────────┘             └──────────────┘
                                                                             │
                                                                             │
                        3V3 and GND come from the ESP32-S3 header pins ──────┘
```

## Important notes

### Use the **UART** USB port, NOT the native USB port

The dual-USB black ESP32-S3-DevKitC-1 has two USB-C (or Micro-USB) ports:

- **UART port** — goes through a CH343 or CP2102 USB-UART bridge.
  This is what the firmware uses (921600 baud).
- **Native USB (USB-OTG) port** — directly to the ESP32-S3 USB
  controller. SANKET firmware is **not** configured for this port.

Plug your cable into the UART port. If you have the native port
selected in the OS it'll show up with a different `/dev/cu.*` name.

### I²C address

The MPU6050 defaults to **0x68** (AD0 pin tied low). SANKET firmware
assumes this address. If your board has AD0 jumpered high (0x69), either:

- Short the AD0 jumper to GND, or
- Change `MPU_ADDR` in `firmware/src/main.cpp` and
  `firmware_infer/src/main.cpp` from `0x68` to `0x69`.

### Pull-ups

MPU6050 breakout boards include I²C pull-ups on the module. No external
pull-ups needed.

### Clock speed

Firmware runs the I²C bus at **400 kHz**:
```cpp
Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
```

### Powering the MPU6050 from the ESP32-S3 is safe

The MPU6050 draws ~3.9 mA max. The ESP32-S3-DevKitC-1's onboard LDO can
supply ~500 mA on the 3V3 rail. No problem.

## Mounting on the wrist

For data collection and testing you can simply:

1. Place the ESP32-S3 flat on the back of your wrist.
2. Tape the MPU6050 flat on top of (or beside) it so the IMU axes stay
   consistent across sessions.
3. Secure with a Velcro strap or a soft cloth band.
4. Keep the USB cable loose so it doesn't tug the board mid-gesture.

> ⚠️ **Keep the MPU6050's orientation CONSISTENT across all data-collection
> sessions AND inference use.** The model learns the gesture *as seen from
> a specific sensor orientation*. If you flip the board upside down between
> training and use, the model will fail.
