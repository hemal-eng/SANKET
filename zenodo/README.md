# Zenodo defensive-publication package

This folder contains everything needed to publish SANKET on
[Zenodo](https://zenodo.org) as a formal defensive publication —
establishing worldwide **prior art** so no one else can patent the
invention after today's date.

## Files

| File | What it is |
|---|---|
| `SANKET_disclosure.md` | Markdown source — the full technical disclosure (10 sections) |
| `SANKET_disclosure.pdf` | **Rendered PDF** — upload this to Zenodo |
| `build_pdf.py` | Re-build the PDF after editing the Markdown source |
| `README.md` | This file |
| *(repo root)* `.zenodo.json` | Metadata auto-filled by Zenodo when GitHub integration is enabled |

## How to publish (two steps, both free, 10 minutes total)

### Step 1 — Enable GitHub ↔ Zenodo integration (code DOI)

This gives you an **automatic DOI** every time you cut a new GitHub Release.

1. Go to https://zenodo.org and click **Sign up** → **"Sign in with GitHub"**.
2. Fill your profile: name **Hassan Hemal**, email **hemalkhan987.1234@gmail.com**.
3. Go to https://zenodo.org/account/settings/github/
4. Find the repository **`hemal-eng/SANKET`** in the list and **flip the switch to ON**.
5. On GitHub, go to https://github.com/hemal-eng/SANKET/releases → **"Create a new release"**:
   - Tag: `v1.0.0` (already pushed — just select it)
   - Title: `SANKET v1.0.0 — Initial Public Release`
   - Description: see below for a suggested text (or copy the Abstract from `SANKET_disclosure.md`)
   - Click **"Publish release"**.
6. Within ~2 minutes Zenodo picks it up, mints a DOI, and sends you a notification.

### Step 2 — Upload the Technical Disclosure PDF (paper DOI)

This gives a **separate DOI for the formal paper** — strongest prior-art form.

1. On https://zenodo.org, click **"New upload"**.
2. Upload file: `SANKET_disclosure.pdf` (in this folder).
3. Fill:
   - **Resource type:** *Publication → Working paper* (or *Preprint*)
   - **Title:** `SANKET: A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written Gesture Recognition`
   - **Authors:** Hassan Hemal
   - **Affiliation:** Embedded Systems Engineer, Bangladesh
   - **Description:** copy from the Abstract section of the PDF
   - **Keywords:** paste the keyword list from `.zenodo.json`
   - **License:** `Creative Commons Attribution 4.0 International` (CC BY 4.0)
   - **Access right:** Open
   - **Related/alternate identifiers:** add `https://github.com/hemal-eng/SANKET` as `is supplement to`
4. Click **"Publish"**. You get a second DOI (for the paper).

### Step 3 — Add DOI badge to your README

Zenodo gives you a Markdown badge after publishing. Paste it near the top
of your main `README.md`:
```markdown
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)
```

Tell me the DOI number and I'll add it for you. ✓

---

## Suggested GitHub Release description (for Step 1.5)

```markdown
# SANKET v1.0.0 — Initial Public Release

**A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written
Gesture Recognition.**

Author: Hassan Hemal <hemalkhan987.1234@gmail.com>

## What's included
- Data-logger firmware for ESP32-S3 (6-second one-shot gesture capture)
- Dual-core on-device TFLite-Micro inference firmware with esp-nn
  ESP32-S3 vector-ISA acceleration
- Python ML pipeline: collector GUI, 1D-CNN training with 24–30x
  augmentation, INT8 quantization, C-header export
- Trained smoke-test model (ami + idle classes, 100 % validation accuracy
  on held-out set)
- Full documentation (architecture, setup, data collection, training,
  deployment, gesture design, future work)
- Hardware BOM: ~US $6-7 (ESP32-S3 + MPU6050)

## Novel contributions
- First open-source Bangla air-written gesture recognition system
  running entirely on an edge microcontroller
- Dual-core sampling + inference architecture keeping 100 Hz IMU
  sampling uninterrupted during TFLM inference
- Position × Style × Repetition data-collection protocol for air-written
  gestures
- Air-written connected full-word (signature-style) gesture encoding
  for Bangla

Licensed under MIT (code) and CC BY 4.0 (technical disclosure).
```

---

## Re-building the PDF

If you edit `SANKET_disclosure.md` and want to regenerate the PDF:

```bash
cd zenodo
/Users/<you>/.../BanglaSign/python/.venv/bin/python build_pdf.py
```

Dependencies: `fpdf2` (already installed in the venv).

## What this protects

- The DOI acts as **worldwide prior art**. Any patent application filed
  after your Zenodo publish date, by anyone, will be rejected at every
  patent office (USPTO, EPO, DPDT, JPO, etc.) if it claims your invention.
- You retain full copyright on the code (MIT allows others to use it;
  they must keep your attribution).
- The CC BY 4.0 on the paper lets academics cite and build on it,
  while you remain the credited inventor forever.

That's about as safe as free gets. For *commercial* exclusivity (where
you want to prevent others from manufacturing SANKET devices), you'd
need to also file a US Provisional Patent (~$75) within 12 months of
this disclosure date. See the main README's "License" section and ask
Hassan for the next steps on that path.
