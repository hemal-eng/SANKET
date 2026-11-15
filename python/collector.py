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
    QMessageBox, QFrame, QSizePolicy, QSlider, QScrollArea
)
import pyqtgraph as pg


# ---------- Config ----------
BAUD              = 921600
SAMPLE_RATE_HZ    = 100
# FIXED 6 s uniform recording across all words — matches the original Ami
# regime, so no padding or resampling is needed at training time. The slider
# is locked (visible but disabled) so you can't accidentally change it.
FIXED_DURATION_S  = 6.0
MIN_DURATION_S    = FIXED_DURATION_S
MAX_DURATION_S    = FIXED_DURATION_S
DEFAULT_DURATION_S= FIXED_DURATION_S
LIVE_WINDOW_S     = 6.0
LIVE_SAMPLES      = int(LIVE_WINDOW_S * SAMPLE_RATE_HZ)
PLOT_FPS          = 30
DATA_DIR          = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Labels — one dict per class the model will learn.
# All target words use the SAME 6.0 s window. Do the gesture at your natural
# pace; hold wrist still for the remaining time. The model learns to ignore
# the trailing stillness exactly like it did for the smoke-test Ami.
LABELS = [
    {"id": 0, "name": "ami",       "bangla": "আমি (I)",                "target": True,  "default_duration_s": 6.0,  "hint": "air-write আমি then hold still until 6 s"},
    {"id": 1, "name": "haan",      "bangla": "হ্যাঁ (yes)",             "target": True,  "default_duration_s": 6.0,  "hint": "air-write হ্যাঁ then hold still until 6 s"},
    {"id": 2, "name": "dhonnobad", "bangla": "ধন্যবাদ (thank you)",      "target": True,  "default_duration_s": 6.0,  "hint": "air-write ধন্যবাদ then hold still until 6 s"},
    {"id": 3, "name": "pani",      "bangla": "পানি (water)",            "target": True,  "default_duration_s": 6.0,  "hint": "air-write পানি then hold still until 6 s"},
    {"id": 4, "name": "khabar",    "bangla": "খাবার (food)",            "target": True,  "default_duration_s": 6.0,  "hint": "air-write খাবার then hold still until 6 s"},
    {"id": 5, "name": "shahajjo", "bangla": "সাহায্য (help)",         "target": True,  "default_duration_s": 6.0,  "hint": "air-write সাহায্য then hold still until 6 s"},
    {"id": 6, "name": "salam",    "bangla": "সালাম (Assalamu Alaikum)", "target": True,  "default_duration_s": 6.0,  "hint": "air-write সালাম then hold still until 6 s"},
    {"id": 7, "name": "idle",      "bangla": "(random / rest)",       "target": False, "default_duration_s": 6.0,  "hint": "random hand movements for the full 6 s"},
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
        # Start modest so it fits a 13" MacBook; user can resize up freely.
        self.resize(980, 680)
        self.setMinimumSize(640, 480)

        # State
        self.reader: SerialReader | None = None
        self.current_label_idx = 0
        self.current_position  = 1
        self.current_style     = 1
        self.current_duration_s = DEFAULT_DURATION_S
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
        # Prime hint + slider for the first label
        self._on_label_change(0)

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

        # ----- Session panel (scrollable, fixed max height) -----
        # Houses Label + Position + Style + Counters so the long list of 11
        # classes × 3 pos × 3 styles doesn't blow up the whole window.
        session_box = QGroupBox("Session")
        session_outer = QVBoxLayout(session_box)
        session_outer.setContentsMargins(6, 10, 6, 6)
        session_outer.setSpacing(4)

        session_scroll = QScrollArea()
        session_scroll.setWidgetResizable(True)
        session_scroll.setFrameShape(QFrame.NoFrame)
        session_scroll.setMinimumHeight(140)
        session_scroll.setMaximumHeight(230)   # <-- panel never bloats more than this
        session_outer.addWidget(session_scroll)

        session_inner = QWidget()
        session_scroll.setWidget(session_inner)
        si = QVBoxLayout(session_inner)
        si.setContentsMargins(2, 2, 2, 2)
        si.setSpacing(6)

        # Row A: Label + Position + Style
        rowA = QGridLayout()
        rowA.setColumnStretch(1, 1)
        rowA.setColumnStretch(3, 1)
        rowA.setColumnStretch(5, 1)
        rowA.addWidget(QLabel("Label:"), 0, 0)
        self.cb_label = QComboBox()
        for i, L in enumerate(LABELS):
            self.cb_label.addItem(f"[{i+1}] {L['name']} — {L['bangla']}")
        self.cb_label.currentIndexChanged.connect(self._on_label_change)
        rowA.addWidget(self.cb_label, 0, 1)

        rowA.addWidget(QLabel("Position:"), 0, 2)
        pos_box = QWidget(); pos_lay = QHBoxLayout(pos_box); pos_lay.setContentsMargins(0, 0, 0, 0)
        self.pos_group = QButtonGroup(self)
        for i in (1, 2, 3):
            rb = QRadioButton(f"P{i}")
            if i == 1: rb.setChecked(True)
            rb.toggled.connect(lambda checked, pi=i: self._on_pos_change(pi) if checked else None)
            self.pos_group.addButton(rb, i)
            pos_lay.addWidget(rb)
        pos_lay.addStretch()
        rowA.addWidget(pos_box, 0, 3)

        rowA.addWidget(QLabel("Style:"), 0, 4)
        sty_box = QWidget(); sty_lay = QHBoxLayout(sty_box); sty_lay.setContentsMargins(0, 0, 0, 0)
        self.style_group = QButtonGroup(self)
        for S in STYLES:
            rb = QRadioButton(f"{S['name']} ({S['desc']})")
            if S["id"] == 1: rb.setChecked(True)
            rb.toggled.connect(lambda checked, si_=S["id"]: self._on_style_change(si_) if checked else None)
            self.style_group.addButton(rb, S["id"])
            sty_lay.addWidget(rb)
        sty_lay.addStretch()
        rowA.addWidget(sty_box, 0, 5)
        si.addLayout(rowA)

        # Row B: counters, pre-formatted monospace grid, scrolls inside this box
        self.lbl_counts = QLabel("")
        f_mono = QFont("Menlo"); f_mono.setPointSize(10)
        self.lbl_counts.setFont(f_mono)
        self.lbl_counts.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.lbl_counts.setStyleSheet("padding:2px 4px;")
        si.addWidget(self.lbl_counts)
        si.addStretch()

        v.addWidget(session_box)

        # ----- Row 2b: duration (LOCKED at 6 s for uniform training) -----
        row2b = QHBoxLayout()
        row2b.addWidget(QLabel("Duration:"))
        self.lbl_duration = QLabel(f"🔒 {int(FIXED_DURATION_S)} s  (locked — uniform dataset)")
        f_dur = QFont(); f_dur.setPointSize(11); f_dur.setBold(True)
        self.lbl_duration.setFont(f_dur)
        self.lbl_duration.setStyleSheet("color:#ffcc80;")
        row2b.addWidget(self.lbl_duration)
        row2b.addStretch(1)
        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#8ab4f8; font-style:italic;")
        self.lbl_hint.setWordWrap(True)
        row2b.addWidget(self.lbl_hint, stretch=3)
        v.addLayout(row2b)
        # No slider — keep attribute for compatibility with handlers.
        self.sl_duration = None

        # (counters moved into the scrollable Session panel above)

        # ----- Instructions bar -----
        tip = QLabel("Press  SPACE  →  do the gesture  →  hold wrist still until the 6 s window ends. "
                     "Every word records for EXACTLY 6.0 s so every sample has the same shape "
                     "(matches the Ami smoke-test regime that hit 100% accuracy).  "
                     "[S] Save  /  [R] Redo.")
        tip.setStyleSheet("background:#2a2a2a; color:#eee; padding:6px; border-radius:4px;")
        v.addWidget(tip)

        # Big one-shot record button
        self.btn_toggle = QPushButton(f"● RECORD  ({int(DEFAULT_DURATION_S)} s)   [SPACE]")
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
            p.setMinimumHeight(130)              # keeps plots usable even on small windows
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
        self.lbl_preview.setStyleSheet("padding:6px; font-family:monospace;")
        self.lbl_preview.setWordWrap(True)
        pv.addWidget(self.lbl_preview, stretch=1)
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
    def _port_score(self, p):
        """Lower = better match for the ESP32-S3's USB-UART bridge.
        Keeps Bluetooth and random /dev/cu.* devices at the bottom."""
        name = p.device.lower()
        desc = (p.description or "").lower()
        # 1. Known USB-UART bridges used by ESP32 dev boards
        if any(k in name for k in ("wchusbserial", "slab_usbtoart", "usbserial", "silabs")):
            return 0
        if any(k in desc for k in ("ch34", "ch9102", "cp210", "ftdi", "silicon labs",
                                   "usb single serial", "usb-serial")):
            return 0
        # 2. ESP32-S3 native-USB CDC (less common in this project but valid)
        if "usbmodem" in name:
            return 1
        # 3. Bluetooth — Mac shows a bunch of these and they're never our device
        if any(k in name for k in ("bluetooth", "blth", "aweig", "incoming")):
            return 9
        # 4. tty.* (prefer cu.* over tty.*)
        if "tty." in name:
            return 7
        return 5

    def _refresh_ports(self):
        self.cb_port.clear()
        ports = sorted(serial.tools.list_ports.comports(), key=self._port_score)
        if not ports:
            self.cb_port.addItem("(no serial ports found)")
            return
        for p in ports:
            desc = p.description or ""
            if desc and desc.lower() != "n/a":
                label = f"{p.device}   ({desc})"
            else:
                label = p.device
            # Store the actual device path as userData; label can be prettier.
            self.cb_port.addItem(label, userData=p.device)

    def _on_connect(self):
        # Prefer the device path stored as userData (set by _refresh_ports);
        # fall back to currentText for the "no ports found" placeholder.
        port = self.cb_port.currentData()
        if not port:
            text = self.cb_port.currentText()
            if not text or "(no serial" in text:
                QMessageBox.warning(self, "No port", "No serial port selected.")
                return
            port = text
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
        """Fire a one-shot recording with the current slider duration."""
        if not self.reader or self.recording:
            return
        samples = int(round(self.current_duration_s * SAMPLE_RATE_HZ))
        cmd = f"T{samples}\n".encode("ascii")
        ok = self.reader.send(cmd)
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
                self.btn_toggle.setText(f"● RECORD  ({int(self.current_duration_s)} s)   [SPACE]")
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
        expected = int(round(self.current_duration_s * SAMPLE_RATE_HZ))
        if n < expected - 10:
            self.lbl_preview.setText(
                f"Recording too short: {n}/{expected} samples "
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
        """Compact multi-line table: one line per word, aligned columns.
        Looks like:
            Word         Tot   P1 S1/S2/S3   P2 S1/S2/S3   P3 S1/S2/S3
            ami           45      5/ 5/ 5       5/ 5/ 5       5/ 5/ 5
            tumi           0      0/ 0/ 0       0/ 0/ 0       0/ 0/ 0
            …
        """
        header = (f"{'Word':<11}{'Tot':>4}   "
                  f"{'P1 S1/S2/S3':<14}{'P2 S1/S2/S3':<14}{'P3 S1/S2/S3':<14}")
        lines = [header, "─" * (len(header) - 4)]
        grand_total = 0
        for L in LABELS:
            name = L["name"]
            p_parts = []
            tot = 0
            for pos in (1, 2, 3):
                s_counts = [self.counts.get((name, pos, s), 0) for s in (1, 2, 3)]
                legacy   = self.counts.get((name, pos, 0), 0)
                tot += sum(s_counts) + legacy
                base = f"{s_counts[0]:>2}/{s_counts[1]:>2}/{s_counts[2]:>2}"
                if legacy:
                    base += f"+{legacy}"
                p_parts.append(f"{base:<14}")
            grand_total += tot
            lines.append(f"{name:<11}{tot:>4}   " + "".join(p_parts))
        lines.append("─" * (len(header) - 4))
        lines.append(f"{'TOTAL':<11}{grand_total:>4}")
        self.lbl_counts.setText("\n".join(lines))

    def _on_label_change(self, idx: int):
        self.current_label_idx = idx
        L = LABELS[idx]
        # Duration is locked to 6s — just show the hint for this word
        self.lbl_hint.setText(f"✏️  {L.get('hint', '')}")

    def _on_pos_change(self, pos: int):
        self.current_position = pos

    def _on_style_change(self, style: int):
        self.current_style = style

    def _on_duration_change(self, value: int):
        # Slider removed — duration is locked. Kept for signal compatibility.
        self.current_duration_s = float(FIXED_DURATION_S)

    # ---------- Clean shutdown ----------
    def closeEvent(self, event):
        """Stop and join the SerialReader thread BEFORE Qt destroys the
        QObject tree. Otherwise QThread's destructor sees a still-running
        thread and aborts with exit code 134."""
        try:
            if self.reader is not None:
                self.reader.stop()
                self.reader.wait(2000)
                self.reader = None
        except Exception:
            pass
        super().closeEvent(event)

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
