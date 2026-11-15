"""
SANKET — Host-side Live Inference GUI (auto motion-bracketed capture)
=====================================================================
A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written
Gesture Recognition.

This GUI is a HOST-SIDE debugging / validation tool. In normal operation
the trained model runs ON the ESP32-S3 (see firmware_infer/).

Pipeline — AUTO motion-bracketed capture
----------------------------------------
On connect the GUI runs a 2 s CALIBRATION period: user holds still while
the GUI measures the baseline gyro noise. Trigger threshold = baseline
+ margin (auto-set, no slider needed).

After that the state machine is:

  CALIBRATING (2 s) → IDLE
     |
  IDLE (motion > threshold)  → RECORDING
     |                          |
     |                       (still moving? keep going)
     |                          |
     |                       motion drops for ~0.4 s → END
     |                          |
     |                       zero-pad to WINDOW → classify → COOLDOWN
     |                                                          |
     +--------------------- COOLDOWN (1 s over) ----------------+

Zero-padding matches training exactly: `train.py` pads shorter samples
to WINDOW at the end, so the model has seen this shape during training.

Run:  python infer_gui.py
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from collections import deque

import numpy as np

import serial
import serial.tools.list_ports

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QComboBox, QLabel, QGroupBox, QProgressBar, QTextEdit,
    QDoubleSpinBox, QScrollArea
)
import pyqtgraph as pg

try:
    from tflite_runtime.interpreter import Interpreter  # type: ignore
except ImportError:
    import tensorflow as tf  # noqa: E402
    Interpreter = tf.lite.Interpreter


# ---------- Config ----------
BAUD              = 921600
SAMPLE_RATE_HZ    = 100
WINDOW            = 600          # overridden from norm.json at startup
PLOT_FPS          = 30

# Auto-calibration
CAL_DURATION_S    = 2.0          # "hold still" period after connect
CAL_MARGIN_MULT   = 6.0          # threshold = baseline + mult * std
CAL_MIN_THRESH    = 40.0         # floor — don't trigger on tiny tremor
CAL_FALLBACK      = 150.0        # Hassan's tested value if cal fails

# Capture bounds
MIN_CAPTURE_S     = 0.5
MAX_CAPTURE_S     = 3.0          # user-adjustable in UI
STOP_SETTLE_S     = 0.4          # motion must stay below threshold this long to end
COOLDOWN_S        = 1.0

# Rolling window for energy smoothing
ENERGY_WIN        = 10           # 100 ms

HERE       = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
MODEL_PATH = MODELS_DIR / "sanket_float32.tflite"
NORM_PATH  = MODELS_DIR / "norm.json"
LABELS_PATH= MODELS_DIR / "labels.json"

CH_NAMES        = ["ax", "ay", "az", "gx", "gy", "gz"]
CH_COLORS_ACC   = [(255, 90,  90),  (90, 220, 90),  (90, 150, 255)]
CH_COLORS_GYRO  = [(230, 180, 90),  (210, 90,  220),(90,  220, 220)]
CLASS_COLORS    = {
    "idle":      "#90a4ae",
    "ami":       "#4caf50",
    "haan":      "#ab47bc",
    "dhonnobad": "#fbc02d",
    "pani":      "#42a5f5",
    "khabar":    "#ff7043",
    "shahajjo":  "#8d6e63",
    "salam":     "#66bb6a",
}

# States
STATE_WAITING     = "WAITING"      # no stream yet
STATE_CALIBRATING = "CALIBRATING"  # 2s baseline sampling
STATE_IDLE        = "IDLE"         # armed, waiting for motion
STATE_RECORDING   = "RECORDING"    # capturing (variable length)
STATE_COOLDOWN    = "COOLDOWN"     # showing result briefly


# ---------- Serial reader (same as collector) ----------
class SerialReader(QThread):
    sample  = Signal(list)
    event   = Signal(str)
    status  = Signal(str)
    stopped = Signal()

    def __init__(self, port, baud=BAUD, parent=None):
        super().__init__(parent)
        self.port = port; self.baud = baud
        self._stop = False; self._ser = None

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self.status.emit(f"Opening {self.port} @ {self.baud}…")
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
            self.status.emit(f"Connected: {self.port}")
        except Exception as e:
            self.status.emit(f"ERROR: {e}")
            self.stopped.emit(); return

        buf = b""
        while not self._stop:
            try:
                chunk = self._ser.read(2048)
                if not chunk: continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode("utf-8", errors="replace").strip()
                    if not s: continue
                    parts = s.split(",")
                    tag = parts[0]
                    if tag == "L":
                        if len(parts) >= 7:
                            try:
                                self.sample.emit([float(x) for x in parts[1:7]])
                            except ValueError:
                                pass
                    else:
                        self.event.emit(s)
            except serial.SerialException as e:
                self.status.emit(f"Serial error: {e}"); break
            except Exception as e:
                self.status.emit(f"Read error: {e}"); break

        try:
            if self._ser: self._ser.close()
        except Exception:
            pass
        self.status.emit("Disconnected")
        self.stopped.emit()


# ---------- Model wrapper ----------
class TFLiteModel:
    def __init__(self, model_path: Path, norm_path: Path, labels_path: Path):
        self.interp = Interpreter(model_path=str(model_path))
        self.interp.allocate_tensors()
        self.in_detail  = self.interp.get_input_details()[0]
        self.out_detail = self.interp.get_output_details()[0]

        with open(norm_path) as f: norm = json.load(f)
        self.mu  = np.asarray(norm["mu"], dtype=np.float32)
        self.sd  = np.asarray(norm["sd"], dtype=np.float32)
        self.W   = int(norm["window"])
        self.C   = int(norm["channels"])

        with open(labels_path) as f: labels = json.load(f)
        self.labels = sorted(labels, key=lambda x: x["id"])
        self.class_names = [L["name"] for L in self.labels]

    def predict(self, win: np.ndarray) -> np.ndarray:
        x = ((win - self.mu) / self.sd).astype(np.float32)[None, ...]
        self.interp.set_tensor(self.in_detail["index"], x)
        self.interp.invoke()
        out = self.interp.get_tensor(self.out_detail["index"])[0]
        return out.astype(np.float32)


# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self, model: TFLiteModel):
        super().__init__()
        self.model = model
        self.setWindowTitle("SANKET — Auto motion-bracketed inference")
        self.resize(980, 640)
        self.setMinimumSize(560, 420)

        self.reader: SerialReader | None = None

        # live plot ring
        self.plot_ring = np.zeros((WINDOW, 6), dtype=np.float32)
        self.plot_ptr  = 0
        self.plot_full = False

        # motion-energy rolling buffer (|gyro| magnitude)
        self.energy_hist = deque(maxlen=ENERGY_WIN)

        # calibration stats
        self.cal_values: list[float] = []
        self.cal_t0: float = 0.0
        self.baseline = 0.0
        self.baseline_std = 0.0
        self.trig_thresh = CAL_FALLBACK  # replaced after calibration

        # capture state
        self.state = STATE_WAITING
        self.capture_samples: list[list[float]] = []
        self.capture_t0 = 0.0
        self.last_motion_t = 0.0
        self.state_t0 = time.time()

        # UI
        self._build_ui()
        self._apply_state_ui()

        self._plot_timer = QTimer(self); self._plot_timer.timeout.connect(self._refresh_plots)
        self._plot_timer.start(int(1000 / PLOT_FPS))

    # ---------- UI ----------
    def _build_ui(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)
        root = QWidget(); scroll.setWidget(root)
        v = QVBoxLayout(root); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        # Connection
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Port:"))
        self.cb_port = QComboBox(); self.cb_port.setMinimumWidth(260); row1.addWidget(self.cb_port)
        btn_r = QPushButton("↻"); btn_r.setFixedWidth(32); btn_r.clicked.connect(self._refresh_ports); row1.addWidget(btn_r)
        self.btn_c = QPushButton("Connect"); self.btn_c.clicked.connect(self._on_connect); row1.addWidget(self.btn_c)
        self.btn_d = QPushButton("Disconnect"); self.btn_d.clicked.connect(self._on_disconnect); self.btn_d.setEnabled(False); row1.addWidget(self.btn_d)
        row1.addStretch()
        self.lbl_status = QLabel("● Not connected"); self.lbl_status.setStyleSheet("color:#888;")
        row1.addWidget(self.lbl_status)
        v.addLayout(row1)

        # State banner
        self.state_banner = QLabel("● WAITING for stream")
        self.state_banner.setAlignment(Qt.AlignCenter); self.state_banner.setMinimumHeight(38)
        sf = QFont(); sf.setPointSize(13); sf.setBold(True); self.state_banner.setFont(sf)
        v.addWidget(self.state_banner)

        # Prediction banner
        self.banner = QLabel("—  no capture yet  —")
        self.banner.setAlignment(Qt.AlignCenter); self.banner.setMinimumHeight(56)
        bf = QFont(); bf.setPointSize(20); bf.setBold(True); self.banner.setFont(bf)
        self.banner.setStyleSheet(
            "background:#263238; color:#90a4ae; border-radius:8px; padding:8px;")
        v.addWidget(self.banner)

        # Live energy + auto baseline info + max-capture knob
        trig_group = QGroupBox("Auto motion detection (no manual threshold)")
        tg = QGridLayout(trig_group); tg.setVerticalSpacing(4)

        tg.addWidget(QLabel("Live energy:"), 0, 0)
        self.energy_bar = QProgressBar(); self.energy_bar.setRange(0, 500); self.energy_bar.setValue(0)
        self.energy_bar.setFormat("%v °/s")
        tg.addWidget(self.energy_bar, 0, 1)
        self.lbl_energy = QLabel("—"); self.lbl_energy.setMinimumWidth(170)
        tg.addWidget(self.lbl_energy, 0, 2)

        tg.addWidget(QLabel("Baseline / threshold:"), 1, 0)
        self.lbl_baseline = QLabel("(not calibrated — connect to calibrate)")
        tg.addWidget(self.lbl_baseline, 1, 1, 1, 2)

        tg.addWidget(QLabel("Max capture (s):"), 2, 0)
        self.sb_max = QDoubleSpinBox(); self.sb_max.setRange(0.5, 6.0); self.sb_max.setSingleStep(0.1)
        self.sb_max.setValue(MAX_CAPTURE_S); self.sb_max.valueChanged.connect(self._on_max_changed)
        tg.addWidget(self.sb_max, 2, 1)
        self.lbl_max_hint = QLabel("stops early when wrist settles")
        tg.addWidget(self.lbl_max_hint, 2, 2)

        row_btn = QHBoxLayout()
        self.btn_recal = QPushButton("↻ Recalibrate (hold still 2 s)"); self.btn_recal.clicked.connect(self._recalibrate)
        row_btn.addWidget(self.btn_recal)
        self.btn_abort = QPushButton("⏹ Abort / reset to IDLE"); self.btn_abort.clicked.connect(self._abort)
        row_btn.addWidget(self.btn_abort)
        row_btn.addStretch()
        tg.addLayout(row_btn, 3, 0, 1, 3)

        v.addWidget(trig_group)

        # Class probability bars
        bars_group = QGroupBox("Last prediction — class probabilities")
        bars_outer = QVBoxLayout(bars_group); bars_outer.setContentsMargins(4, 4, 4, 4)
        bars_scroll = QScrollArea(); bars_scroll.setWidgetResizable(True); bars_scroll.setMaximumHeight(200)
        bars_inner = QWidget(); bars_scroll.setWidget(bars_inner)
        bg = QGridLayout(bars_inner); bg.setContentsMargins(4, 4, 4, 4); bg.setVerticalSpacing(2)
        self.bars = {}; self.bar_labels = {}
        for i, L in enumerate(self.model.labels):
            name_lbl = QLabel(f"{L['name']} ({L['bangla']})"); name_lbl.setMinimumWidth(150)
            bg.addWidget(name_lbl, i, 0)
            bar = QProgressBar(); bar.setRange(0, 1000); bar.setValue(0); bar.setFormat("%.1f%%")
            bar.setMaximumHeight(16)
            color = CLASS_COLORS.get(L["name"], "#7986cb")
            bar.setStyleSheet(
                "QProgressBar { background:#1b1b1b; border:1px solid #333; border-radius:4px;"
                "               text-align:center; color:#eee; }"
                f"QProgressBar::chunk {{ background:{color}; }}"
            )
            bg.addWidget(bar, i, 1)
            self.bars[L["name"]] = bar
            val_lbl = QLabel("0.0 %"); val_lbl.setMinimumWidth(60); val_lbl.setAlignment(Qt.AlignRight)
            bg.addWidget(val_lbl, i, 2)
            self.bar_labels[L["name"]] = val_lbl
        bars_outer.addWidget(bars_scroll)
        v.addWidget(bars_group)

        # Live plots
        pg.setConfigOptions(antialias=True, foreground="#dddddd", background="#111111")
        self.plot_accel = pg.PlotWidget(title="Accelerometer (g)")
        self.plot_gyro  = pg.PlotWidget(title="Gyroscope (°/s)")
        for p in (self.plot_accel, self.plot_gyro):
            p.showGrid(x=True, y=True, alpha=0.3)
            p.setMouseEnabled(x=False, y=True)
            p.setLabel("bottom", "time (s)")
            p.setXRange(-WINDOW/SAMPLE_RATE_HZ, 0)
            p.setMinimumHeight(150)
        self.plot_accel.setYRange(-2.5, 2.5)
        self.plot_gyro.setYRange(-600, 600)
        v.addWidget(self.plot_accel)
        v.addWidget(self.plot_gyro)
        self.curves = []
        for i in range(3):
            self.curves.append(self.plot_accel.plot(pen=pg.mkPen(color=CH_COLORS_ACC[i], width=2)))
        for i in range(3):
            self.curves.append(self.plot_gyro.plot(pen=pg.mkPen(color=CH_COLORS_GYRO[i], width=2)))

        # Log
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(80); self.log.setMinimumHeight(60)
        self.log.setStyleSheet("background:#0f0f0f; color:#ddd; font-family:monospace;")
        v.addWidget(self.log)

        self._refresh_ports()

    # ---------- State transitions ----------
    def _on_max_changed(self, v: float):
        self._log(f"max capture → {v:.2f} s")

    def _recalibrate(self):
        if self.reader is None:
            self._log("connect first to recalibrate")
            return
        self._start_calibration()

    def _abort(self):
        self._enter_idle("aborted by user")

    def _start_calibration(self):
        self.state = STATE_CALIBRATING
        self.cal_values = []
        self.cal_t0 = time.time()
        self._log("CALIBRATING — hold wrist still for 2 s…")
        self._apply_state_ui()

    def _finish_calibration(self):
        vals = np.asarray(self.cal_values, dtype=np.float32)
        if vals.size < 20:
            self.trig_thresh = CAL_FALLBACK
            self.baseline = 0.0; self.baseline_std = 0.0
            self._log(f"calibration too short — using fallback {CAL_FALLBACK:.0f} °/s")
        else:
            self.baseline = float(vals.mean())
            self.baseline_std = float(vals.std())
            raw = self.baseline + CAL_MARGIN_MULT * self.baseline_std
            self.trig_thresh = max(raw, CAL_MIN_THRESH)
            self._log(f"CALIBRATED — baseline={self.baseline:.1f}  std={self.baseline_std:.1f}  "
                      f"threshold={self.trig_thresh:.0f} °/s")
        self.lbl_baseline.setText(
            f"baseline {self.baseline:.1f} °/s  ±  {self.baseline_std:.1f}  →  "
            f"trigger ≥ {self.trig_thresh:.0f} °/s")
        self._enter_idle("calibration complete")

    def _enter_idle(self, reason: str = ""):
        self.state = STATE_IDLE
        self.capture_samples = []
        self.capture_t0 = 0.0
        self.state_t0 = time.time()
        if reason: self._log(f"→ IDLE ({reason})")
        self._apply_state_ui()

    def _start_capture(self, energy: float):
        self.state = STATE_RECORDING
        self.capture_samples = []
        self.capture_t0 = time.time()
        self.last_motion_t = self.capture_t0
        self._log(f"⚡ START capture (energy {energy:.0f} ≥ {self.trig_thresh:.0f} °/s)")
        self._apply_state_ui()

    def _finish_capture(self, reason: str):
        n = len(self.capture_samples)
        duration = n / SAMPLE_RATE_HZ
        if duration < MIN_CAPTURE_S:
            self._log(f"✗ capture too short ({duration:.2f} s < {MIN_CAPTURE_S:.1f}) — discarded")
            self._enter_idle("short capture discarded")
            return

        # Build WINDOW-shaped array, gesture at start, zero-pad the rest
        data = np.asarray(self.capture_samples, dtype=np.float32)
        if n >= WINDOW:
            data = data[:WINDOW]
        else:
            pad = np.zeros((WINDOW - n, 6), dtype=np.float32)
            data = np.concatenate([data, pad], axis=0)

        probs = self.model.predict(data)
        for L in self.model.labels:
            p = float(probs[L["id"]]) * 100.0
            self.bars[L["name"]].setValue(int(p * 10))
            self.bar_labels[L["name"]].setText(f"{p:.1f} %")
        top = int(np.argmax(probs))
        top_name = self.model.class_names[top]
        top_prob = float(probs[top])
        bangla = next((L.get("bangla", top_name) for L in self.model.labels
                       if L["name"] == top_name), top_name)
        color = CLASS_COLORS.get(top_name, "#2e7d32")
        self.banner.setText(f"{bangla}  ({top_prob*100:.0f}%)")
        self.banner.setStyleSheet(
            f"background:{color}; color:white; border-radius:8px; padding:8px;")
        self._log(f"✅ {top_name} ({bangla}) @ {top_prob*100:.1f}%  —  "
                  f"wrote {duration:.2f} s, padded to {WINDOW/SAMPLE_RATE_HZ:.1f} s  ({reason})")

        self.state = STATE_COOLDOWN
        self.state_t0 = time.time()
        self._apply_state_ui()

    def _apply_state_ui(self):
        if self.state == STATE_WAITING:
            self.state_banner.setText("● WAITING  —  connect the device")
            self.state_banner.setStyleSheet(
                "background:#37474f; color:#b0bec5; border-radius:6px; padding:6px;")
        elif self.state == STATE_CALIBRATING:
            remain = max(0.0, CAL_DURATION_S - (time.time() - self.cal_t0))
            self.state_banner.setText(f"⏳ CALIBRATING  —  HOLD STILL  {remain:.1f} s left")
            self.state_banner.setStyleSheet(
                "background:#6a1b9a; color:white; border-radius:6px; padding:6px;")
        elif self.state == STATE_IDLE:
            self.state_banner.setText("● IDLE  —  start writing when ready")
            self.state_banner.setStyleSheet(
                "background:#37474f; color:#b0bec5; border-radius:6px; padding:6px;")
        elif self.state == STATE_RECORDING:
            elapsed = len(self.capture_samples) / SAMPLE_RATE_HZ
            self.state_banner.setText(f"⚡ RECORDING  —  {elapsed:.2f} s  (keep writing…)")
            self.state_banner.setStyleSheet(
                "background:#ef6c00; color:white; border-radius:6px; padding:6px;")
        elif self.state == STATE_COOLDOWN:
            self.state_banner.setText("✓ COOLDOWN  —  re-arming shortly…")
            self.state_banner.setStyleSheet(
                "background:#1565c0; color:white; border-radius:6px; padding:6px;")

    # ---------- Ports / connection ----------
    def _refresh_ports(self):
        self.cb_port.clear()
        found = [p.device for p in serial.tools.list_ports.comports()]
        found.sort(key=lambda x: (0 if ("wchusbserial" in x or "usbmodem" in x) else 1, x))
        for d in found: self.cb_port.addItem(d)
        if not found: self.cb_port.addItem("(no serial ports found)")

    def _on_connect(self):
        port = self.cb_port.currentText()
        if not port or "(no serial" in port: return
        self.reader = SerialReader(port, BAUD)
        self.reader.sample.connect(self._on_sample)
        self.reader.event.connect(self._on_event)
        self.reader.status.connect(self._on_status)
        self.reader.stopped.connect(self._on_reader_stopped)
        self.reader.start()
        self.btn_c.setEnabled(False); self.btn_d.setEnabled(True)
        # start calibration automatically on connect
        QTimer.singleShot(400, self._start_calibration)

    def _on_disconnect(self):
        if self.reader: self.reader.stop()

    def _on_reader_stopped(self):
        self.btn_c.setEnabled(True); self.btn_d.setEnabled(False); self.reader = None
        self.state = STATE_WAITING
        self._apply_state_ui()

    def _on_status(self, text: str):
        self.lbl_status.setText(f"● {text}")
        if "Connected" in text:
            self.lbl_status.setStyleSheet("color:#4caf50;")
        elif "ERROR" in text or "error" in text:
            self.lbl_status.setStyleSheet("color:#ef5350;")
        else:
            self.lbl_status.setStyleSheet("color:#bbb;")

    def _on_event(self, s: str):
        if s.startswith("H,"):     self._log("device ready")
        elif s.startswith("C,DONE"): self._log("device calibrated")
        elif s.startswith("E,"):   self._log(f"⚠ {s}")

    # ---------- Sample ingest = state machine driver ----------
    def _on_sample(self, vals: list):
        # live plot ring
        self.plot_ring[self.plot_ptr] = vals
        self.plot_ptr = (self.plot_ptr + 1) % WINDOW
        if self.plot_ptr == 0: self.plot_full = True

        # gyro magnitude energy (rolling max over ENERGY_WIN samples)
        gx, gy, gz = vals[3], vals[4], vals[5]
        mag = (gx*gx + gy*gy + gz*gz) ** 0.5
        self.energy_hist.append(mag)
        energy = max(self.energy_hist) if self.energy_hist else 0.0

        # update live energy display
        self.energy_bar.setValue(min(int(energy), 500))
        self.lbl_energy.setText(f"{energy:.1f}   (trig {self.trig_thresh:.0f})")
        chunk = "#ef5350" if energy >= self.trig_thresh else "#66bb6a"
        self.energy_bar.setStyleSheet(
            "QProgressBar { background:#1b1b1b; border:1px solid #333; border-radius:4px;"
            "               text-align:center; color:#eee; }"
            f"QProgressBar::chunk {{ background:{chunk}; }}"
        )

        # state machine
        now = time.time()
        if self.state == STATE_CALIBRATING:
            self.cal_values.append(mag)
            # update banner countdown
            if int((now - self.cal_t0) * 10) % 3 == 0:
                self._apply_state_ui()
            if (now - self.cal_t0) >= CAL_DURATION_S:
                self._finish_calibration()

        elif self.state == STATE_IDLE:
            if energy >= self.trig_thresh:
                self._start_capture(energy)

        elif self.state == STATE_RECORDING:
            self.capture_samples.append(vals)
            elapsed = len(self.capture_samples) / SAMPLE_RATE_HZ

            # track last motion moment
            if energy >= self.trig_thresh:
                self.last_motion_t = now

            # end conditions
            settled_for = now - self.last_motion_t
            max_cap = self.sb_max.value()
            if elapsed >= max_cap:
                self._finish_capture(f"max {max_cap:.1f} s")
            elif elapsed >= MIN_CAPTURE_S and settled_for >= STOP_SETTLE_S:
                self._finish_capture(f"wrist settled")
            else:
                # refresh elapsed in banner every ~100 ms
                if len(self.capture_samples) % 10 == 0:
                    self._apply_state_ui()

        elif self.state == STATE_COOLDOWN:
            if (now - self.state_t0) >= COOLDOWN_S:
                self._enter_idle("cooldown over")

    def _current_plot_window(self) -> np.ndarray | None:
        if not self.plot_full and self.plot_ptr < 2: return None
        if not self.plot_full:
            return self.plot_ring[:self.plot_ptr]
        a = self.plot_ring[self.plot_ptr:]
        b = self.plot_ring[:self.plot_ptr]
        return np.concatenate([a, b], axis=0)

    def _refresh_plots(self):
        win = self._current_plot_window()
        if win is None or win.shape[0] < 2: return
        n = win.shape[0]
        t = np.linspace(-n / SAMPLE_RATE_HZ, 0, n)
        for i in range(6):
            self.curves[i].setData(t, win[:, i])

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    def closeEvent(self, event):
        if self.reader:
            self.reader.stop()
            self.reader.wait(2000)
        super().closeEvent(event)


# ---------- main ----------
def main():
    if not MODEL_PATH.exists():
        print(f"❌ model not found: {MODEL_PATH}\nRun `python train.py` first.")
        sys.exit(1)

    model = TFLiteModel(MODEL_PATH, NORM_PATH, LABELS_PATH)
    global WINDOW
    WINDOW = model.W
    print(f"✓ loaded model ({MODEL_PATH.stat().st_size/1024:.1f} KB)  "
          f"classes={model.class_names}  window={WINDOW} samples "
          f"({WINDOW/SAMPLE_RATE_HZ:.1f} s)")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.Window,        QColor(30, 30, 30))
    pal.setColor(QPalette.WindowText,    QColor(230, 230, 230))
    pal.setColor(QPalette.Base,          QColor(20, 20, 20))
    pal.setColor(QPalette.Text,          QColor(230, 230, 230))
    pal.setColor(QPalette.Button,        QColor(55, 55, 55))
    pal.setColor(QPalette.ButtonText,    QColor(230, 230, 230))
    pal.setColor(QPalette.Highlight,     QColor(0, 120, 212))
    app.setPalette(pal)

    w = MainWindow(model); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
