#include <pitchwing/Engine.hpp>

#include <signalsmith-linear/fft.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace pitchwing {
namespace {

constexpr double pi = 3.141592653589793238462643383279502884;
constexpr double twoPi = 2.0 * pi;
constexpr std::size_t maxRegions = 64;
constexpr double relativePeakFloor = 1e-4;
constexpr double flatSpectrumTolerance = 1e-12;
using Complex = std::complex<double>;

bool validPitch(double value) noexcept {
    return std::isfinite(value) && value >= -12.0 && value <= 12.0;
}

EngineConfig validateConfig(const EngineConfig& config) {
    const auto n = config.analysisSize;
    const auto length = config.synthesisSize;
    const auto hop = config.hop;
    // Explicit preparation bound: reject accidental giant FFT allocations and
    // leave ample arithmetic headroom on supported 32/64-bit platforms.
    constexpr auto maxSize = std::size_t{65536};
    if (!std::isfinite(config.sampleRate) || config.sampleRate <= 0.0) {
        throw std::invalid_argument("sampleRate must be finite and positive");
    }
    if (n < 8 || length < 8 || n < length || n % 2 != 0 || length % 2 != 0 ||
        n > maxSize) {
        throw std::invalid_argument("sizes must be even and 65536 >= N >= L >= 8");
    }
    if (hop == 0 || length % hop != 0 || hop > length / 2) {
        throw std::invalid_argument("hop must divide L with at least two overlaps");
    }
    if (config.window != Window::Asymmetric && config.window != Window::Symmetric) {
        throw std::invalid_argument("invalid window selection");
    }
    if (config.window == Window::Symmetric && n != length) {
        throw std::invalid_argument("symmetric mode requires N == L");
    }
    if (!validPitch(config.pitchSemitones)) {
        throw std::invalid_argument("pitchSemitones must be finite in [-12, 12]");
    }
    return config;
}

double principal(double angle) noexcept {
    // Match NumPy's modulo convention, including negative angles.
    auto result = std::fmod(angle + pi, twoPi);
    if (result < 0.0) {
        result += twoPi;
    }
    return result - pi;
}

template <typename Sample>
bool validAddressRange(const Sample* pointer, std::size_t count) noexcept {
    if (pointer == nullptr || count > std::numeric_limits<std::size_t>::max() / sizeof(Sample)) {
        return false;
    }
    const auto begin = reinterpret_cast<std::uintptr_t>(pointer);
    const auto bytes = count * sizeof(Sample);
    return bytes <= std::numeric_limits<std::uintptr_t>::max() - begin;
}

template <typename Sample>
bool validBuffers(const Sample* input, Sample* output, std::size_t count) noexcept {
    if (!validAddressRange(input, count) || !validAddressRange(output, count)) {
        return false;
    }
    if (input == output) {
        return true;
    }
    const auto inputBegin = reinterpret_cast<std::uintptr_t>(input);
    const auto outputBegin = reinterpret_cast<std::uintptr_t>(output);
    const auto bytes = count * sizeof(Sample);
    return inputBegin + bytes <= outputBegin || outputBegin + bytes <= inputBegin;
}

}  // namespace

struct Engine::Impl {
    struct Region {
        std::size_t peak = 0;
        double omega = 0.0;
        double delta = 0.0;
        double rotation = 0.0;
    };

    explicit Impl(const EngineConfig& config)
        : configuration(config), n(config.analysisSize), length(config.synthesisSize),
          hop(config.hop), bins(n / 2 + 1), tail(n + length - 1 + hop),
          ratio(std::pow(2.0, config.pitchSemitones / 12.0)),
          binWidth(twoPi / static_cast<double>(n)), inverseN(1.0 / static_cast<double>(n)),
          fft(n), analysis(n), synthesis(length), history(n), output(length),
          magnitude(bins), binOmega(bins), recent(length), time(n), spectrum(n),
          previousSpectrum(bins), inverseSpectrum(n), inverseTime(n), peaks(bins) {
        const auto pivot = n - length / 2;
        for (std::size_t index = 0; index < n; ++index) {
            const auto position = static_cast<double>(index);
            if (configuration.window == Window::Symmetric) {
                analysis[index] = std::sin(pi * position / static_cast<double>(n));
            } else if (index < pivot) {
                analysis[index] = std::sin(pi * position / (2.0 * static_cast<double>(pivot)));
            } else {
                analysis[index] = std::cos(pi * static_cast<double>(index - pivot) /
                                           (2.0 * static_cast<double>(n - pivot)));
            }
        }
        for (std::size_t q = 0; q < length; ++q) {
            const auto product = (1.0 - std::cos(twoPi * static_cast<double>(q) /
                                               static_cast<double>(length))) /
                                 (static_cast<double>(length) / static_cast<double>(hop));
            const auto denominator = analysis[n - length + q];
            synthesis[q] = denominator != 0.0 ? product / denominator : 0.0;
        }
        for (std::size_t bin = 0; bin < bins; ++bin) {
            // Preserve Python's multiply-then-divide ordering where practical.
            binOmega[bin] = twoPi * static_cast<double>(bin) / static_cast<double>(n);
        }
        reset();
    }

    void reset() noexcept {
        std::fill(history.begin(), history.end(), 0.0);
        std::fill(output.begin(), output.end(), 0.0);
        std::fill(previousSpectrum.begin(), previousSpectrum.end(), Complex{});
        regionCount = 0;
        previousRegionCount = 0;
        historyPosition = 0;
        outputPosition = 0;
        hopPhase = 0;
        previousValid = false;
        started = false;
        closed = false;
    }

    template <typename Sample>
    Status process(const Sample* input, Sample* destination, std::size_t count) noexcept {
        if (closed) {
            return Status::StreamClosed;
        }
        if (count == 0) {
            return Status::Ok;
        }
        if (!validBuffers(input, destination, count)) {
            return Status::InvalidBuffer;
        }
        // Validate all input before writing output or changing any DSP state.
        for (std::size_t index = 0; index < count; ++index) {
            const auto value = static_cast<double>(input[index]);
            if (!std::isfinite(value) || std::abs(value) > 1e100) {
                return Status::InvalidSample;
            }
        }
        started = true;
        for (std::size_t index = 0; index < count; ++index) {
            const auto value = static_cast<double>(input[index]);
            destination[index] = static_cast<Sample>(processSample(value));
        }
        return Status::Ok;
    }

    template <typename Sample>
    Status flush(Sample* destination, std::size_t capacity, std::size_t& written) noexcept {
        written = 0;
        if (closed) {
            return Status::Ok;
        }
        if (capacity < tail) {
            return Status::BufferTooSmall;
        }
        if (!validAddressRange(destination, tail)) {
            return Status::InvalidBuffer;
        }
        for (std::size_t index = 0; index < tail; ++index) {
            destination[index] = static_cast<Sample>(processSample(0.0));
        }
        closed = true;
        written = tail;
        return Status::Ok;
    }

    double processSample(double value) noexcept {
        history[historyPosition] = value;
        if (++historyPosition == n) {
            historyPosition = 0;
        }
        if (hopPhase == 0) {
            frame();
            auto position = outputPosition;
            for (std::size_t q = 0; q < length; ++q) {
                output[position] += recent[q] * synthesis[q];
                if (++position == length) {
                    position = 0;
                }
            }
        }
        const auto result = output[outputPosition];
        output[outputPosition] = 0.0;
        if (++outputPosition == length) {
            outputPosition = 0;
        }
        if (++hopPhase == hop) {
            hopPhase = 0;
        }
        return result;
    }

    void findRegions() noexcept {
        auto largest = 0.0;
        auto smallest = std::numeric_limits<double>::max();
        auto largestBin = std::size_t{1};
        for (std::size_t bin = 0; bin < bins; ++bin) {
            magnitude[bin] = std::abs(spectrum[bin]);
            if (bin > 0 && bin + 1 < bins && magnitude[bin] > largest) {
                largest = magnitude[bin];
                largestBin = bin;
            }
            if (bin > 0 && bin + 1 < bins) {
                smallest = std::min(smallest, magnitude[bin]);
            }
        }
        regionCount = 0;
        if (largest == 0.0) {
            return;
        }
        auto count = std::size_t{0};
        if (largest - smallest <= largest * flatSpectrumTolerance) {
            // A lone effective sample has a flat spectrum. FFT rounding must
            // not invent dozens of peaks and seed persistent phase ancestry.
            peaks[count++] = 1;
        } else {
            for (std::size_t bin = 1; bin + 1 < bins; ++bin) {
                if (magnitude[bin] >= magnitude[bin - 1] && magnitude[bin] > magnitude[bin + 1] &&
                    magnitude[bin] >= largest * relativePeakFloor) {
                    peaks[count++] = bin;
                }
            }
        }
        if (count == 0) {
            peaks[count++] = largestBin;
        }
        if (count > maxRegions) {
            const auto end = peaks.begin() + static_cast<std::ptrdiff_t>(count);
            std::sort(peaks.begin(), end, [this](std::size_t left, std::size_t right) {
                if (magnitude[left] == magnitude[right]) {
                    return left < right;
                }
                return magnitude[left] < magnitude[right];
            });
            std::copy(end - static_cast<std::ptrdiff_t>(maxRegions), end, peaks.begin());
            count = maxRegions;
            std::sort(peaks.begin(), peaks.begin() + static_cast<std::ptrdiff_t>(count));
        }
        for (std::size_t regionIndex = 0; regionIndex < count; ++regionIndex) {
            const auto peak = peaks[regionIndex];
            const auto left = std::log(std::max(magnitude[peak - 1], 1e-300));
            const auto middle = std::log(std::max(magnitude[peak], 1e-300));
            const auto right = std::log(std::max(magnitude[peak + 1], 1e-300));
            const auto denominator = left - 2.0 * middle + right;
            const auto fraction = std::abs(denominator) > 1e-12
                                      ? 0.5 * (left - right) / denominator : 0.0;
            auto estimate = binWidth * (static_cast<double>(peak) +
                                       std::clamp(fraction, -0.5, 0.5));
            if (previousValid && std::abs(previousSpectrum[peak]) > largest * 1e-6) {
                const auto residual = principal(std::arg(spectrum[peak]) -
                                                std::arg(previousSpectrum[peak]) -
                                                binOmega[peak] * static_cast<double>(hop));
                const auto instantaneous = binOmega[peak] + residual / static_cast<double>(hop);
                if (instantaneous > 0.0 && instantaneous < pi &&
                    std::abs(instantaneous - estimate) <= 2.0 * binWidth) {
                    estimate = instantaneous;
                }
            }
            const auto delta = (ratio - 1.0) * estimate;
            auto rotation = 0.0;
            if (previousRegionCount > 0) {
                auto nearest = std::size_t{0};
                auto distance = std::abs(previousRegions[0].omega - estimate);
                for (std::size_t old = 1; old < previousRegionCount; ++old) {
                    const auto nextDistance = std::abs(previousRegions[old].omega - estimate);
                    if (nextDistance < distance) {
                        nearest = old;
                        distance = nextDistance;
                    }
                }
                const auto& ancestor = previousRegions[nearest];
                rotation = principal(ancestor.rotation + 0.5 * static_cast<double>(hop) *
                                                            (ancestor.delta + delta));
            }
            regions[regionIndex] = Region{peak, estimate, delta, rotation};
        }
        regionCount = count;
    }

    void frame() noexcept {
        auto source = historyPosition;
        for (std::size_t index = 0; index < n; ++index) {
            time[index] = Complex{history[source] * analysis[index], 0.0};
            if (++source == n) {
                source = 0;
            }
        }
        fft.fft(time.data(), spectrum.data());
        spectrum[0].imag(0.0);
        spectrum[n / 2].imag(0.0);
        findRegions();
        if (ratio == 1.0) {
            // Match NumPy irfft's reconstruction from the positive half.
            inverseSpectrum[0] = spectrum[0];
            inverseSpectrum[n / 2] = spectrum[n / 2];
            for (std::size_t bin = 1; bin < n / 2; ++bin) {
                inverseSpectrum[bin] = spectrum[bin];
                inverseSpectrum[n - bin] = std::conj(spectrum[bin]);
            }
            fft.ifft(inverseSpectrum.data(), inverseTime.data());
            for (std::size_t q = 0; q < length; ++q) {
                recent[q] = inverseTime[n - length + q].real() * inverseN;
            }
        } else {
            transport();
        }
        std::copy_n(spectrum.begin(), bins, previousSpectrum.begin());
        std::copy_n(regions.begin(), regionCount, previousRegions.begin());
        previousRegionCount = regionCount;
        previousValid = true;
    }

    void transport() noexcept {
        // Retain DFT bin zero, not a promise of constant-waveform preservation.
        // Nonunity omits the Nyquist bin, faithfully retaining reference flaws.
        std::fill(recent.begin(), recent.end(), spectrum[0].real() * inverseN);
        const auto guard = 2.0 * binWidth;
        for (std::size_t index = 0; index < regionCount; ++index) {
            const auto& region = regions[index];
            const auto begin = index == 0 ? 1 : (regions[index - 1].peak + region.peak) / 2 + 1;
            const auto end = index + 1 == regionCount
                                 ? n / 2 : (region.peak + regions[index + 1].peak) / 2 + 1;
            std::fill(inverseSpectrum.begin(), inverseSpectrum.end(), Complex{});
            for (auto bin = begin; bin < end; ++bin) {
                const auto destination = binOmega[bin] + region.delta;
                auto taper = 0.0;
                if (destination > 0.0 && destination < pi) {
                    if (destination <= pi - guard) {
                        taper = 1.0;
                    } else {
                        const auto high = (pi - destination) / guard;
                        taper = 0.5 - 0.5 * std::cos(pi * high);
                    }
                }
                inverseSpectrum[bin] = 2.0 * spectrum[bin] * taper;
            }
            fft.ifft(inverseSpectrum.data(), inverseTime.data());
            const auto step = Complex{std::cos(region.delta), std::sin(region.delta)};
            auto modulation = Complex{};
            for (std::size_t q = 0; q < length; ++q) {
                // Re-anchor at least every 64 samples so recurrence roundoff
                // cannot accumulate across a frame or into persistent state.
                if (q % 64 == 0) {
                    const auto offset = static_cast<double>(q) - static_cast<double>(length - 1);
                    const auto angle = region.rotation + region.delta * offset;
                    modulation = Complex{std::cos(angle), std::sin(angle)};
                }
                recent[q] += (inverseTime[n - length + q] * modulation).real() * inverseN;
                modulation *= step;
            }
        }
    }

    EngineConfig configuration;
    const std::size_t n;
    const std::size_t length;
    const std::size_t hop;
    const std::size_t bins;
    const std::size_t tail;
    double ratio;
    const double binWidth;
    const double inverseN;
    signalsmith::linear::SplitFFT<double> fft;
    std::vector<double> analysis;
    std::vector<double> synthesis;
    std::vector<double> history;
    std::vector<double> output;
    std::vector<double> magnitude;
    std::vector<double> binOmega;
    std::vector<double> recent;
    std::vector<Complex> time;
    std::vector<Complex> spectrum;
    std::vector<Complex> previousSpectrum;
    std::vector<Complex> inverseSpectrum;
    std::vector<Complex> inverseTime;
    std::vector<std::size_t> peaks;
    std::array<Region, maxRegions> regions{};
    std::array<Region, maxRegions> previousRegions{};
    std::size_t regionCount = 0;
    std::size_t previousRegionCount = 0;
    std::size_t historyPosition = 0;
    std::size_t outputPosition = 0;
    std::size_t hopPhase = 0;
    bool previousValid = false;
    bool started = false;
    bool closed = false;
};

Engine::Engine(const EngineConfig& config)
    : impl_(std::make_unique<Impl>(validateConfig(config))) {}

Engine::~Engine() = default;
Engine::Engine(Engine&& other) noexcept = default;
Engine& Engine::operator=(Engine&& other) noexcept = default;

Status Engine::process(const double* input, double* output, std::size_t count) noexcept {
    return impl_ ? impl_->process(input, output, count) : Status::NotPrepared;
}

Status Engine::process(const float* input, float* output, std::size_t count) noexcept {
    return impl_ ? impl_->process(input, output, count) : Status::NotPrepared;
}

Status Engine::flush(double* output, std::size_t capacity, std::size_t& written) noexcept {
    written = 0;
    return impl_ ? impl_->flush(output, capacity, written) : Status::NotPrepared;
}

Status Engine::flush(float* output, std::size_t capacity, std::size_t& written) noexcept {
    written = 0;
    return impl_ ? impl_->flush(output, capacity, written) : Status::NotPrepared;
}

Status Engine::reset() noexcept {
    if (!impl_) {
        return Status::NotPrepared;
    }
    impl_->reset();
    return Status::Ok;
}

Status Engine::setPitchSemitones(double value) noexcept {
    if (!impl_) {
        return Status::NotPrepared;
    }
    if (!validPitch(value)) {
        return Status::InvalidPitch;
    }
    if (value == impl_->configuration.pitchSemitones) {
        return Status::Ok;
    }
    if (impl_->started || impl_->closed) {
        return Status::PitchLocked;
    }
    impl_->configuration.pitchSemitones = value;
    impl_->ratio = std::pow(2.0, value / 12.0);
    return Status::Ok;
}

std::size_t Engine::latencySamples() const noexcept {
    return impl_ ? impl_->length - 1 : 0;
}

std::size_t Engine::tailSamples() const noexcept {
    return impl_ ? impl_->tail : 0;
}

EngineConfig Engine::config() const noexcept {
    return impl_ ? impl_->configuration : EngineConfig{};
}

}  // namespace pitchwing
