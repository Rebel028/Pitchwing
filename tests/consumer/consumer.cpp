#if defined(_WIN32)
#if defined(PITCHWING_CONSUMER_DRIVER)
#define PITCHWING_CONSUMER_EXPORT __declspec(dllimport)
#else
#define PITCHWING_CONSUMER_EXPORT __declspec(dllexport)
#endif
#else
#define PITCHWING_CONSUMER_EXPORT
#endif

extern "C" PITCHWING_CONSUMER_EXPORT int pitchwing_consumer_check();

#if defined(PITCHWING_CONSUMER_DRIVER)

int main() { return pitchwing_consumer_check(); }

#else

#include <pitchwing/LiveEngine.hpp>

#include <array>
#include <cmath>
#include <cstddef>

extern "C" PITCHWING_CONSUMER_EXPORT int pitchwing_consumer_check() {
    pitchwing::LiveConfig config;
    config.sampleRate = 48000.0;
    pitchwing::LiveEngine engine(config);
    const auto latency = engine.latencySamples();
    if (latency == 0 || latency > 480 || engine.config().sampleRate != 48000.0) {
        return 1;
    }
    std::array<float, 1024> left{}, right{}, outLeft{}, outRight{};
    left[11] = 0.25f;
    right[11] = -0.125f;
    if (engine.process(left.data(), right.data(), outLeft.data(), outRight.data(),
                       left.size()) != pitchwing::Status::Ok) {
        return 2;
    }
    for (std::size_t i = 0; i < left.size(); ++i) {
        const auto expectedLeft = i == latency + 11 ? 0.25f : 0.0f;
        const auto expectedRight = i == latency + 11 ? -0.125f : 0.0f;
        if (!std::isfinite(outLeft[i]) || !std::isfinite(outRight[i]) ||
            std::abs(outLeft[i] - expectedLeft) > 1e-5f ||
            std::abs(outRight[i] - expectedRight) > 1e-5f) {
            return 3;
        }
    }
    for (const auto shift : {49.0, -49.0, 0.0}) {
        if (engine.setPitchSemitones(shift) != pitchwing::Status::Ok ||
            engine.process(left.data(), right.data(), outLeft.data(), outRight.data(),
                           1) != pitchwing::Status::Ok ||
            engine.latencySamples() != latency) {
            return 4;
        }
    }
    return engine.reset() == pitchwing::Status::Ok ? 0 : 5;
}

#endif
