// SANKET — ON-DEVICE INFERENCE FIRMWARE (motion-trigger + OLED)
//   A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid
//   Air-Written Gesture Recognition.
//
// Hardware
// --------
//   ESP32-S3-DevKitC-1 (N16R8), UART USB port (CH343/CP2102)
//   MPU6050  — I2C bus 0 (Wire) on SDA=GPIO 8,  SCL=GPIO 9  @ 400 kHz
//   SSD1306  — I2C bus 1 (Wire1) on SDA=GPIO 19, SCL=GPIO 20 @ 400 kHz, addr 0x3C
//   0.96" 128×64 OLED
//
// Bangla text rendering uses the mamunul/BanglaText library on top of
// Adafruit_SSD1306. Only one font is bundled — BanglaMNRegular_25pt.
//
// Pipeline
// --------
// Core 1 samples IMU @ 100 Hz and drives the motion-trigger state
// machine. On capture end the sample window (zero-padded to 600) is
// handed to the inference task on core 0. On every state transition
// the OLED is refreshed with the current status and detected word.
//
// Serial protocol stays the same as v2 (see README) so the host GUI
// and logs keep working.

#include <Arduino.h>
#include <Wire.h>
#include <string>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>

#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <BanglaText.h>
#include "BanglaMNRegular_25pt.h"

#include "model_data.h"
#include "model_norm.h"

// ---------- Pins ----------
static const int PIN_SDA       = 8;
static const int PIN_SCL       = 9;
static const int PIN_OLED_SDA  = 41;
static const int PIN_OLED_SCL  = 42;

// ---------- MPU6050 ----------
static const uint8_t MPU_ADDR          = 0x68;
static const uint8_t REG_SMPLRT_DIV    = 0x19;
static const uint8_t REG_CONFIG        = 0x1A;
static const uint8_t REG_GYRO_CONFIG   = 0x1B;
static const uint8_t REG_ACCEL_CONFIG  = 0x1C;
static const uint8_t REG_PWR_MGMT_1    = 0x6B;
static const uint8_t REG_ACCEL_XOUT_H  = 0x3B;
static const uint8_t REG_WHO_AM_I      = 0x75;

static constexpr float ACCEL_LSB_PER_G  = 8192.0f;   // ±4g
static constexpr float GYRO_LSB_PER_DPS = 65.5f;     // ±500 dps

// ---------- OLED ----------
#define SCREEN_WIDTH   128
#define SCREEN_HEIGHT  64
#define SCREEN_ADDR    0x3C
static Adafruit_SSD1306 g_display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire1, -1 /*rst*/);

// BanglaTextRenderer draws via a pixel callback; use globals to offset
// the text position (callback is a plain function pointer, can't capture).
static BTfont                g_bangla_font;
static BanglaTextRenderer*   g_bangla_renderer = nullptr;
// Bangla glyphs are rendered into this off-screen canvas first, then
// copied to the display rotated 180° so they line up with the panel's
// ribbon side while the English text stays in the default orientation.
// The renderer lays words out along Y (25pt words span up to ~81 px tall,
// ~28 px wide), so the canvas must be tall, not wide.
static GFXcanvas1            g_bangla_canvas(40, 128);
static void banglaDrawPixel(int16_t x, int16_t y) {
    g_bangla_canvas.drawPixel(x, y, 1);
}

// ---------- Sampling config ----------
static const uint32_t SAMPLE_RATE_HZ    = 100;
static const uint32_t SAMPLE_PERIOD_US  = 1000000UL / SAMPLE_RATE_HZ;
static const uint32_t CALIB_SAMPLES     = 200;
static constexpr float FILTER_ALPHA     = 0.30f;

// ---------- Motion-trigger config ----------
static constexpr float   TRIG_THRESH_DPS   = 80.0f;         // Hassan-tested value
static constexpr float   MAX_CAPTURE_S     = 3.50f;         // early stop OK, this is the cap
static constexpr float   MIN_CAPTURE_S     = 0.50f;
static constexpr float   STOP_SETTLE_S     = 0.40f;
static constexpr float   COOLDOWN_S        = 1.00f;
static constexpr float   DETECT_CONF       = 0.75f;

static const uint32_t MAX_CAP_SMPL     = (uint32_t)(MAX_CAPTURE_S  * SAMPLE_RATE_HZ);
static const uint32_t MIN_CAP_SMPL     = (uint32_t)(MIN_CAPTURE_S  * SAMPLE_RATE_HZ);
static const uint32_t SETTLE_SMPL      = (uint32_t)(STOP_SETTLE_S  * SAMPLE_RATE_HZ);
static const uint32_t COOLDOWN_SMPL    = (uint32_t)(COOLDOWN_S     * SAMPLE_RATE_HZ);
static const uint32_t ENERGY_WIN       = 10;
static const uint32_t LIVE_TX_PERIOD   = SAMPLE_RATE_HZ;
static const uint32_t CAP_TX_PERIOD    = 50;

// Bangla name per class (MUST match MODEL_CLASS_NAMES order in model_norm.h)
static const char* CLASS_BANGLA[MODEL_CLASSES] = {
    "বিশ্রাম",      // idle
    "আমি",          // ami
    "হ্যাঁ",        // haan
    "ধন্যবাদ",      // dhonnobad
    "পানি",         // pani
    "খাবার",        // khabar
    "সাহায্য",      // shahajjo
    "সালাম",        // salam
};

// ---------- IMU state ----------
float    g_offset_raw[6] = {0};
float    g_filtered[6]   = {0};
uint32_t g_next_sample_us = 0;

float    g_energy_ring[ENERGY_WIN] = {0};
uint32_t g_energy_ptr = 0;

// ---------- Capture buffers ----------
static float             g_capture_buf[MODEL_WINDOW][MODEL_CHANNELS];
static uint32_t          g_capture_idx = 0;
static float             g_snapshot   [MODEL_WINDOW][MODEL_CHANNELS];
static SemaphoreHandle_t g_snap_mutex = nullptr;
static TaskHandle_t      g_infer_task_handle = nullptr;

// ---------- State machine ----------
enum State { S_IDLE, S_CAPTURING, S_COOLDOWN };
static State    g_state           = S_IDLE;
static uint32_t g_settled_count   = 0;
static uint32_t g_cooldown_left   = 0;
static uint32_t g_live_tx_counter = 0;

// ---------- TFLite micro globals ----------
namespace {
const tflite::Model*      model          = nullptr;
tflite::MicroInterpreter* interpreter    = nullptr;
TfLiteTensor*             input          = nullptr;
TfLiteTensor*             output         = nullptr;

// Big model actually uses 150 KB (reported at boot). 168 KB gives
// comfortable headroom while leaving room in DRAM for the OLED
// framebuffer and the BanglaText renderer.
constexpr int kTensorArenaSize = 168 * 1024;
alignas(16) uint8_t tensor_arena[kTensorArenaSize];
}

// ============================================================================
//                               OLED helpers
// ============================================================================
static void displayHeader(const char* top) {
    g_display.setTextSize(1);
    g_display.setTextColor(SSD1306_WHITE);
    g_display.setCursor(0, 0);
    g_display.print(top);
    g_display.drawFastHLine(0, 10, SCREEN_WIDTH, SSD1306_WHITE);
}

// Render Bangla off-screen, find its bounding box, then blit it rotated
// 180° and centered in the band between header (y=12) and footer (y=54).
static void displayBangla(const char* utf8) {
    if (!g_bangla_renderer) return;
    g_bangla_canvas.fillScreen(0);
    g_bangla_renderer->renderText(std::string(utf8), banglaDrawPixel);

    const int16_t cw = g_bangla_canvas.width(), ch = g_bangla_canvas.height();
    int16_t minx = cw, miny = ch, maxx = -1, maxy = -1;
    for (int16_t y = 0; y < ch; y++)
        for (int16_t x = 0; x < cw; x++)
            if (g_bangla_canvas.getPixel(x, y)) {
                if (x < minx) minx = x;
                if (x > maxx) maxx = x;
                if (y < miny) miny = y;
                if (y > maxy) maxy = y;
            }
    if (maxx < 0) return;

    const int16_t bw = maxx - minx + 1, bh = maxy - miny + 1;
    const int16_t band_top = 12, band_h = 42;


    int16_t dx = (SCREEN_WIDTH - bh) / 2;
    int16_t dy = band_top + (band_h - bw) / 2;


    if (dx < 0) dx = 0;
    if (dy < band_top) dy = band_top;

    for (int16_t y = miny; y <= maxy; y++)
        for (int16_t x = minx; x <= maxx; x++)
            if (g_bangla_canvas.getPixel(x, y))




             g_display.drawPixel(dx + (y - miny), dy + (maxx - x), SSD1306_WHITE);
}

static void displayFooter(const char* text) {
    g_display.setTextSize(1);
    g_display.setCursor(0, SCREEN_HEIGHT - 9);
    g_display.print(text);
}

static void displayShowReady() {
    g_display.clearDisplay();
    displayHeader("SANKET  * ready");
    displayBangla("লিখুন");                   // "write" prompt
    displayFooter("move wrist to start");
    g_display.display();
}

static void displayShowCapturing(float energy) {
    g_display.clearDisplay();
    displayHeader("* CAPTURING");
    displayBangla("লিখছেন");                  // "writing..."
    char buf[32];
    snprintf(buf, sizeof(buf), "energy %.0f /s", energy);
    displayFooter(buf);
    g_display.display();
}

static void displayShowResult(int class_id, float conf, bool detected) {
    g_display.clearDisplay();
    char hdr[48];
    if (detected) {
        snprintf(hdr, sizeof(hdr), "DETECTED  %d%%", (int)(conf * 100));
    } else {
        snprintf(hdr, sizeof(hdr), "unclear   %d%% %s",
                 (int)(conf * 100), MODEL_CLASS_NAMES[class_id]);
    }
    displayHeader(hdr);
    displayBangla(CLASS_BANGLA[class_id]);
    displayFooter(MODEL_CLASS_NAMES[class_id]);
    g_display.display();
}

static void displayShowCooldown() {
    // Keep the result up but add a small marker. For simplicity we don't
    // repaint — the last displayShowResult() frame stays until the next
    // STATE_CAPTURING or STATE_IDLE transition.
}

static bool setupOLED() {
    Wire1.begin(PIN_OLED_SDA, PIN_OLED_SCL, 400000UL);
    if (!g_display.begin(SSD1306_SWITCHCAPVCC, SCREEN_ADDR)) {
        Serial.println("E,oled_init_fail");
        return false;
    }
    g_bangla_font = BanglaMNRegular_25pt;
    g_bangla_renderer = new BanglaTextRenderer(&g_bangla_font);
    g_display.clearDisplay();
    g_display.setTextSize(1);
    g_display.setTextColor(SSD1306_WHITE);
    g_display.setCursor(0, 0);
    g_display.println("SANKET boot...");
    g_display.display();
    return true;
}

// ============================================================================
//                               MPU6050 helpers
// ============================================================================
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

static bool readIMU(int16_t out[6]) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((int)MPU_ADDR, 14);
  if (Wire.available() < 14) return false;
  out[0] = (int16_t)((Wire.read() << 8) | Wire.read());
  out[1] = (int16_t)((Wire.read() << 8) | Wire.read());
  out[2] = (int16_t)((Wire.read() << 8) | Wire.read());
  Wire.read(); Wire.read();
  out[3] = (int16_t)((Wire.read() << 8) | Wire.read());
  out[4] = (int16_t)((Wire.read() << 8) | Wire.read());
  out[5] = (int16_t)((Wire.read() << 8) | Wire.read());
  return true;
}

static bool configureMPU() {
  if (!mpuWrite(REG_PWR_MGMT_1, 0x01)) return false;
  delay(50);
  uint8_t who = mpuRead(REG_WHO_AM_I);
  if (who != 0x68 && who != 0x70 && who != 0x71 && who != 0x72 && who != 0x98) {
    Serial.printf("E,who_am_i=0x%02X\n", who);
    return false;
  }
  if (!mpuWrite(REG_SMPLRT_DIV,   0x09)) return false;
  if (!mpuWrite(REG_CONFIG,       0x03)) return false;
  if (!mpuWrite(REG_GYRO_CONFIG,  0x08)) return false;
  if (!mpuWrite(REG_ACCEL_CONFIG, 0x08)) return false;
  delay(50);
  return true;
}

static void calibrate() {
  Serial.println("C,START");
  delay(500);
  double sum[6] = {0};
  int16_t raw[6];
  uint32_t taken = 0;
  for (uint32_t i = 0; i < CALIB_SAMPLES; i++) {
    if (readIMU(raw)) {
      for (int j = 0; j < 6; j++) sum[j] += raw[j];
      taken++;
    }
    delay(10);
  }
  if (taken == 0) { Serial.println("E,calib_no_data"); return; }
  for (int j = 0; j < 6; j++) g_offset_raw[j] = (float)(sum[j] / taken);
  Serial.printf("C,DONE,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f\n",
    g_offset_raw[0] / ACCEL_LSB_PER_G,
    g_offset_raw[1] / ACCEL_LSB_PER_G,
    g_offset_raw[2] / ACCEL_LSB_PER_G,
    g_offset_raw[3] / GYRO_LSB_PER_DPS,
    g_offset_raw[4] / GYRO_LSB_PER_DPS,
    g_offset_raw[5] / GYRO_LSB_PER_DPS);
  for (int j = 0; j < 6; j++) g_filtered[j] = 0.0f;
}

// ============================================================================
//                               TFLite setup
// ============================================================================
static bool setupTFLite() {
  model = tflite::GetModel(sanket_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("E,model_schema_version=%d expected=%d\n",
                  model->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }
  static tflite::MicroMutableOpResolver<6> resolver;
  resolver.AddConv2D();
  resolver.AddExpandDims();
  resolver.AddFullyConnected();
  resolver.AddMean();
  resolver.AddReshape();
  resolver.AddSoftmax();

  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaSize);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("E,allocate_tensors_failed");
    return false;
  }

  input  = interpreter->input(0);
  output = interpreter->output(0);
  size_t used = interpreter->arena_used_bytes();
  Serial.printf("I,arena_used=%u/%d\n", (unsigned)used, kTensorArenaSize);
  return true;
}

// ============================================================================
//                               Inference task (core 0)
// ============================================================================
static void inferTask(void* /*unused*/) {
  const float  in_scale  = input->params.scale;
  const int    in_zp     = input->params.zero_point;
  const float  out_scale = output->params.scale;
  const int    out_zp    = output->params.zero_point;
  int idle_idx = -1;
  for (int k = 0; k < MODEL_CLASSES; k++) {
    if (strcmp(MODEL_CLASS_NAMES[k], "idle") == 0) { idle_idx = k; break; }
  }

  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    xSemaphoreTake(g_snap_mutex, portMAX_DELAY);
    int8_t* in_data = input->data.int8;
    for (int i = 0; i < MODEL_WINDOW; i++) {
      for (int c = 0; c < MODEL_CHANNELS; c++) {
        float norm = (g_snapshot[i][c] - MODEL_MU[c]) / MODEL_SD[c];
        int   q    = (int)lroundf(norm / in_scale) + in_zp;
        if (q < -128) q = -128; else if (q > 127) q = 127;
        in_data[i * MODEL_CHANNELS + c] = (int8_t)q;
      }
    }
    xSemaphoreGive(g_snap_mutex);

    uint32_t t0 = millis();
    if (interpreter->Invoke() != kTfLiteOk) {
      Serial.println("E,invoke_failed");
      continue;
    }
    uint32_t dt = millis() - t0;

    float probs[MODEL_CLASSES];
    int   top   = 0;
    float top_p = -1.0f;
    for (int k = 0; k < MODEL_CLASSES; k++) {
      probs[k] = ((int)output->data.int8[k] - out_zp) * out_scale;
      if (probs[k] > top_p) { top_p = probs[k]; top = k; }
    }

    Serial.printf("INFER,top=%s,conf=%.3f,infer_ms=%u,probs=[",
                  MODEL_CLASS_NAMES[top], top_p, (unsigned)dt);
    for (int k = 0; k < MODEL_CLASSES; k++) {
      Serial.printf("%s%s:%.3f",
                    (k == 0 ? "" : ","), MODEL_CLASS_NAMES[k], probs[k]);
    }
    Serial.println("]");

    bool detected = (top != idle_idx && top_p >= DETECT_CONF);
    if (detected) {
      Serial.printf("DETECTED,%s,%.3f\n", MODEL_CLASS_NAMES[top], top_p);
    }

    // Push result to the OLED (I2C on Wire1, ~20 ms, happens during cooldown
    // so it doesn't disrupt sampling)
    displayShowResult(top, top_p, detected);
  }
}

// ---------- Capture end — snapshot + notify ----------
static void finishCapture(const char* reason) {
  uint32_t n = g_capture_idx;
  float elapsed = (float)n / SAMPLE_RATE_HZ;

  if (n < MIN_CAP_SMPL) {
    Serial.printf("STATE,FINISH,n=%u,elapsed=%.2fs,reason=short_discard\n",
                  (unsigned)n, elapsed);
    g_state = S_IDLE;
    Serial.println("STATE,IDLE");
    displayShowReady();
    return;
  }

  Serial.printf("STATE,FINISH,n=%u,elapsed=%.2fs,reason=%s\n",
                (unsigned)n, elapsed, reason);

  if (xSemaphoreTake(g_snap_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
    for (uint32_t i = 0; i < n; i++) {
      for (int c = 0; c < MODEL_CHANNELS; c++) {
        g_snapshot[i][c] = g_capture_buf[i][c];
      }
    }
    for (uint32_t i = n; i < MODEL_WINDOW; i++) {
      for (int c = 0; c < MODEL_CHANNELS; c++) g_snapshot[i][c] = 0.0f;
    }
    xSemaphoreGive(g_snap_mutex);
    xTaskNotifyGive(g_infer_task_handle);
  } else {
    Serial.println("E,snap_mutex_busy");
  }

  g_state = S_COOLDOWN;
  g_cooldown_left = COOLDOWN_SMPL;
  Serial.println("STATE,COOLDOWN");
  // Display update for the result will happen from inferTask when invoke
  // finishes (~40 ms later), during cooldown.
}

// ============================================================================
//                               setup / loop
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println("H,SANKET-infer,v3,motion-trigger+oled,100hz");

  // Primary I2C — MPU6050
  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
  if (!configureMPU()) {
    Serial.println("E,mpu_init_fail");
    while (true) { delay(1000); Serial.println("E,mpu_init_fail"); }
  }
  calibrate();

  // Secondary I2C — SSD1306 OLED (non-fatal if missing, keep running)
  if (!setupOLED()) {
    Serial.println("W,oled_not_found_continuing_without_display");
  }

  if (!setupTFLite()) {
    while (true) { delay(1000); Serial.println("E,tflite_init_fail"); }
  }

  g_snap_mutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(inferTask, "infer", 16384, nullptr,
                          1 /*prio*/, &g_infer_task_handle, 0 /*core*/);

  Serial.printf("I,ready,thresh=%.1f,maxcap=%.2fs,mincap=%.2fs,settle=%.2fs,cooldown=%.2fs,classes=%d\n",
                TRIG_THRESH_DPS, MAX_CAPTURE_S, MIN_CAPTURE_S, STOP_SETTLE_S,
                COOLDOWN_S, MODEL_CLASSES);
  Serial.print("I,class_order=");
  for (int k = 0; k < MODEL_CLASSES; k++) {
    Serial.printf("%s%s", (k == 0 ? "" : ","), MODEL_CLASS_NAMES[k]);
  }
  Serial.println();
  Serial.println("STATE,IDLE");
  displayShowReady();

  g_next_sample_us = micros() + SAMPLE_PERIOD_US;
}

void loop() {
  uint32_t now_us = micros();
  if ((int32_t)(now_us - g_next_sample_us) < 0) return;
  g_next_sample_us += SAMPLE_PERIOD_US;

  int16_t raw[6];
  if (!readIMU(raw)) { Serial.println("E,read_fail"); return; }

  float sample[6];
  sample[0] = (raw[0] - g_offset_raw[0]) / ACCEL_LSB_PER_G;
  sample[1] = (raw[1] - g_offset_raw[1]) / ACCEL_LSB_PER_G;
  sample[2] = (raw[2] - g_offset_raw[2]) / ACCEL_LSB_PER_G;
  sample[3] = (raw[3] - g_offset_raw[3]) / GYRO_LSB_PER_DPS;
  sample[4] = (raw[4] - g_offset_raw[4]) / GYRO_LSB_PER_DPS;
  sample[5] = (raw[5] - g_offset_raw[5]) / GYRO_LSB_PER_DPS;

  for (int j = 0; j < 6; j++) {
    g_filtered[j] = FILTER_ALPHA * sample[j] + (1.0f - FILTER_ALPHA) * g_filtered[j];
  }

  float gx = g_filtered[3], gy = g_filtered[4], gz = g_filtered[5];
  float mag = sqrtf(gx*gx + gy*gy + gz*gz);
  g_energy_ring[g_energy_ptr] = mag;
  g_energy_ptr = (g_energy_ptr + 1) % ENERGY_WIN;
  float energy = 0.0f;
  for (uint32_t i = 0; i < ENERGY_WIN; i++)
    if (g_energy_ring[i] > energy) energy = g_energy_ring[i];

  switch (g_state) {
    case S_IDLE: {
      if (energy >= TRIG_THRESH_DPS) {
        g_state = S_CAPTURING;
        g_capture_idx = 0;
        g_settled_count = 0;
        Serial.printf("STATE,CAPTURING,energy=%.1f\n", energy);
        displayShowCapturing(energy);   // ~20 ms I2C blip, fine at start of capture
      } else {
        g_live_tx_counter++;
        if (g_live_tx_counter >= LIVE_TX_PERIOD) {
          g_live_tx_counter = 0;
          Serial.printf("LIVE,energy=%.1f\n", energy);
        }
      }
      break;
    }

    case S_CAPTURING: {
      if (g_capture_idx < MODEL_WINDOW) {
        for (int c = 0; c < MODEL_CHANNELS; c++) {
          g_capture_buf[g_capture_idx][c] = g_filtered[c];
        }
        g_capture_idx++;
      }

      if (energy >= TRIG_THRESH_DPS) {
        g_settled_count = 0;
      } else {
        g_settled_count++;
      }

      if ((g_capture_idx % CAP_TX_PERIOD) == 0) {
        float elapsed = (float)g_capture_idx / SAMPLE_RATE_HZ;
        Serial.printf("CAP,n=%u,elapsed=%.2fs,energy=%.1f,settled=%u\n",
                      (unsigned)g_capture_idx, elapsed, energy,
                      (unsigned)g_settled_count);
      }

      if (g_capture_idx >= MAX_CAP_SMPL) {
        finishCapture("max_cap");
      } else if (g_capture_idx >= MIN_CAP_SMPL && g_settled_count >= SETTLE_SMPL) {
        finishCapture("settled");
      }
      break;
    }

    case S_COOLDOWN: {
      if (g_cooldown_left > 0) g_cooldown_left--;
      if (g_cooldown_left == 0) {
        g_state = S_IDLE;
        g_live_tx_counter = 0;
        Serial.println("STATE,IDLE");
        displayShowReady();
      }
      break;
    }
  }
}
