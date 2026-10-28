// SANKET — model normalization constants (auto-generated from norm.json).
// Per-channel mean/std used during training; MUST be applied before feeding
// data to the model.
#pragma once

constexpr int   MODEL_WINDOW   = 600;
constexpr int   MODEL_CHANNELS = 6;
constexpr int   MODEL_CLASSES  = 2;

// Order: ax, ay, az (g), gx, gy, gz (°/s)
constexpr float MODEL_MU[6] = {
    -0.027055740356445312f,
     0.21883641183376312f,
    -0.12755762040615082f,
     5.55214786529541f,
     1.0101189613342285f,
     1.6056228876113892f
};
constexpr float MODEL_SD[6] = {
     0.354187548160553f,
     0.4231823980808258f,
     0.3928932845592499f,
    49.249820709228516f,
    30.566730499267578f,
    44.00409698486328f
};

// Class names (order matches softmax output index)
constexpr const char* MODEL_CLASS_NAMES[MODEL_CLASSES] = {
    "idle",
    "ami"
};
