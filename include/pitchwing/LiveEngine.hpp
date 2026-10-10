#ifndef PITCHWING_LIVE_ENGINE_HPP
#define PITCHWING_LIVE_ENGINE_HPP

#include <pitchwing/Engine.hpp>

#include <cstddef>
#include <memory>

namespace pitchwing {

struct LiveConfig {
    double sampleRate = 48000.0;
    double pitchSemitones = 0.0;
};

/// Linked-stereo, live-ratio engine. Exclusive caller access is required.
/// Prepare/move/destroy outside audio callbacks; process/reset/setter allocate
/// nothing. Configuration accepts 8--192 kHz and [-49, 49] semitones.
class LiveEngine {
public:
    explicit LiveEngine(const LiveConfig& config = {});
    ~LiveEngine();
    LiveEngine(LiveEngine&& other) noexcept;
    LiveEngine& operator=(LiveEngine&& other) noexcept;
    LiveEngine(const LiveEngine&) = delete;
    LiveEngine& operator=(const LiveEngine&) = delete;

    /// Planar stereo; exact in-place and duplicated mono inputs are supported.
    /// Output channels must not overlap. Samples must be finite and |x| <= 1e30
    /// in both precisions, allowing safe mixed-precision streams. Invalid blocks
    /// leave state/output intact.
    Status process(const float* left, const float* right, float* outLeft,
                   float* outRight, std::size_t frames) noexcept;
    Status process(const double* left, const double* right, double* outLeft,
                   double* outRight, std::size_t frames) noexcept;

    /// Offline terminal drain; capacity must be at least tailSamples().
    Status flush(float* outLeft, float* outRight, std::size_t capacity,
                 std::size_t& written) noexcept;
    Status flush(double* outLeft, double* outRight, std::size_t capacity,
                 std::size_t& written) noexcept;

    Status reset() noexcept;
    /// New target applies from the next input sample, without resetting history.
    Status setPitchSemitones(double value) noexcept;
    std::size_t latencySamples() const noexcept;
    std::size_t tailSamples() const noexcept;
    std::size_t analysisSize() const noexcept;
    std::size_t synthesisSize() const noexcept;
    std::size_t hopSamples() const noexcept;
    LiveConfig config() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace pitchwing

#endif
