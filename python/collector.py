"""
SANKET Data Collector GUI
=========================
A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written
Gesture Recognition.

Connects to the ESP32-S3 data-logger over USB-UART Serial (921600 baud) and:
  • Shows live scrolling 6-channel IMU plot (ax, ay, az in g; gx, gy, gz in °/s)
  • Fires one-shot 6 s recordings on SPACEBAR (or the big button)
  • Shows a preview of the just-recorded gesture + quality metrics
  • Saves to data/<label>/pos<P>_style<S>_rep<N>.npz   (keyboard: S save, R redo)

Run:  python collector.py
"""
import os
import sys
import time
import json
import glob
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

import serial
import serial.tools.list_ports

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QObject
from PySide6.QtGui import QFont, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QComboBox, QLabel, QRadioButton, QButtonGroup, QGroupBox,
    QMessageBox, QFrame, QSizePolicy
)
import pyqtgraph as pg


# ---------- Config ----------
BAUD              = 921600
SAMPLE_RATE_HZ    = 100
FIXED_RECORD_S    = 6.0                                    # must match firmware FIXED_RECORD_SAMPLES
FIXED_RECORD_SMPL = int(FIXED_RECORD_S * SAMPLE_RATE_HZ)   # 600
LIVE_WINDOW_S     = 6.0
LIVE_SAMPLES      = int(LIVE_WINDOW_S * SAMPLE_RATE_HZ)
PLOT_FPS          = 30
DATA_DIR          = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Labels — map numeric id to (english_name, bangla_display, is_target)
# Add more as the project grows; order here defines dropdown order.
LABELS = [
    {"id": 0, "name": "ami",  "bangla": "আমি (air-written)", "target": True},
    {"id": 1, "name": "idle", "bangla": "(random / rest)",  "target": False},
]

# Writing styles — each gesture label is collected across these styles so the
# model sees handwriting variability (we only differentiate styles for the
# target class; idle ignores them in file names).
STYLES = [
    {"id": 1, "name": "S1", "desc": "normal"},
    {"id": 2, "name": "S2", "desc": "slow-careful"},
    {"id": 3, "name": "S3", "desc": "quick-sloppy"},
]

CH_NAMES    = ["ax", "ay", "az", "gx", "gy", "gz"]
CH_UNITS    = ["g",  "g",  "g",  "°/s", "°/s", "°/s"]
CH_COLORS_ACC   = [(255, 90,  90),  (90, 220, 90),  (90, 150, 255)]  # R G B lines
CH_COLORS_GYRO  = [(230, 180, 90),  (210, 90,  220),(90,  220, 220)]


# ---------- Serial reader thread ----------
class SerialReader(QThread):
    """Reads lines from the serial port and emits parsed messages on the main thread."""
    sample      = Signal(str, list)       # ('L' or 'D', [float x6])
    event       = Signal(str, list)       # ('H' | 'C' | 'R' | 'E', [arg strings])
    status      = Signal(str)             # free text (connecting, disconnected, error)
    stopped     = Signal()

    def __init__(self, port: str, baud: int = BAUD, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._stop = False
        self._ser = None

    def stop(self):
        self._stop = True

    def send(self, data: bytes) -> bool:
        """Send bytes to the device. Thread-safe-enough for short commands."""
        try:
            if self._ser and self._ser.is_open:
                self._ser.write(data)
                return True
        except Exception:
            pass
        return False

    def run(self):
        try:
            self.status.emit(f"Opening {self.port} @ {self.baud}…")
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
            self.status.emit(f"Connected: {self.port}")
        except Exception as e:
            self.status.emit(f"ERROR: {e}")
            self.stopped.emit()
            return

        buf = b""
        while not self._stop:
            try:
                chunk = self._ser.read(1024)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode("utf-8", errors="replace").strip()
                    if not s:
                        continue
                    parts = s.split(",")
                    tag = parts[0]
                    if tag in ("L", "D"):
                        if len(parts) >= 7:
                            try:
                                vals = [float(x) for x in parts[1:7]]
                                self.sample.emit(tag, vals)
                            except ValueError:
                                pass
                    else:
                        self.event.emit(tag, parts[1:])
            except serial.SerialException as e:
                self.status.emit(f"Serial error: {e}")
                break
            except Exception as e:
                self.status.emit(f"Read error: {e}")
                break

        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        self.status.emit("Disconnected")
        self.stopped.emit()


# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SANKET — Data Collector")
        self.resize(1200, 820)

        # State
        self.reader: SerialReader | None = None
        self.current_label_idx = 0
        self.current_position  = 1
        self.current_style     = 1
        self.counts = self._scan_counts()   # (name, pos, style) -> int

        # Buffers
        self.live_buf = np.zeros((LIVE_SAMPLES, 6), dtype=np.float32)
        self.live_ptr = 0
        self.live_filled = False

        self.rec_data: list[list[float]] = []  # growing list during record
        self.recording = False
        self.pending   = None  # dict with latest completed recording, waiting Save/Redo

        self._build_ui()
        self._refresh_ui_counts()

        # Plot update timer
        self._plot_timer = QTimer(self)
        self._plot_timer.timeout.connect(self._refresh_plots)
        self._plot_timer.start(int(1000 / PLOT_FPS))

    # ---------- UI construction ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        # ----- Row 1: port / connect -----
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Port:"))
        self.cb_port = QComboBox()
        self.cb_port.setMinimumWidth(260)
        row1.addWidget(self.cb_port)
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedWidth(32)
        self.btn_refresh.clicked.connect(self._refresh_ports)
        row1.addWidget(self.btn_refresh)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._on_connect)
        row1.addWidget(self.btn_connect)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.btn_disconnect.setEnabled(False)
        row1.addWidget(self.btn_disconnect)

        row1.addStretch()
        self.lbl_status = QLabel("● Not connected")
        self.lbl_status.setStyleSheet("color: #888;")
        row1.addWidget(self.lbl_status)
        v.addLayout(row1)

        # ----- Row 2: label + position + style -----
        row2 = QGridLayout()
        row2.setColumnStretch(1, 1)
        row2.setColumnStretch(3, 1)
        row2.setColumnStretch(5, 1)
        row2.addWidget(QLabel("Label:"), 0, 0)
        self.cb_label = QComboBox()
        for i, L in enumerate(LABELS):
            self.cb_label.addItem(f"[{i+1}] {L['name']} — {L['bangla']}")
        self.cb_label.currentIndexChanged.connect(self._on_label_change)
        row2.addWidget(self.cb_label, 0, 1)

        row2.addWidget(QLabel("Position:"), 0, 2)
        pos_box = QWidget(); pos_lay = QHBoxLayout(pos_box); pos_lay.setContentsMargins(0, 0, 0, 0)
        self.pos_group = QButtonGroup(self)
        for i in (1, 2, 3):
            rb = QRadioButton(f"P{i}")
            if i == 1: rb.setChecked(True)
            rb.toggled.connect(lambda checked, pi=i: self._on_pos_change(pi) if checked else None)
            self.pos_group.addButton(rb, i)
            pos_lay.addWidget(rb)
        pos_lay.addStretch()
        row2.addWidget(pos_box, 0, 3)

        row2.addWidget(QLabel("Style:"), 0, 4)
        sty_box = QWidget(); sty_lay = QHBoxLayout(sty_box); sty_lay.setContentsMargins(0, 0, 0, 0)
        self.style_group = QButtonGroup(self)
        for S in STYLES:
            rb = QRadioButton(f"{S['name']} ({S['desc']})")
            if S["id"] == 1: rb.setChecked(True)
            rb.toggled.connect(lambda checked, si=S["id"]: self._on_style_change(si) if checked else None)
            self.style_group.addButton(rb, S["id"])
            sty_lay.addWidget(rb)
        sty_lay.addStretch()
        row2.addWidget(sty_box, 0, 5)
        v.addLayout(row2)

        # ----- Row 3: counters -----
        row3 = QHBoxLayout()
        self.lbl_counts = QLabel("")
        f = QFont();  f.setPointSize(11)
        self.lbl_counts.setFont(f)
        row3.addWidget(self.lbl_counts)
        row3.addStretch()
        v.addLayout(row3)

        # ----- Instructions bar -----
        tip = QLabel(f"Press  SPACE  → air-write আমি (ত + ি, আ, ম) in the air with your wrist "
                     f"— device captures exactly {FIXED_RECORD_S:.1f} s and auto-stops. "
                     f"Then  [S] Save  /  [R] Redo.  Change Position + Style between batches.")
        tip.setStyleSheet("background:#2a2a2a; color:#eee; padding:6px; border-radius:4px;")
        v.addWidget(tip)

        # Big one-shot record button
        self.btn_toggle = QPushButton(f"● RECORD  ({FIXED_RECORD_S:.1f} s)   [SPACE]")
        self.btn_toggle.setMinimumHeight(52)
        f_big = QFont(); f_big.setPointSize(14); f_big.setBold(True)
        self.btn_toggle.setFont(f_big)
        self.btn_toggle.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; border-radius:6px; }"
            "QPushButton:disabled { background:#444; color:#888; }"
        )
        self.btn_toggle.clicked.connect(self._on_toggle_record)
        self.btn_toggle.setEnabled(False)   # enabled only when connected
        v.addWidget(self.btn_toggle)

        # ----- Plots -----
        pg.setConfigOptions(antialias=True, foreground="#dddddd", background="#111111")
        self.plot_accel = pg.PlotWidget(title="Accelerometer (g)")
        self.plot_gyro  = pg.PlotWidget(title="Gyroscope (°/s)")
        for p in (self.plot_accel, self.plot_gyro):
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setMouseEnabled(x=False, y=True)
            p.setLabel("bottom", "time (s)")
            p.setXRange(-LIVE_WINDOW_S, 0)
        self.plot_accel.setYRange(-2.5, 2.5)
        self.plot_gyro.setYRange(-600, 600)
        v.addWidget(self.plot_accel, stretch=2)
        v.addWidget(self.plot_gyro,  stretch=2)

        self.curves = []
        for i in range(3):
            pen = pg.mkPen(color=CH_COLORS_ACC[i], width=2)
            c = self.plot_accel.plot(pen=pen, name=CH_NAMES[i])
            self.curves.append(c)
        for i in range(3):
            pen = pg.mkPen(color=CH_COLORS_GYRO[i], width=2)
            c = self.plot_gyro.plot(pen=pen, name=CH_NAMES[3+i])
            self.curves.append(c)
        self.plot_accel.addLegend(offset=(10, 10))
        self.plot_gyro.addLegend(offset=(10, 10))

        # ----- Preview + Save/Redo -----
        self.preview_box = QGroupBox("Last recording")
        pv = QHBoxLayout(self.preview_box)
        self.lbl_preview = QLabel("No recording yet.")
        self.lbl_preview.setMinimumWidth(500)
        self.lbl_preview.setStyleSheet("padding:6px; font-family:monospace;")
        pv.addWidget(self.lbl_preview)
        pv.addStretch()
        self.btn_save = QPushButton("Save ✓  (S)")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        self.btn_redo = QPushButton("Redo ✗  (R)")
        self.btn_redo.clicked.connect(self._on_redo)
        self.btn_redo.setEnabled(False)
        pv.addWidget(self.btn_save)
        pv.addWidget(self.btn_redo)
        v.addWidget(self.preview_box)

        # Keyboard shortcuts
        QShortcut(QKeySequence("S"), self, activated=self._on_save)
        QShortcut(QKeySequence("R"), self, activated=self._on_redo)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._on_toggle_record)

        self._refresh_ports()

    # ---------- Port handling ----------
    def _refresh_ports(self):
        self.cb_port.clear()
        found = []
        for p in serial.tools.list_ports.comports():
            found.append(p.device)
        # macOS: prefer cu.* over tty.*
        found.sort(key=lambda x: (0 if "cu." in x else 1, x))
        for d in found:
            self.cb_port.addItem(d)
        if not found:
            self.cb_port.addItem("(no serial ports found)")

    def _on_connect(self):
        port = self.cb_port.currentText()
        if not port or "(no serial" in port:
            QMessageBox.warning(self, "No port", "No serial port selected.")
            return
        self.reader = SerialReader(port, BAUD)
        self.reader.sample.connect(self._on_sample)
        self.reader.event.connect(self._on_event)
        self.reader.status.connect(self._on_status)
        self.reader.stopped.connect(self._on_reader_stopped)
        self.reader.start()
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.btn_toggle.setEnabled(True)

    def _on_disconnect(self):
        if self.reader:
            self.reader.stop()

    def _on_reader_stopped(self):
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_toggle.setEnabled(False)
        self.reader = None

    def _on_toggle_record(self):
        """Fire a one-shot recording. Ignored by firmware while already recording."""
        if not self.reader or self.recording:
            return
        ok = self.reader.send(b"T\n")
        if not ok:
            self._on_status("Trigger failed — serial not open")

    def _on_status(self, text: str):
        self.lbl_status.setText(f"● {text}")
        if "Connected" in text:
            self.lbl_status.setStyleSheet("color: #4caf50;")
        elif "ERROR" in text or "error" in text:
            self.lbl_status.setStyleSheet("color: #ef5350;")
        else:
            self.lbl_status.setStyleSheet("color: #bbb;")

    # ---------- Serial events ----------
    def _on_sample(self, tag: str, vals: list):
        # Append to live buffer regardless (used for live plot in idle)
        self.live_buf[self.live_ptr] = vals
        self.live_ptr = (self.live_ptr + 1) % LIVE_SAMPLES
        if self.live_ptr == 0:
            self.live_filled = True

        if tag == "D" and self.recording:
            self.rec_data.append(vals)

    def _on_event(self, tag: str, args: list):
        if tag == "H":
            self._on_status("Device ready (handshake received)")
        elif tag == "C":
            if args and args[0] == "START":
                self._on_status("Calibrating… keep still")
            elif args and args[0] == "DONE":
                self._on_status(f"Calibrated (offsets logged)")
        elif tag == "R":
            if args and args[0] == "START":
                self.recording = True
                self.rec_data = []
                self._on_status("● RECORDING…")
                self.lbl_status.setStyleSheet("color: #ff5252; font-weight: bold;")
                # Disable save/redo while recording in progress
                self.btn_save.setEnabled(False)
                self.btn_redo.setEnabled(False)
                # Disabled & red while in progress — no stop action
                self.btn_toggle.setEnabled(False)
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background:#c62828; color:white; border-radius:6px; }"
                    "QPushButton:disabled { background:#c62828; color:white; border-radius:6px; }"
                )
            elif args and args[0] == "STOP":
                self.recording = False
                # Back to green ready state
                self.btn_toggle.setEnabled(True)
                self.btn_toggle.setText(f"● RECORD  ({FIXED_RECORD_S:.1f} s)   [SPACE]")
                self.btn_toggle.setStyleSheet(
                    "QPushButton { background:#2e7d32; color:white; border-radius:6px; }"
                    "QPushButton:disabled { background:#444; color:#888; }"
                )
                try:
                    reported_n = int(args[1]) if len(args) > 1 else len(self.rec_data)
                except ValueError:
                    reported_n = len(self.rec_data)
                self._on_recording_done(reported_n)
        elif tag == "E":
            self._on_status(f"Device error: {','.join(args)}")

    # ---------- Recording done -> preview ----------
    def _on_recording_done(self, reported_n: int):
        data = np.asarray(self.rec_data, dtype=np.float32)
        n = data.shape[0]
        if n < FIXED_RECORD_SMPL - 10:
            self.lbl_preview.setText(
                f"Recording too short: {n}/{FIXED_RECORD_SMPL} samples "
                f"(serial drops?). Redo.")
            self.pending = None
            self.btn_save.setEnabled(False)
            self.btn_redo.setEnabled(False)
            self._on_status("Recording too short — ignored")
            return

        duration_s = n / SAMPLE_RATE_HZ
        acc_mag = np.linalg.norm(data[:, :3], axis=1)
        gyr_mag = np.linalg.norm(data[:, 3:], axis=1)
        peak_a  = float(acc_mag.max())
        peak_g  = float(gyr_mag.max())

        # Air-writing is slow smooth motion (not sharp spikes). No motion
        # threshold here — ANY captured 6 s window is a valid sample. The
        # model learns from the shape, not the magnitude.
        quality = "🟢 Captured"

        label = LABELS[self.current_label_idx]
        txt = (f"Label: {label['name']} ({label['bangla']})   "
               f"Position: P{self.current_position}   "
               f"Style: S{self.current_style}\n"
               f"Duration: {duration_s:.2f} s ({n} samples @ {SAMPLE_RATE_HZ} Hz)\n"
               f"Peak |a|: {peak_a:.2f} g    Peak |ω|: {peak_g:.1f} °/s\n"
               f"Quality: {quality}")
        self.lbl_preview.setText(txt)
        self.pending = {
            "data": data, "label": label, "position": self.current_position,
            "style": self.current_style,
            "duration_s": duration_s, "peak_a": peak_a, "peak_g": peak_g,
            "sample_rate_hz": SAMPLE_RATE_HZ, "quality": quality,
        }
        self.btn_save.setEnabled(True)
        self.btn_redo.setEnabled(True)
        self._on_status(f"Ready — press S to save, R to redo")

    # ---------- Save / Redo ----------
    def _on_save(self):
        if not self.pending:
            return
        label_name = self.pending["label"]["name"]
        pos        = self.pending["position"]
        style      = self.pending["style"]
        key        = (label_name, pos, style)
        n_existing = self.counts.get(key, 0)
        new_idx    = n_existing + 1
        out_dir    = DATA_DIR / label_name
        out_dir.mkdir(parents=True, exist_ok=True)
        fname      = out_dir / f"pos{pos}_style{style}_rep{new_idx:03d}.npz"

        np.savez_compressed(
            fname,
            data=self.pending["data"],
            label=label_name,
            label_bangla=self.pending["label"]["bangla"],
            position=pos,
            style=style,
            sample_rate_hz=SAMPLE_RATE_HZ,
            duration_s=self.pending["duration_s"],
            peak_a=self.pending["peak_a"],
            peak_g=self.pending["peak_g"],
            quality=self.pending["quality"],
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
        )
        self.counts[key] = new_idx
        self._refresh_ui_counts()
        self._on_status(f"Saved {fname.name}")
        self.pending = None
        self.btn_save.setEnabled(False)
        self.btn_redo.setEnabled(False)

    def _on_redo(self):
        if not self.pending:
            return
        self._on_status("Discarded — ready for next recording")
        self.pending = None
        self.btn_save.setEnabled(False)
        self.btn_redo.setEnabled(False)

    # ---------- Counters ----------
    def _scan_counts(self) -> dict:
        counts = {}
        for L in LABELS:
            # New-style files
            for pos in (1, 2, 3):
                for style in (1, 2, 3):
                    pat = str(DATA_DIR / L["name"] / f"pos{pos}_style{style}_rep*.npz")
                    counts[(L["name"], pos, style)] = len(glob.glob(pat))
            # Legacy (pre-style) files are counted under style=0 so they still
            # show up in totals but don't collide with new filenames.
            for pos in (1, 2, 3):
                legacy = glob.glob(str(DATA_DIR / L["name"] / f"pos{pos}_rep*.npz"))
                if legacy:
                    counts[(L["name"], pos, 0)] = len(legacy)
        return counts

    def _refresh_ui_counts(self):
        parts = []
        for L in LABELS:
            per_pos_tot = []
            for pos in (1, 2, 3):
                s_counts = [self.counts.get((L["name"], pos, s), 0) for s in (1, 2, 3)]
                legacy   = self.counts.get((L["name"], pos, 0), 0)
                pt = sum(s_counts) + legacy
                per_pos_tot.append((pt, s_counts, legacy))
            tot = sum(pt for pt, _, _ in per_pos_tot)
            cells = []
            for i, (pt, s_counts, legacy) in enumerate(per_pos_tot, start=1):
                sub = f"S1:{s_counts[0]} S2:{s_counts[1]} S3:{s_counts[2]}"
                if legacy:
                    sub += f" L:{legacy}"
                cells.append(f"P{i}[{sub}]")
            parts.append(f"{L['name']}: {tot}  " + " ".join(cells))
        self.lbl_counts.setText("    ".join(parts))

    def _on_label_change(self, idx: int):
        self.current_label_idx = idx

    def _on_pos_change(self, pos: int):
        self.current_position = pos

    def _on_style_change(self, style: int):
        self.current_style = style

    # ---------- Plot refresh ----------
    def _refresh_plots(self):
        # If recording, show the growing recording.  Otherwise show rolling live buffer.
        if self.recording and len(self.rec_data) > 0:
            data = np.asarray(self.rec_data, dtype=np.float32)
            n = data.shape[0]
            t = (np.arange(n) - n) / SAMPLE_RATE_HZ   # x goes from -n/fs to 0
        else:
            if self.live_filled:
                # Unwrap ring buffer so the newest sample is at index -1
                a = self.live_buf[self.live_ptr:]
                b = self.live_buf[:self.live_ptr]
                data = np.concatenate([a, b], axis=0)
            else:
                data = self.live_buf[:self.live_ptr]
                if data.shape[0] < 2:
                    return
            n = data.shape[0]
            t = np.linspace(-n / SAMPLE_RATE_HZ, 0, n)

        for i in range(6):
            self.curves[i].setData(t, data[:, i])


# ---------- main ----------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Dark palette
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.Window,        QColor(30, 30, 30))
    pal.setColor(QPalette.WindowText,    QColor(230, 230, 230))
    pal.setColor(QPalette.Base,          QColor(20, 20, 20))
    pal.setColor(QPalette.AlternateBase, QColor(40, 40, 40))
    pal.setColor(QPalette.Text,          QColor(230, 230, 230))
    pal.setColor(QPalette.Button,        QColor(55, 55, 55))
    pal.setColor(QPalette.ButtonText,    QColor(230, 230, 230))
    pal.setColor(QPalette.Highlight,     QColor(0, 120, 212))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
