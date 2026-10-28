// SANKET — Data Logger Firmware
// Target : ESP32-S3-DevKitC-1 (N16R8, dual-USB black board), UART USB port
// Sensor : MPU6050 (I2C @ 0x68) on SDA=GPIO8, SCL=GPIO9
// Trigger: BOOT button (GPIO 0) — press & hold to record, release to stop
//
// Trigger model: ONE-SHOT FIXED-DURATION. One trigger (either BOOT press or
// 'T' over serial) → firmware records EXACTLY FIXED_RECORD_SAMPLES samples
// (6.0 s at 100 Hz) and auto-stops. No stop trigger. Any trigger while already
// recording is ignored. This eliminates every class of "cut recording" bug
// since nothing except the sample counter can stop the recording.
//
// Serial protocol (ASCII, newline-terminated, 921600 baud):
//   Host → Device:
//     T\n                                  trigger a one-shot recording (ignored if already recording)
//   Device → Host:
//     H,SANKET-logger,v5,100hz,oneshot,600
//     C,START
//     C,DONE,ox,oy,oz,ogx,ogy,ogz          (offsets in g and dps)
//     L,ax,ay,az,gx,gy,gz                  (live stream at 50 Hz when idle)
//     R,START
//     D,ax,ay,az,gx,gy,gz                  (recording data at 100 Hz)
//     R,STOP,<sample_count>                (fires at FIXED_RECORD_SAMPLES)
//     E,<reason>                           (error)

#include <Arduino.h>
#include <Wire.h>

// ---------- Pins ----------
static const int PIN_SDA   = 8;
static const int PIN_SCL   = 9;
static const int PIN_BOOT  = 0;    // BOOT button (built-in, GPIO 0, active-low)

// ---------- MPU6050 ----------
static const uint8_t MPU_ADDR = 0x68;
static const uint8_t REG_SMPLRT_DIV   = 0x19;
static const uint8_t REG_CONFIG       = 0x1A;
static const uint8_t REG_GYRO_CONFIG  = 0x1B;
static const uint8_t REG_ACCEL_CONFIG = 0x1C;
static const uint8_t REG_PWR_MGMT_1   = 0x6B;
static const uint8_t REG_ACCEL_XOUT_H = 0x3B;
static const uint8_t REG_WHO_AM_I     = 0x75;

// LSB sensitivity at ±4g / ±500 dps
static constexpr float ACCEL_LSB_PER_G   = 8192.0f;
static constexpr float GYRO_LSB_PER_DPS  = 65.5f;

// ---------- Timing / Config ----------
static const uint32_t SAMPLE_RATE_HZ   = 100;
static const uint32_t SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;
static const uint32_t CALIB_SAMPLES    = 200;       // 2 s @ 100 Hz
static const uint32_t CALIB_WARMUP_MS  = 1500;      // wait before calibrating
static const uint32_t FIXED_RECORD_SAMPLES = 600;   // exactly 6.0 s @ 100 Hz — air-writing window
static const uint32_t BTN_READY_MS     = 1000;      // ignore BOOT during this window after start
static const uint32_t BTN_DEBOUNCE_MS  = 40;        // raw must be stable this long before logical flips

// IIR low-pass alpha (0..1). Smaller = heavier smoothing. 0.3 ≈ gentle.
static constexpr float FILTER_ALPHA = 0.30f;

// ---------- State ----------
float g_offset_raw[6] = {0, 0, 0, 0, 0, 0};  // raw (int16) offsets
float g_filtered[6]   = {0, 0, 0, 0, 0, 0};  // filtered physical units

bool     g_recording       = false;
uint32_t g_record_count    = 0;
uint32_t g_next_sample_us  = 0;
uint32_t g_last_live_tx_us = 0;

uint32_t g_boot_time_ms    = 0;
bool     g_btn_raw_level   = HIGH;   // most recent raw read of PIN_BOOT
bool     g_btn_pressed     = false;  // debounced LOGICAL "button is pressed"
bool     g_btn_prev_pressed= false;  // previous value, for edge detection
uint32_t g_btn_last_change = 0;      // ms when raw level last changed

// ---------- MPU helpers ----------
static bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

static uint8_t mpuRead(uint8_t reg) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  Wire.requestFrom((int)MPU_ADDR, 1);
  return Wire.available() ? Wire.read() : 0xFF;
}

// Reads 6 raw int16 values: ax, ay, az, gx, gy, gz
static bool readIMU(int16_t out[6]) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((int)MPU_ADDR, 14);
  if (Wire.available() < 14) return false;

  out[0] = (int16_t)((Wire.read() << 8) | Wire.read());  // ax
  out[1] = (int16_t)((Wire.read() << 8) | Wire.read());  // ay
  out[2] = (int16_t)((Wire.read() << 8) | Wire.read());  // az
  Wire.read(); Wire.read();                              // skip TEMP
  out[3] = (int16_t)((Wire.read() << 8) | Wire.read());  // gx
  out[4] = (int16_t)((Wire.read() << 8) | Wire.read());  // gy
  out[5] = (int16_t)((Wire.read() << 8) | Wire.read());  // gz
  return true;
}

// ---------- Trigger a one-shot recording (ignored if already recording) ----------
static void triggerRecording() {
  if (g_recording) return;     // one-shot: ignore all triggers during a recording
  g_recording    = true;
  g_record_count = 0;
  Serial.println("R,START");
}

// ---------- Setup ----------
static bool configureMPU() {
  // Wake from sleep, use PLL with X-gyro reference (0x01) for stability
  if (!mpuWrite(REG_PWR_MGMT_1, 0x01)) return false;
  delay(50);

  // Identify
  uint8_t who = mpuRead(REG_WHO_AM_I);
  if (who != 0x68 && who != 0x70 && who != 0x71 && who != 0x72 && who != 0x98) {
    Serial.printf("E,who_am_i=0x%02X\n", who);
    return false;
  }

  // Sample rate = 1kHz / (1 + 9) = 100 Hz
  if (!mpuWrite(REG_SMPLRT_DIV, 0x09)) return false;
  // DLPF: 44 Hz accel BW, 42 Hz gyro BW
  if (!mpuWrite(REG_CONFIG, 0x03)) return false;
  // Gyro range ±500 dps
  if (!mpuWrite(REG_GYRO_CONFIG, 0x08)) return false;
  // Accel range ±4g
  if (!mpuWrite(REG_ACCEL_CONFIG, 0x08)) return false;

  delay(50);
  return true;
}

static void calibrate() {
  Serial.println("C,START");
  delay(500);  // let user settle wrist

  double sum[6] = {0, 0, 0, 0, 0, 0};
  int16_t raw[6];
  uint32_t taken = 0;

  for (uint32_t i = 0; i < CALIB_SAMPLES; i++) {
    if (readIMU(raw)) {
      for (int j = 0; j < 6; j++) sum[j] += raw[j];
      taken++;
    }
    delay(10);
  }

  if (taken == 0) {
    Serial.println("E,calib_no_data");
    return;
  }

  for (int j = 0; j < 6; j++) g_offset_raw[j] = (float)(sum[j] / taken);

  // Report in physical units
  Serial.printf("C,DONE,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f\n",
    g_offset_raw[0] / ACCEL_LSB_PER_G,
    g_offset_raw[1] / ACCEL_LSB_PER_G,
    g_offset_raw[2] / ACCEL_LSB_PER_G,
    g_offset_raw[3] / GYRO_LSB_PER_DPS,
    g_offset_raw[4] / GYRO_LSB_PER_DPS,
    g_offset_raw[5] / GYRO_LSB_PER_DPS);

  // Prime filter state with zeros (offsets just subtracted)
  for (int j = 0; j < 6; j++) g_filtered[j] = 0.0f;
}

void setup() {
  pinMode(PIN_BOOT, INPUT_PULLUP);

  Serial.begin(921600);
  delay(600);  // allow Mac to settle USB
  Serial.println("H,SANKET-logger,v5,100hz,oneshot,600");

  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);  // 400 kHz I2C

  if (!configureMPU()) {
    Serial.println("E,mpu_init_fail");
    while (true) { delay(1000); Serial.println("E,mpu_init_fail"); }
  }

  calibrate();

  g_boot_time_ms    = millis();
  g_next_sample_us  = micros() + SAMPLE_PERIOD_US;
  g_btn_raw_level   = digitalRead(PIN_BOOT);
  g_btn_pressed     = false;              // logical state starts "released"
  g_btn_prev_pressed= false;
  g_btn_last_change = g_boot_time_ms;
}

// ---------- Loop ----------
void loop() {
  uint32_t now_us = micros();
  if ((int32_t)(now_us - g_next_sample_us) < 0) return;
  g_next_sample_us += SAMPLE_PERIOD_US;

  int16_t raw[6];
  if (!readIMU(raw)) {
    Serial.println("E,read_fail");
    return;
  }

  // Subtract offsets, convert to physical units
  float sample[6];
  sample[0] = (raw[0] - g_offset_raw[0]) / ACCEL_LSB_PER_G;
  sample[1] = (raw[1] - g_offset_raw[1]) / ACCEL_LSB_PER_G;
  sample[2] = (raw[2] - g_offset_raw[2]) / ACCEL_LSB_PER_G;
  sample[3] = (raw[3] - g_offset_raw[3]) / GYRO_LSB_PER_DPS;
  sample[4] = (raw[4] - g_offset_raw[4]) / GYRO_LSB_PER_DPS;
  sample[5] = (raw[5] - g_offset_raw[5]) / GYRO_LSB_PER_DPS;

  // IIR low-pass filter (per channel)
  for (int j = 0; j < 6; j++) {
    g_filtered[j] = FILTER_ALPHA * sample[j] + (1.0f - FILTER_ALPHA) * g_filtered[j];
  }

  // ----- BOOT button handling (debounced + edge-triggered TOGGLE) -----
  // The logical "pressed" flips only after the raw pin has been stable for
  // BTN_DEBOUNCE_MS. Each rising edge (release→press) toggles recording.
  // So the finger is OFF the button during the gesture, meaning table-tap
  // shocks can't cut the sample. A 500 ms min window stops accidental
  // double-taps from aborting a fresh recording.
  uint32_t now_ms  = millis();
  bool raw_level   = digitalRead(PIN_BOOT);
  if (raw_level != g_btn_raw_level) {
    g_btn_raw_level   = raw_level;
    g_btn_last_change = now_ms;
  }
  bool button_ready = (now_ms - g_boot_time_ms) > BTN_READY_MS;
  if (button_ready && (now_ms - g_btn_last_change) >= BTN_DEBOUNCE_MS) {
    g_btn_pressed = (g_btn_raw_level == LOW);   // commit stable value (active-low)
  }

  // Rising edge on debounced button → one-shot trigger
  bool press_edge = button_ready && g_btn_pressed && !g_btn_prev_pressed;
  g_btn_prev_pressed = g_btn_pressed;
  if (press_edge) triggerRecording();

  // Serial command from host (preferred: GUI spacebar sends 'T')
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'T' || c == 't') triggerRecording();
    // ignore CR/LF and any other junk
  }

  // Fixed-length stop: the ONLY way a recording ends
  if (g_recording && g_record_count >= FIXED_RECORD_SAMPLES) {
    g_recording = false;
    Serial.printf("R,STOP,%u\n", g_record_count);
  }

  // ----- Emit sample -----
  if (g_recording) {
    Serial.printf("D,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f\n",
      g_filtered[0], g_filtered[1], g_filtered[2],
      g_filtered[3], g_filtered[4], g_filtered[5]);
    g_record_count++;
  } else {
    // Live stream at FULL 100 Hz when idle — matches the inference window stride
    g_last_live_tx_us = now_us;
    Serial.printf("L,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f\n",
      g_filtered[0], g_filtered[1], g_filtered[2],
      g_filtered[3], g_filtered[4], g_filtered[5]);
  }
}
