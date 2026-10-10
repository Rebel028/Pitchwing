#ifndef PITCHWING_ENGINE_HPP
#define PITCHWING_ENGINE_HPP

#include <cstddef>
#include <memory>

namespace pitchwing {

enum class Window { Asymmetric, Symmetric };

struct EngineConfig {
    double sampleRate = 48000.0;
    std::size_t analysisSize = 2048;
    std::size_t synthesisSize = 384;
    std::size_t hop = 96;
    double pitchSemitones = 0.0;
    Window window = Window::Asymmetric;
};

enum class Status {
    Ok,
    InvalidBuffer,
    InvalidSample,
    InvalidPitch,
    PitchLocked,
    StreamClosed,
    BufferTooSmall,
    NotPrepared
};

/// Reusable mono, static-ratio research engine. Instances are not thread-safe.
/// Preparation may allocate/throw; processing and reset allocate nothing.
/// Known low-register/DC flaws are retained from the reference experiment.
/// Sizes must be even and 65536 >= analysisSize >= synthesisSize >= 8.
class Engine {
public:
    explicit Engine(const EngineConfig& config = {});
    ~Engine();
    Engine(Engine&& other) noexcept;
    Engine& operator=(Engine&& other) noexcept;
    Engine(const Engine&) = delete;
    Engine& operator=(const Engine&) = delete;

    /// Writes count samples. Exact in-place use is allowed; partial overlap is
    /// rejected. Validation failure leaves output and processing state intact.
    Status process(const double* input, double* output, std::size_t count) noexcept;
    Status process(const float* input, float* output, std::size_t count) noexcept;

    /// First flush requires tailSamples() capacity and closes the stream.
    /// Repeated flush succeeds with written=0. Failure also sets written=0.
    Status flush(double* output, std::size_t capacity, std::size_t& written) noexcept;
    Status flush(float* output, std::size_t capacity, std::size_t& written) noexcept;

    Status reset() noexcept;
    Status setPitchSemitones(double value) noexcept;
    std::size_t latencySamples() const noexcept;
    std::size_t tailSamples() const noexcept;
    EngineConfig config() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace pitchwing

#endif
