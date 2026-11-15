#include "audio.h"
#include <DFRobotDFPlayerMini.h>

namespace {
HardwareSerial          g_df_serial(2);
DFRobotDFPlayerMini     g_player;
bool                    g_ok        = false;
int                     g_busy_pin  = -1;
volatile bool           g_played    = false;
volatile uint32_t       g_play_ms   = 0;
constexpr uint32_t      kStartGraceMs = 500;
}

bool audioInit(int rx_pin, int tx_pin, int busy_pin, uint8_t volume) {
    g_busy_pin = busy_pin;
    pinMode(busy_pin, INPUT_PULLUP);
    g_df_serial.begin(9600, SERIAL_8N1, rx_pin, tx_pin);
    delay(1500);  // DFPlayer reads the SD card after power-up

    if (!g_player.begin(g_df_serial, /*isACK=*/true, /*doReset=*/true)) {
        g_ok = false;
        return false;
    }
    g_player.setTimeOut(600);
    g_player.volume(volume);
    g_player.EQ(DFPLAYER_EQ_NORMAL);
    g_ok = true;
    return true;
}

bool audioReady() { return g_ok; }

int audioFileCount() { return g_ok ? g_player.readFileCounts() : -1; }

void audioPlay(int track) {
    if (!g_ok || track < 1) return;
    g_play_ms = millis();
    g_played  = true;
    g_player.playMp3Folder(track);
}

bool audioActive() {
    if (!g_ok) return false;
    if (g_played && millis() - g_play_ms < kStartGraceMs) return true;
    return digitalRead(g_busy_pin) == LOW;
}
