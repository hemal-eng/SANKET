// SANKET — model normalization + labels (auto-regenerated).
// Per-channel mean/std used during training; MUST be applied before feeding
// data to the model.
#pragma once

constexpr int   MODEL_WINDOW   = 600;
constexpr int   MODEL_CHANNELS = 6;
constexpr int   MODEL_CLASSES  = 8;

// Order: ax, ay, az (g), gx, gy, gz (°/s)
constexpr float MODEL_MU[6] = {
    -0.2722071111f,
    0.0085783144f,
    -0.4693828523f,
    0.6768615246f,
    0.8164339066f,
    2.1612236500f
};
constexpr float MODEL_SD[6] = {
    0.4862846136f,
    0.4330985248f,
    0.4913423657f,
    66.1413192749f,
    57.3431510925f,
    57.2136650085f
};

// Class names (index == softmax output id)
constexpr const char* MODEL_CLASS_NAMES[MODEL_CLASSES] = {
    "idle",
    "ami",
    "haan",
    "dhonnobad",
    "pani",
    "khabar",
    "shahajjo",
    "salam"
};
