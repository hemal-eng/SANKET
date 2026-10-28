"""
SANKET — Host-side Live Inference GUI
=====================================
A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid Air-Written
Gesture Recognition.

This GUI is a HOST-SIDE debugging / validation tool. In normal operation
the trained model runs ON the ESP32-S3 (see firmware_infer/), and the
device outputs predictions directly over serial. This GUI runs the same
model on the laptop for comparison and development.

Reads continuous IMU samples from the ESP32-S3 (L messages @100 Hz),
keeps a sliding 6-second window, runs the trained TFLite model every
~200 ms, shows live class probabilities and a big detection banner.

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
    QPushButton, QComboBox, QLabel, QGroupBox, QProgressBar, QTextEdit
)
import pyqtgraph as pg

# Use TFLite interpreter (lightweight) if available, else fall back to full TF.
try:
    from tflite_runtime.interpreter import Interpreter  # type: ignore
except ImportError:
    import tensorflow as tf  # noqa: E402
    Interpreter = tf.lite.Interpreter


# ---------- Config ----------
BAUD              = 921600
SAMPLE_RATE_HZ    = 100
WINDOW            = 600                  # samples (6 s) — must match train.py / firmware
INFER_INTERVAL_MS = 200                  # how often to run the model
PLOT_FPS          = 30
CONF_THRESHOLD    = 0.75                 # min prob to call it a detection
CONSEC_FRAMES     = 2                    # consecutive frames above threshold

HERE       = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
MODEL_PATH = MODELS_DIR / "sanket_float32.tflite"
NORM_PATH  = MODELS_DIR / "norm.json"
LABELS_PATH= MODELS_DIR / "labels.json"

CH_NAMES        = ["ax", "ay", "az", "gx", "gy", "gz"]
CH_COLORS_ACC   = [(255, 90,  90),  (90, 220, 90),  (90, 150, 255)]
CH_COLORS_GYRO  = [(230, 180, 90),  (210, 90,  220),(90,  220, 220)]
CLASS_COLORS    = {"ami": "#4caf50", "idle": "#90a4ae"}


# ---------- Serial reader thread (reused from collector) ----------
class SerialReader(QThread):
    sample  = Signal(list)   # [float x6]  — only L samples are forwarded
    event   = Signal(str)    # 'H' / 'C,DONE' / 'E,...'
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
        """win: (W, C) float32 in physical units → probabilities (K,)."""
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
        self.setWindowTitle("SANKET — Live Inference (host-side)")
        self.resize(1200, 850)

        self.reader: SerialReader | None = None

        # Ring buffer for sliding window
        self.ring = np.zeros((WINDOW, 6), dtype=np.float32)
        self.ring_ptr = 0
        self.ring_full = False

        # Smoothing / detection state
        self.probs_hist = deque(maxlen=4)
        self.consec_ami = 0
        self.last_detect_t = 0.0

        self._build_ui()

        # Plot & inference timers
        self._plot_timer = QTimer(self); self._plot_timer.timeout.connect(self._refresh_plots)
        self._plot_timer.start(int(1000 / PLOT_FPS))
        self._infer_timer = QTimer(self); self._infer_timer.timeout.connect(self._run_inference)
        self._infer_timer.start(INFER_INTERVAL_MS)

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        v = QVBoxLayout(root); v.setContentsMargins(10, 10, 10, 10); v.setSpacing(8)

        # Connection bar
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

        # Big detection banner
        self.banner = QLabel("—  waiting for stream  —")
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setMinimumHeight(80)
        bf = QFont(); bf.setPointSize(28); bf.setBold(True); self.banner.setFont(bf)
        self.banner.setStyleSheet(
            "background:#263238; color:#90a4ae; border-radius:8px; padding:12px;")
        v.addWidget(self.banner)

        # Class probability bars
        bars_group = QGroupBox("Class probabilities (live)")
        bg = QGridLayout(bars_group)
        self.bars = {}
        self.bar_labels = {}
        for i, L in enumerate(self.model.labels):
            name_lbl = QLabel(f"{L['name']} ({L['bangla']})")
            name_lbl.setMinimumWidth(170)
            bg.addWidget(name_lbl, i, 0)
            bar = QProgressBar(); bar.setRange(0, 1000); bar.setValue(0); bar.setFormat("%.1f%%")
            color = CLASS_COLORS.get(L["name"], "#7986cb")
            bar.setStyleSheet(
                "QProgressBar { background:#1b1b1b; border:1px solid #333; border-radius:4px;"
                "               text-align:center; color:#eee; }"
                f"QProgressBar::chunk {{ background:{color}; }}"
            )
            bg.addWidget(bar, i, 1)
            self.bars[L["name"]] = bar
            val_lbl = QLabel("0.0 %"); val_lbl.setMinimumWidth(70); val_lbl.setAlignment(Qt.AlignRight)
            bg.addWidget(val_lbl, i, 2)
            self.bar_labels[L["name"]] = val_lbl
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
        self.plot_accel.setYRange(-2.5, 2.5)
        self.plot_gyro.setYRange(-600, 600)
        v.addWidget(self.plot_accel, stretch=2)
        v.addWidget(self.plot_gyro,  stretch=2)
        self.curves = []
        for i in range(3):
            self.curves.append(self.plot_accel.plot(pen=pg.mkPen(color=CH_COLORS_ACC[i], width=2)))
        for i in range(3):
            self.curves.append(self.plot_gyro.plot(pen=pg.mkPen(color=CH_COLORS_GYRO[i], width=2)))

        # Detection log
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(100)
        self.log.setStyleSheet("background:#0f0f0f; color:#ddd; font-family:monospace;")
        v.addWidget(self.log)

        self._refresh_ports()

    # ---------- Ports ----------
    def _refresh_ports(self):
        self.cb_port.clear()
        found = [p.device for p in serial.tools.list_ports.comports()]
        found.sort(key=lambda x: (0 if "cu." in x else 1, x))
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

    def _on_disconnect(self):
        if self.reader: self.reader.stop()

    def _on_reader_stopped(self):
        self.btn_c.setEnabled(True); self.btn_d.setEnabled(False); self.reader = None

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
        elif s.startswith("C,DONE"): self._log("calibrated")
        elif s.startswith("E,"):   self._log(f"⚠ {s}")

    # ---------- Sample ingest ----------
    def _on_sample(self, vals: list):
        self.ring[self.ring_ptr] = vals
        self.ring_ptr = (self.ring_ptr + 1) % WINDOW
        if self.ring_ptr == 0: self.ring_full = True

    def _current_window(self) -> np.ndarray | None:
        if not self.ring_full: return None
        a = self.ring[self.ring_ptr:]
        b = self.ring[:self.ring_ptr]
        return np.concatenate([a, b], axis=0)

    # ---------- Inference ----------
    def _run_inference(self):
        win = self._current_window()
        if win is None: return
        probs = self.model.predict(win)
        self.probs_hist.append(probs)
        # Smoothed probabilities = mean of last few frames
        smoothed = np.mean(np.stack(self.probs_hist, axis=0), axis=0)

        for L in self.model.labels:
            p = float(smoothed[L["id"]]) * 100.0
            self.bars[L["name"]].setValue(int(p * 10))
            self.bar_labels[L["name"]].setText(f"{p:.1f} %")

        top = int(np.argmax(smoothed))
        top_name = self.model.class_names[top]
        top_prob = float(smoothed[top])

        # Detection: consecutive ami above threshold
        if top_name == "ami" and top_prob > CONF_THRESHOLD:
            self.consec_ami += 1
        else:
            self.consec_ami = 0

        if self.consec_ami >= CONSEC_FRAMES:
            self._set_banner("আমি  DETECTED", "#2e7d32")
            now = time.time()
            if now - self.last_detect_t > 1.5:
                self.last_detect_t = now
                self._log(f"✅ ami @ {top_prob*100:.1f}%")
        elif top_name == "idle" and top_prob > CONF_THRESHOLD:
            self._set_banner("idle", "#455a64")
        else:
            self._set_banner("…", "#263238")

    def _set_banner(self, text: str, bg: str):
        self.banner.setText(text)
        self.banner.setStyleSheet(
            f"background:{bg}; color:white; border-radius:8px; padding:12px;")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")

    # ---------- Plot refresh ----------
    def _refresh_plots(self):
        win = self._current_window()
        if win is None:
            win = self.ring[:self.ring_ptr]
            if win.shape[0] < 2: return
        n = win.shape[0]
        t = np.linspace(-n / SAMPLE_RATE_HZ, 0, n)
        for i in range(6):
            self.curves[i].setData(t, win[:, i])


# ---------- main ----------
def main():
    if not MODEL_PATH.exists():
        print(f"❌ model not found: {MODEL_PATH}\nRun `python train.py` first.")
        sys.exit(1)

    model = TFLiteModel(MODEL_PATH, NORM_PATH, LABELS_PATH)
    print(f"✓ loaded model ({MODEL_PATH.stat().st_size/1024:.1f} KB)  classes={model.class_names}")

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
