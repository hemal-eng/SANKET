// SANKET — DFPlayer Mini audio module.
// Track N on the SD card (/mp3/000N.mp3) == model class id N (idle = 0, never played).
#pragma once
#include <Arduino.h>

// Starts UART2 + the DFPlayer. Blocks ~2-3 s (module boot + reset).
// Returns false if the module doesn't answer; audio then stays disabled.
bool audioInit(int rx_pin, int tx_pin, int busy_pin, uint8_t volume);

bool audioReady();
int  audioFileCount();          // files the DFPlayer sees on the card, -1 if offline
void audioPlay(int track);      // plays /mp3/000<track>.mp3, ignored if offline

// True while a word is playing. Also true for a short grace period right
// after audioPlay(), because the BUSY pin only goes LOW ~100-300 ms later.
bool audioActive();
