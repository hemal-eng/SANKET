// SANKET — DFPlayer Mini PHASE 1 standalone test
// ----------------------------------------------
// Only the DFPlayer: no MPU, no TFLite, no OLED.
// The full firmware is backed up in src/test/main_oled_bangla270_working.cpp.
//
// Wiring (ESP32-S3 → DFPlayer Mini):
//   GPIO 17 (TX) ──[1 kΩ]──► RX
//   GPIO 18 (RX) ◄─────────  TX
//   GPIO 16      ◄─────────  BUSY   (LOW = playing)
//   5V → VCC, GND → GND, speaker on SPK_1 / SPK_2
// SD card: /mp3/0001.mp3 … 0007.mp3
//
// On boot it plays all 7 files once, in order. Then type in the serial
// monitor (115200 baud):
//   1..7  play that file      a  play all again
//   +  -  volume up / down    s  stop       ?  status

#include <Arduino.h>
#include <DFRobotDFPlayerMini.h>

static const int PIN_DF_TX   = 17;   // ESP32 TX → DFPlayer RX
static const int PIN_DF_RX   = 18;   // ESP32 RX ← DFPlayer TX
static const int PIN_DF_BUSY = 16;   // LOW while playing

static const int NUM_TRACKS     = 7;
static const int START_VOLUME   = 25;   // 0..30

static const char* TRACK_NAMES[NUM_TRACKS + 1] = {
    "", "ami", "haan", "dhonnobad", "pani", "khabar", "shahajjo", "salam"
};

HardwareSerial      dfSerial(2);
DFRobotDFPlayerMini player;
static int          g_volume = START_VOLUME;

static bool isBusy() { return digitalRead(PIN_DF_BUSY) == LOW; }

// Play one track and block until it finishes (BUSY goes HIGH), with timeouts.
static void playAndWait(int n) {
    Serial.printf("PLAY,track=%d,name=%s\n", n, TRACK_NAMES[n]);
    uint32_t t0 = millis();
    player.playMp3Folder(n);

    // BUSY goes LOW within ~100–300 ms of the command
    while (!isBusy() && millis() - t0 < 1000) delay(5);
    if (!isBusy()) {
        Serial.printf("WARN,track=%d,busy_never_went_low (check BUSY wire / file exists)\n", n);
        delay(3000);
        return;
    }
    uint32_t t_start = millis();
    while (isBusy() && millis() - t_start < 10000) delay(5);
    Serial.printf("DONE,track=%d,played_ms=%lu\n", n, (unsigned long)(millis() - t_start));
}

static void playAll() {
    for (int n = 1; n <= NUM_TRACKS; n++) {
        playAndWait(n);
        delay(600);
    }
    Serial.println("ALL,done");
}

static void printPlayerEvent(uint8_t type, int value) {
    switch (type) {
        case TimeOut:              Serial.println("EVT,timeout"); break;
        case WrongStack:           Serial.println("EVT,wrong_stack"); break;
        case DFPlayerCardInserted: Serial.println("EVT,card_inserted"); break;
        case DFPlayerCardRemoved:  Serial.println("EVT,card_removed"); break;
        case DFPlayerCardOnline:   Serial.println("EVT,card_online"); break;
        case DFPlayerPlayFinished: Serial.printf("EVT,play_finished,%d\n", value); break;
        case DFPlayerError:        Serial.printf("EVT,error,code=%d\n", value); break;
        default: break;
    }
}

void setup() {
    Serial.begin(115200);
    delay(600);
    Serial.println();
    Serial.println("H,SANKET-dfplayer-test,phase1");

    pinMode(PIN_DF_BUSY, INPUT_PULLUP);
    dfSerial.begin(9600, SERIAL_8N1, PIN_DF_RX, PIN_DF_TX);

    // DFPlayer needs ~1–2 s after power-up to read the SD card
    Serial.println("DF,waiting_for_module");
    delay(1500);

    if (!player.begin(dfSerial, /*isACK=*/true, /*doReset=*/true)) {
        Serial.println("E,dfplayer_not_responding");
        Serial.println("  check: 5V on VCC, common GND, TX17->RX via 1k, RX18<-TX, SD card inserted");
        while (true) { delay(2000); Serial.println("E,dfplayer_not_responding"); }
    }
    Serial.println("DF,online");

    player.setTimeOut(600);
    player.volume(g_volume);
    player.EQ(DFPLAYER_EQ_NORMAL);
    delay(200);

    int files = player.readFileCounts();
    Serial.printf("DF,files_on_card=%d,expected=%d,volume=%d\n", files, NUM_TRACKS, g_volume);
    if (files != NUM_TRACKS) {
        Serial.println("W,file_count_mismatch (macOS hidden files on card, or wrong folder)");
    }

    Serial.println("TEST,play_all_once");
    playAll();
    Serial.println("READY,type 1-7 / a / + / - / s / ?");
}

void loop() {
    if (player.available()) printPlayerEvent(player.readType(), player.read());

    if (!Serial.available()) return;
    char c = Serial.read();

    if (c >= '1' && c <= '0' + NUM_TRACKS) {
        playAndWait(c - '0');
    } else if (c == 'a') {
        playAll();
    } else if (c == '+') {
        g_volume = min(30, g_volume + 2);
        player.volume(g_volume);
        Serial.printf("VOL,%d\n", g_volume);
    } else if (c == '-') {
        g_volume = max(0, g_volume - 2);
        player.volume(g_volume);
        Serial.printf("VOL,%d\n", g_volume);
    } else if (c == 's') {
        player.stop();
        Serial.println("STOP");
    } else if (c == '?') {
        Serial.printf("STATUS,busy=%d,volume=%d,files=%d\n",
                      isBusy(), g_volume, player.readFileCounts());
    }
}
