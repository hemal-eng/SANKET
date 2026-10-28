# SANKET — Bill of Materials

As of the current state of the project (data logger + on-device inference).

| # | Component | Qty | Approx price | Where to buy (BD / global) |
|---|---|---|---|---|
| 1 | ESP32-S3-DevKitC-1 N16R8 (dual-USB *black* board) | 1 | ~৳550 / ~$5 | TechShop BD, Daraz, AliExpress, Amazon |
| 2 | MPU6050 breakout (GY-521 or clone) | 1 | ~৳100 / ~$1 | TechShop BD, Daraz, AliExpress |
| 3 | Jumper wires (female-female), 4 pcs | — | <৳20 / <$0.50 | any electronics shop |
| 4 | USB cable (Micro-USB or USB-C depending on board) | 1 | you own | — |
| **Total parts cost** |  |  | **~৳670 / ~$6.50** |  |

That's the entire system. No camera, no gloves, no phone, no cloud.

## Why so cheap?

The whole design philosophy is **"low-cost deaf-aid"**:

- ESP32-S3 is a $5 chip but has dual-core 240 MHz, 320 KB RAM, 8 MB
  PSRAM, 16 MB flash, and a vector ISA (esp-nn) that accelerates
  INT8 neural nets.
- MPU6050 is the **cheapest** 6-axis IMU in the world — $1 clones
  work fine with our DLPF + boot-time calibration + IIR filter pipeline.
- No glove / no camera / no cloud → nothing recurring, nothing to
  break, nothing to invade privacy.

## Current form factor

The dev board sits on the wrist (wrapped with Velcro or taped), with the
MPU6050 breakout flat on top. For a wearable product the two could be
combined onto a custom PCB the size of a wristwatch.

## Future BOM additions (not yet implemented)

See [`../docs/FUTURE_WORK.md`](../docs/FUTURE_WORK.md) for what's coming.
These are **not** in the current project:

- DFPlayer Mini + small 3W speaker (voice output)
- SSD1306 128×64 OLED (text display)
- 18650 cell + TP4056 (battery)
- 3D-printed enclosure (wrist strap)
