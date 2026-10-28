// SANKET — ON-DEVICE INFERENCE FIRMWARE
//   A Wrist-Worn ESP32-S3 TinyML System for Bangla Deaf-Aid
//   Air-Written Gesture Recognition.
// Target : ESP32-S3-DevKitC-1 (N16R8), UART USB port (CH343/CP2102)
// Sensor : MPU6050 (I2C @ 0x68) on SDA=GPIO 8, SCL=GPIO 9
//
// This firmware runs the quantized int8 TFLite model locally. It keeps a
// 600-sample ring buffer (6 s at 100 Hz) of IMU readings and invokes the
// model every ~300 ms. Each inference prints exactly one line on serial:
//
//     P,<class_name>,<confidence>
//
// where confidence is a float in [0, 1]. Example:
//     P,ami,0.92
//     P,idle,0.98
//
// A big "AMI DETECTED" line is also printed when ami confidence > 0.75 for
// two consecutive inferences, so you can watch Serial Monitor and see it.

#include <Arduino.h>
#include <Wire.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>

// Official Espressif TFLite-Micro (ESP32-S3-optimized via esp-nn).
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "model_data.h"
#include "model_norm.h"

// ---------- Pins ----------
static const int PIN_SDA = 8;
static const int PIN_SCL = 9;

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

// ---------- Config ----------
static const uint32_t SAMPLE_RATE_HZ    = 100;
static const uint32_t SAMPLE_PERIOD_US  = 1000000UL / SAMPLE_RATE_HZ;
static const uint32_t CALIB_SAMPLES     = 200;
static constexpr float FILTER_ALPHA     = 0.30f;
static const uint32_t INFER_STRIDE_SMPL = 30;        // run inference every 30 new samples (~300ms)
static const float    CONF_THRESHOLD    = 0.75f;
static const uint8_t  CONSEC_FRAMES     = 2;

// ---------- IMU state ----------
float    g_offset_raw[6] = {0, 0, 0, 0, 0, 0};
float    g_filtered[6]   = {0, 0, 0, 0, 0, 0};
uint32_t g_next_sample_us = 0;
uint32_t g_last_live_tx_us = 0;

// ---------- Ring buffer of the latest MODEL_WINDOW samples ----------
static float    g_ring[MODEL_WINDOW][MODEL_CHANNELS];
static uint32_t g_ring_ptr   = 0;
static uint32_t g_ring_total = 0;             // monotonically increasing count
static uint32_t g_last_infer_total = 0;

// ---------- Dual-core inference plumbing ----------
// loop() samples at 100 Hz on core 1 and never blocks on inference.
// A dedicated FreeRTOS task on core 0 runs the model in parallel.
// When loop() has enough new samples it snapshots the ring (brief memcpy
// under a mutex) and notifies the inference task.
static float             g_snapshot[MODEL_WINDOW][MODEL_CHANNELS];
static SemaphoreHandle_t g_snap_mutex       = nullptr;
static TaskHandle_t      g_infer_task_handle = nullptr;

// ---------- TFLite micro globals ----------
namespace {
const tflite::Model*          model          = nullptr;
tflite::MicroInterpreter*     interpreter    = nullptr;
TfLiteTensor*                 input          = nullptr;
TfLiteTensor*                 output         = nullptr;

// Arena. The model is ~17KB with Conv1D/BN/Dense on (600,6). ~90KB arena is
// a safe starting point; adjust up if interpreter.AllocateTensors() fails.
constexpr int kTensorArenaSize = 90 * 1024;
alignas(16) uint8_t tensor_arena[kTensorArenaSize];
}

static uint8_t  g_consec_ami = 0;

// ---------- MPU6050 helpers ----------
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
  Wire.read(); Wire.read();  // temp
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
  if (!mpuWrite(REG_SMPLRT_DIV,   0x09)) return false;  // 100 Hz
  if (!mpuWrite(REG_CONFIG,       0x03)) return false;  // DLPF 44 Hz
  if (!mpuWrite(REG_GYRO_CONFIG,  0x08)) return false;  // ±500 dps
  if (!mpuWrite(REG_ACCEL_CONFIG, 0x08)) return false;  // ±4 g
  delay(50);
  return true;
}

static void calibrate() {
  Serial.println("C,START");
  delay(500);
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

// ---------- TFLite setup ----------
static bool setupTFLite() {
  model = tflite::GetModel(sanket_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.printf("E,model_schema_version=%d expected=%d\n",
                  model->version(), TFLITE_SCHEMA_VERSION);
    return false;
  }

  // Exact ops present in banglasign_int8.tflite (per Python inspection):
  //   CONV_2D, EXPAND_DIMS, FULLY_CONNECTED, MEAN, RESHAPE, SOFTMAX
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
  return true;
}

// ---------- Inference task (runs on core 0, parallel to sampling) ----------
static void inferTask(void* /*unused*/) {
  const float  in_scale  = input->params.scale;
  const int    in_zp     = input->params.zero_point;
  const float  out_scale = output->params.scale;
  const int    out_zp    = output->params.zero_point;
  int ami_idx = -1;
  for (int k = 0; k < MODEL_CLASSES; k++) {
    if (strcmp(MODEL_CLASS_NAMES[k], "ami") == 0) { ami_idx = k; break; }
  }

  for (;;) {
    // Wait for loop() to tell us a fresh snapshot is ready.
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    // Normalize + quantize the snapshot into the input tensor.
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

    // Invoke (slow — but we're on core 0, loop keeps sampling on core 1).
    if (interpreter->Invoke() != kTfLiteOk) {
      Serial.println("E,invoke_failed");
      continue;
    }

    // Dequantize output
    float probs[MODEL_CLASSES];
    for (int k = 0; k < MODEL_CLASSES; k++) {
      probs[k] = ((int)output->data.int8[k] - out_zp) * out_scale;
    }

    // Find top class
    int   top   = 0;
    float top_p = probs[0];
    for (int k = 1; k < MODEL_CLASSES; k++) {
      if (probs[k] > top_p) { top_p = probs[k]; top = k; }
    }

    //   P,idle,0.996
    //   P,ami,0.942
    Serial.printf("P,%s,%.3f\n", MODEL_CLASS_NAMES[top], top_p);

    // ami detection streak
    if (ami_idx >= 0 && probs[ami_idx] > CONF_THRESHOLD) {
      if (g_consec_ami < 255) g_consec_ami++;
    } else {
      g_consec_ami = 0;
    }
    if (g_consec_ami == CONSEC_FRAMES) {
      Serial.printf("DETECTED,ami,%.3f\n", probs[ami_idx]);
    }
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(921600);
  delay(600);
  Serial.println("H,SANKET-infer,v1,100hz,on-device");

  Wire.begin(PIN_SDA, PIN_SCL, 400000UL);
  if (!configureMPU()) {
    Serial.println("E,mpu_init_fail");
    while (true) { delay(1000); Serial.println("E,mpu_init_fail"); }
  }
  calibrate();

  if (!setupTFLite()) {
    while (true) { delay(1000); Serial.println("E,tflite_init_fail"); }
  }

  // Spin up the inference task on core 0 so loop() on core 1 can sample
  // without ever blocking on Invoke(). 16 KB stack is generous for TFLM.
  g_snap_mutex = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(inferTask, "infer", 16384, nullptr,
                          1 /*prio*/, &g_infer_task_handle, 0 /*core*/);
  Serial.println("I,ready");

  // Prime the ring buffer with zeros (already zero-initialized)
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

  // IIR low-pass per channel
  for (int j = 0; j < 6; j++) {
    g_filtered[j] = FILTER_ALPHA * sample[j] + (1.0f - FILTER_ALPHA) * g_filtered[j];
  }

  // Write to ring buffer at the OLDEST slot (which is g_ring_ptr), then advance
  for (int c = 0; c < MODEL_CHANNELS; c++) {
    g_ring[g_ring_ptr][c] = g_filtered[c];
  }
  g_ring_ptr = (g_ring_ptr + 1) % MODEL_WINDOW;
  g_ring_total++;

  // Trigger inference once the buffer is full, every INFER_STRIDE_SMPL samples.
  // Snapshot the ring under the mutex (brief memcpy) and notify core-0.
  // If the inferer is still busy with the previous snapshot, we try next
  // trigger — never block sampling.
  if (g_ring_total >= MODEL_WINDOW &&
      (g_ring_total - g_last_infer_total) >= INFER_STRIDE_SMPL) {
    if (xSemaphoreTake(g_snap_mutex, 0) == pdTRUE) {
      g_last_infer_total = g_ring_total;
      for (int i = 0; i < MODEL_WINDOW; i++) {
        uint32_t idx = (g_ring_ptr + i) % MODEL_WINDOW;
        memcpy(g_snapshot[i], g_ring[idx], sizeof(float) * MODEL_CHANNELS);
      }
      xSemaphoreGive(g_snap_mutex);
      xTaskNotifyGive(g_infer_task_handle);
    }
    // else: inference busy — skip this cycle, try again at the next stride.
  }
}
