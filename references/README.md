# `references/` — Third-party libraries used by SANKET

This folder holds third-party open-source libraries that SANKET uses or
plans to use. They remain under their original authors' licenses — see
each subfolder for the specifics.

## Current contents

### `BanglaText-main/` — Bangla text rendering for OLED displays
- **Author:** Mamunul Mazid
- **License:** MIT (see `BanglaText-main/LICENSE`)
- **Upstream:** https://github.com/mamunul/BanglaText
- **Why we keep it:** The future **OLED display** feature of SANKET
  (showing the detected Bangla word on a 128×64 SSD1306 or similar)
  will use this library. It handles Bangla shaping engine logic
  (conjuncts, kars, reph) and ships pre-generated font headers.
- **Status in SANKET:** Not yet wired into the firmware. Planned
  under `docs/FUTURE_WORK.md` → "On-wrist OLED".

### Not vendored, but worth noting
- **`esp-tflite-micro`** — Espressif's official TensorFlow Lite Micro
  port. Pulled via PlatformIO `lib_deps` at build time, so it lives
  under `firmware_infer/.pio/libdeps/…/esp-tflite-micro/` (gitignored).
- **`fpdf2`, `tensorflow`, `scikit-learn`, `PySide6`, `pyqtgraph`,
  `pyserial`, `numpy`** — Python deps, installed via `pip` from PyPI
  into `python/.venv/` (also gitignored).

## Why this folder exists
Keeping third-party code the SANKET project explicitly reads (vs. just
links against) in-tree makes the research artifact fully reproducible
decades from now, even if upstream repositories vanish.
