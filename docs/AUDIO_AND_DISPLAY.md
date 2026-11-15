# SANKET — Bangla Display and Spoken Audio

How SANKET shows the detected word in Bangla script on a 0.96" OLED and
speaks it aloud through a DFPlayer Mini.

```
detected word (class id N, confidence ≥ 0.75)
        │
        ├──► OLED (Wire1, GPIO 41/42) ── big Bangla word + confidence
        │
        └──► DFPlayer (UART2, GPIO 17/18) ── plays /mp3/000N.mp3 ──► speaker
```

---

## Part A — OLED display

### A.1 Hardware and libraries

| Item | Value |
|---|---|
| Panel | SSD1306, 0.96", 128 × 64, I²C address 0x3C |
| Bus | `Wire1`, SDA = GPIO 41, SCL = GPIO 42, 400 kHz |
| Driver | `adafruit/Adafruit SSD1306` + `adafruit/Adafruit GFX Library` |
| Bangla rendering | [`mamunul/BanglaText`](https://github.com/mamunul/BanglaText) (MIT) — renders Unicode Bangla with correct conjuncts and vowel signs |
| Font | `BanglaMNRegular_25pt.h` (from the BanglaText library, stored in `firmware_infer/src/`, kept in flash) |

English text (status header, footer) uses the normal Adafruit GFX font.

### A.2 How a Bangla word reaches the screen

The BanglaText renderer does not draw directly to the display. It calls a
pixel callback for every lit pixel, and it lays each word out **along the
Y axis** (top to bottom). SANKET uses that in four steps:

```
"পানি" ──► renderText()  ──► pixel callback ──► off-screen GFXcanvas1(40 × 128)
                                                         │
                       measure bounding box (minx..maxx, miny..maxy)
                                                         │
                       copy each lit pixel, rotated 270°, centred in
                       the band between header and footer (y = 12 … 54)
                                                         │
                                                         ▼
                                             OLED (128 × 64)
```

1. **Render off-screen** into a `GFXcanvas1(40, 128)` — tall, because words
   run along Y.
2. **Measure** the bounding box of the lit pixels.
3. **Rotate 270°** while copying: screen x = `dx + (y − miny)`,
   screen y = `dy + (maxx − x)`. The rotation lines the Bangla up with the
   panel's ribbon side; the English text stays in the default orientation.
4. **Centre** the word horizontally and inside the band y = 12 … 54.

The code is `displayBangla()` in `firmware_infer/src/main.cpp`.

### A.3 Measured word sizes (25 pt font, before rotation)

| Word | Width × length (px) |
|---|---|
| আমি | 24 × 49 |
| হ্যাঁ | 24 × 31 |
| পানি | 24 × 45 |
| খাবার | 20 × 58 |
| সালাম | 20 × 63 |
| সাহায্য | 20 × 68 |
| ধন্যবাদ | 20 × 73 |
| বিশ্রাম | 26 × 60 |
| লিখুন | 28 × 55 |
| লিখছেন | 25 × 81 |

After the 270° rotation the "length" runs across the 128 px screen width,
so every word fits. (An earlier `192 × 64` canvas was too short and cut
the long words in half.)

### A.4 Screen layout

```
┌──────────────────────────────┐  y = 0
│ DETECTED  92%                │  header (English, size 1)
├──────────────────────────────┤  y = 10  line
│                              │
│            পানি              │  Bangla word, band y = 12 … 54
│                              │
│ pani                         │  footer (English), y = 55
└──────────────────────────────┘  y = 63
```

### A.5 Screens

| When | Header | Middle (Bangla) | Footer |
|---|---|---|---|
| Boot | `SANKET boot...` | — | — |
| Ready (idle) | `SANKET  * ready` | **লিখুন** ("write") | `move wrist to start` |
| Capturing | `* CAPTURING` | **লিখছেন** ("writing…") | `energy 234 /s` |
| Detected (≥ 75 %) | `DETECTED  92%` | the word, e.g. **পানি** | `pani` |
| Unclear (< 75 % or idle) | `unclear   55% khabar` | top word | class name |

The result stays on screen through the cooldown and returns to the ready
screen when the device re-arms.

---

## Part B — Spoken audio

### B.1 Hardware

| Item | Value |
|---|---|
| Module | DFPlayer Mini (`dfrobot/DFRobotDFPlayerMini` library) |
| Bus | UART2, 9600 baud — ESP32 TX GPIO 17 → 1 kΩ → DFPlayer RX; ESP32 RX GPIO 18 ← DFPlayer TX |
| BUSY | GPIO 16 (LOW while playing) |
| Power | 5 V, 100–470 µF capacitor across VCC/GND |
| Speaker | 3 W, 4–8 Ω on SPK_1 / SPK_2 |
| Volume | `AUDIO_VOLUME = 25` (0–30) in `main.cpp` |

### B.2 Track numbering: class id = track number

| Class id | Class | Track file | Spoken |
|---|---|---|---|
| 0 | idle | — | (never played) |
| 1 | ami | `/mp3/0001.mp3` | আমি |
| 2 | haan | `/mp3/0002.mp3` | হ্যাঁ |
| 3 | dhonnobad | `/mp3/0003.mp3` | ধন্যবাদ |
| 4 | pani | `/mp3/0004.mp3` | পানি |
| 5 | khabar | `/mp3/0005.mp3` | খাবার |
| 6 | shahajjo | `/mp3/0006.mp3` | সাহায্য |
| 7 | salam | `/mp3/0007.mp3` | আস-সালামু আলাইকুম |

The firmware calls `playMp3Folder(class_id)` — no lookup table needed.

### B.3 Recording the voices

1. Use any phone voice recorder (Samsung Voice Recorder, Google Recorder…).
2. Quiet room, fan off, phone ~20 cm from the mouth.
3. **One recording per word**: ~1 s silence → the word, clearly → ~1 s silence.
4. Name the files `Ami.aac`, `Haan.aac`, `Dhonnobad.aac`, `Pani.aac`,
   `Khabar.aac`, `Shahajjo.aac`, `Salam.aac` and put them in
   `The_Audios/`.

The original recordings used in SANKET are 1.6–2.7 s long.

### B.4 Converting to DFPlayer-ready MP3s

The DFPlayer cannot decode AAC, so the recordings are converted with
`python/prepare_audio.py`. For each word it:

1. Decodes the `.aac` with macOS `afconvert` (to 16-bit, 44.1 kHz, mono WAV).
2. Trims leading/trailing silence below **−40 dB** (relative to the peak),
   keeping **80 ms** of padding.
3. Normalises the peak to **−1 dBFS** so all words are equally loud.
4. Encodes **44.1 kHz mono 128 kbps MP3** with `lameenc`.
5. Writes `0001.mp3` … `0007.mp3` in class order.

```bash
cd python
source .venv/bin/activate
pip install lameenc
python prepare_audio.py
```

Listen to the results before copying:

```bash
cd ../The_Audios/SD_CARD/mp3 && for f in *.mp3; do echo "$f"; afplay "$f"; done
```

### B.5 Preparing the microSD card

1. **Format** in Disk Utility (View → Show All Devices → select the card
   device → Erase): Format **MS-DOS (FAT)**, Scheme **Master Boot Record**.
   Cards up to 32 GB work (SANKET uses 16 GB).
2. **Copy** the `mp3` folder to the card root:

```bash
cp -R The_Audios/SD_CARD/mp3 /Volumes/SANKET/
```

3. **Remove macOS hidden files** (the DFPlayer counts them as tracks) and
   stop Spotlight indexing the card:

```bash
mdutil -i off /Volumes/SANKET
dot_clean -m /Volumes/SANKET
find /Volumes/SANKET -name "._*" -delete
rm -rf /Volumes/SANKET/.Spotlight-V100 /Volumes/SANKET/.fseventsd /Volumes/SANKET/.Trashes
ls -la /Volumes/SANKET/mp3/
diskutil eject /Volumes/SANKET
```

(Replace `SANKET` with your card's volume name.) Final layout:

```
SD card
└── mp3/
    ├── 0001.mp3   আমি
    ├── 0002.mp3   হ্যাঁ
    ├── 0003.mp3   ধন্যবাদ
    ├── 0004.mp3   পানি
    ├── 0005.mp3   খাবার
    ├── 0006.mp3   সাহায্য
    └── 0007.mp3   আস-সালামু আলাইকুম
```

### B.6 Playback rules

| Rule | Behaviour |
|---|---|
| Speak only real detections | Top class is **not idle** and confidence **≥ 0.75**. Unclear results are silent. |
| Once per word | Each detection plays its track once; writing the same word again speaks it again. |
| Screen and sound together | The play command is sent just before the OLED update. |
| No re-arm while speaking | During `COOLDOWN` the timer is held while BUSY is LOW (plus a 0.5 s grace after the command, because BUSY lags ~100–300 ms). Arm movement while the speaker talks cannot start a capture. |
| Re-arm after audio | The device returns to `IDLE` **1 s after the audio ends**. |
| Missing module | If the DFPlayer does not answer at boot, the device keeps running display-only. |

### B.7 `audio.h` API

| Function | Description |
|---|---|
| `bool audioInit(int rx, int tx, int busy, uint8_t volume)` | Starts UART2 and the DFPlayer (~2.5 s). Returns `false` if the module does not answer. |
| `bool audioReady()` | `true` if the DFPlayer is online |
| `int audioFileCount()` | Files the DFPlayer sees on the card (`-1` if offline or not ready) |
| `void audioPlay(int track)` | Plays `/mp3/000<track>.mp3`; ignored if offline or `track < 1` |
| `bool audioActive()` | `true` while a word is playing (BUSY LOW), and for 0.5 s right after `audioPlay()` |

### B.8 Testing audio on its own

`firmware_infer/src/test/main_dfplayer_phase1_test.cpp` plays all seven
words on boot and accepts serial keys (115200 baud): `1`–`7` play a word,
`a` all, `+`/`-` volume, `s` stop, `?` status. See
[`DEPLOYMENT.md`](DEPLOYMENT.md) §9 for how to swap it in.
