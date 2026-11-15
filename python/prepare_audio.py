"""
SANKET — voice file preparation for the DFPlayer Mini
=====================================================
Turns the phone recordings of each word into the numbered MP3 files the
DFPlayer Mini plays from its SD card.

  input   The_Audios/Ami.aac, Haan.aac, ... (.aac / .m4a / .wav)
  output  The_Audios/SD_CARD/mp3/0001.mp3 ... 0007.mp3

File number == model class id, so the firmware can call
playMp3Folder(class_id) directly (class 0 = idle has no audio).

Processing per file:
  1. decode to 16-bit mono 44.1 kHz WAV (macOS `afconvert`, else `ffmpeg`)
  2. trim leading/trailing silence below -40 dB of the peak
     (10 ms moving-average envelope, 80 ms padding kept)
  3. peak-normalise to -1 dBFS so every word plays at the same loudness
  4. encode MP3 128 kbps mono with lameenc

Run:
  python prepare_audio.py
  python prepare_audio.py --in ../The_Audios --out ../The_Audios/SD_CARD/mp3
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

try:
    import lameenc
except ImportError:
    sys.exit("❌ lameenc is missing — run:  pip install lameenc")

HERE = Path(__file__).resolve().parent

# Order == model class id (1..7). Must match python/models/labels.json.
ORDER = ["Ami", "Haan", "Dhonnobad", "Pani", "Khabar", "Shahajjo", "Salam"]
INPUT_EXTS = (".aac", ".m4a", ".wav", ".mp3")

SAMPLE_RATE   = 44100
SILENCE_DB    = -40.0
ENVELOPE_S    = 0.010
PAD_S         = 0.080
PEAK_DBFS     = -1.0
BITRATE_KBPS  = 128


def find_input(in_dir: Path, word: str) -> Path | None:
    for ext in INPUT_EXTS:
        for cand in (in_dir / f"{word}{ext}", in_dir / f"{word.lower()}{ext}"):
            if cand.exists():
                return cand
    return None


def decode_to_wav(src: Path, dst: Path) -> None:
    if shutil.which("afconvert"):
        cmd = ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1",
               str(src), str(dst)]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
               "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(dst)]
    else:
        sys.exit("❌ Need either `afconvert` (macOS) or `ffmpeg` to decode audio.")
    subprocess.run(cmd, check=True)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32)
    return x, sr


def trim_silence(x: np.ndarray, sr: int) -> np.ndarray:
    peak = float(np.abs(x).max()) or 1.0
    win = max(1, int(ENVELOPE_S * sr))
    env = np.convolve(np.abs(x), np.ones(win) / win, mode="same")
    loud = np.where(env > peak * 10 ** (SILENCE_DB / 20))[0]
    if loud.size == 0:
        return x
    pad = int(PAD_S * sr)
    return x[max(0, loud[0] - pad): min(len(x), loud[-1] + pad)]


def normalise(x: np.ndarray) -> np.ndarray:
    peak = float(np.abs(x).max()) or 1.0
    return x / peak * 32767 * 10 ** (PEAK_DBFS / 20)


def encode_mp3(x: np.ndarray, sr: int) -> bytes:
    pcm = np.clip(x, -32768, 32767).astype(np.int16).tobytes()
    enc = lameenc.Encoder()
    enc.set_bit_rate(BITRATE_KBPS)
    enc.set_in_sample_rate(sr)
    enc.set_channels(1)
    enc.set_quality(2)
    return enc.encode(pcm) + enc.flush()


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepare SANKET voice files for the DFPlayer SD card.")
    ap.add_argument("--in", dest="in_dir", type=Path, default=HERE.parent / "The_Audios",
                    help="folder with Ami.aac, Haan.aac, ... (default: ../The_Audios)")
    ap.add_argument("--out", dest="out_dir", type=Path,
                    default=HERE.parent / "The_Audios" / "SD_CARD" / "mp3",
                    help="output folder (default: ../The_Audios/SD_CARD/mp3)")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{'file':<10} {'source':<16} {'in (s)':>7} {'out (s)':>8} {'size':>9}")
    print("-" * 54)
    missing = []
    with tempfile.TemporaryDirectory() as tmp:
        for track, word in enumerate(ORDER, start=1):
            src = find_input(args.in_dir, word)
            if src is None:
                missing.append(word)
                continue
            wav = Path(tmp) / f"{word}.wav"
            decode_to_wav(src, wav)
            x, sr = read_wav(wav)
            dur_in = len(x) / sr
            x = normalise(trim_silence(x, sr))
            mp3 = encode_mp3(x, sr)
            out = args.out_dir / f"{track:04d}.mp3"
            out.write_bytes(mp3)
            print(f"{out.name:<10} {src.name:<16} {dur_in:>7.2f} {len(x)/sr:>8.2f} "
                  f"{len(mp3)/1024:>7.1f} KB")

    if missing:
        print(f"\n⚠️  Missing recordings: {', '.join(missing)} (looked in {args.in_dir})")
    print(f"\n✅ Done → {args.out_dir}")
    print("Copy the 'mp3' folder to the root of a FAT32 SD card for the DFPlayer Mini.")


if __name__ == "__main__":
    main()
