#include <pitchwing/LiveEngine.hpp>

#include <signalsmith-linear/fft.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace pitchwing {
namespace {

constexpr double pi = 3.141592653589793238462643383279502884;
constexpr double twoPi = 2.0 * pi;
constexpr std::size_t maxRegions = 64;
using Complex = std::complex<double>;
using Transform = signalsmith::linear::SplitFFT<double>;

bool validPitch(double value) noexcept {
    return std::isfinite(value) && value >= -49.0 && value <= 49.0;
}

LiveConfig validateConfig(const LiveConfig& config) {
    if (!std::isfinite(config.sampleRate) || config.sampleRate < 8000.0 ||
        config.sampleRate > 192000.0) {
        throw std::invalid_argument("sampleRate must be finite in [8000, 192000]");
    }
    if (!validPitch(config.pitchSemitones)) {
        throw std::invalid_argument("pitchSemitones must be finite in [-49, 49]");
    }
    return config;
}

double principal(double angle) noexcept {
    auto result = std::fmod(angle + pi, twoPi);
    if (result < 0.0) {
        result += twoPi;
    }
    return result - pi;
}

template <typename Sample>
bool validRange(const Sample* pointer, std::size_t count) noexcept {
    if (pointer == nullptr || count > std::numeric_limits<std::size_t>::max() / sizeof(Sample)) {
        return false;
    }
    const auto address = reinterpret_cast<std::uintptr_t>(pointer);
    return count * sizeof(Sample) <= std::numeric_limits<std::uintptr_t>::max() - address;
}

template <typename Sample>
bool disjoint(const Sample* left, const Sample* right, std::size_t count) noexcept {
    const auto a = reinterpret_cast<std::uintptr_t>(left);
    const auto b = reinterpret_cast<std::uintptr_t>(right);
    const auto bytes = count * sizeof(Sample);
    return a + bytes <= b || b + bytes <= a;
}

template <typename Sample>
bool compatible(const Sample* input, const Sample* output, std::size_t count) noexcept {
    return input == output || disjoint(input, output, count);
}

template <typename Sample>
bool validBuffers(const Sample* left, const Sample* right, Sample* outLeft,
                  Sample* outRight, std::size_t count) noexcept {
    if (!validRange(left, count) || !validRange(right, count) ||
        !validRange(outLeft, count) || !validRange(outRight, count)) {
        return false;
    }
    return compatible(left, right, count) && disjoint(outLeft, outRight, count) &&
           compatible(left, outLeft, count) && compatible(left, outRight, count) &&
           compatible(right, outLeft, count) && compatible(right, outRight, count);
}

}  // namespace

struct LiveEngine::Impl {
    struct Region {
        std::size_t peak = 0;
        double omega = 0.0;
        double rotation = 0.0;
    };

    explicit Impl(const LiveConfig& config)
        : configuration(config),
          hop(static_cast<std::size_t>(std::floor(config.sampleRate * 0.002))),
          length(4 * hop),
          n(Transform::fastSizeAbove(static_cast<std::size_t>(
              std::ceil(config.sampleRate * (2048.0 / 48000.0))))),
          bins(n / 2 + 1), ringSize(length + hop), delay(length - 1 + hop),
          tail(n + delay + hop), ratioMinusOne(std::exp2(config.pitchSemitones / 12.0) - 1.0),
          binWidth(twoPi / static_cast<double>(n)), inverseN(1.0 / static_cast<double>(n)),
          fft(n), analysis(n), synthesis(length), transportSynthesis(length), controlHistory(length),
          frameControl(length), negativeSuffix(length), magnitude(bins),
          binOmega(bins), peaks(bins), time(n), inverseSpectrum(n), inverseTime(n),
          modulation(length), taper(n / 2) {
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            history[channel].resize(n);
            output[channel].resize(ringSize);
            spectrum[channel].resize(n);
            previousSpectrum[channel].resize(bins);
        }
        const auto pivot = n - length / 2;
        for (std::size_t index = 0; index < n; ++index) {
            if (index < pivot) {
                analysis[index] = std::sin(pi * static_cast<double>(index) /
                                           (2.0 * static_cast<double>(pivot)));
            } else {
                analysis[index] = std::cos(pi * static_cast<double>(index - pivot) /
                                           (2.0 * static_cast<double>(n - pivot)));
            }
        }
        for (std::size_t q = 0; q < length; ++q) {
            const auto product = (1.0 - std::cos(twoPi * static_cast<double>(q) /
                                               static_cast<double>(length))) / 4.0;
            synthesis[q] = product / analysis[n - length + q];
            transportSynthesis[q] = synthesis[q] * inverseN;
        }
        for (std::size_t bin = 0; bin < bins; ++bin) {
            binOmega[bin] = twoPi * static_cast<double>(bin) / static_cast<double>(n);
        }
        reset();
    }

    void reset() noexcept {
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::fill(history[channel].begin(), history[channel].end(), 0.0);
            std::fill(output[channel].begin(), output[channel].end(), 0.0);
            std::fill(previousSpectrum[channel].begin(), previousSpectrum[channel].end(), Complex{});
        }
        std::fill(controlHistory.begin(), controlHistory.end(), 0.0);
        historyPosition = 0;
        controlPosition = 0;
        outputPosition = 0;
        frameOutputStart = 0;
        hopPhase = 0;
        regionCount = 0;
        previousRegionCount = 0;
        completedRegions = 0;
        hopArea = 0.0;
        previousValid = false;
        closed = false;
    }

    template <typename Sample>
    Status process(const Sample* left, const Sample* right, Sample* outLeft,
                   Sample* outRight, std::size_t frames) noexcept {
        if (closed) {
            return Status::StreamClosed;
        }
        if (frames == 0) {
            return Status::Ok;
        }
        if (!validBuffers(left, right, outLeft, outRight, frames)) {
            return Status::InvalidBuffer;
        }
        // A shared bound keeps queued double-path output representable when a
        // later call uses float buffers, including mixed-precision flushing.
        constexpr auto sampleLimit = 1e30;
        for (std::size_t index = 0; index < frames; ++index) {
            const auto l = static_cast<double>(left[index]);
            const auto r = static_cast<double>(right[index]);
            if (!std::isfinite(l) || !std::isfinite(r) ||
                std::abs(l) > sampleLimit || std::abs(r) > sampleLimit) {
                return Status::InvalidSample;
            }
        }
        for (std::size_t index = 0; index < frames; ++index) {
            // Read both before writing either: exact/cross-channel in-place and
            // duplicated mono inputs must not overwrite the second read.
            const auto l = static_cast<double>(left[index]);
            const auto r = static_cast<double>(right[index]);
            const auto result = processSample(l, r);
            outLeft[index] = static_cast<Sample>(result[0]);
            outRight[index] = static_cast<Sample>(result[1]);
        }
        return Status::Ok;
    }

    template <typename Sample>
    Status flush(Sample* outLeft, Sample* outRight, std::size_t capacity,
                 std::size_t& written) noexcept {
        written = 0;
        if (closed) {
            return Status::Ok;
        }
        if (capacity < tail) {
            return Status::BufferTooSmall;
        }
        if (!validRange(outLeft, tail) || !validRange(outRight, tail) ||
            !disjoint(outLeft, outRight, tail)) {
            return Status::InvalidBuffer;
        }
        for (std::size_t index = 0; index < tail; ++index) {
            const auto result = processSample(0.0, 0.0);
            outLeft[index] = static_cast<Sample>(result[0]);
            outRight[index] = static_cast<Sample>(result[1]);
        }
        closed = true;
        written = tail;
        return Status::Ok;
    }

    std::array<double, 2> processSample(double left, double right) noexcept {
        history[0][historyPosition] = left;
        history[1][historyPosition] = right;
        if (++historyPosition == n) {
            historyPosition = 0;
        }
        controlHistory[controlPosition] = ratioMinusOne;
        if (++controlPosition == length) {
            controlPosition = 0;
        }
        hopArea += ratioMinusOne;
        if (hopPhase == 0) {
            prepareFrame();
            hopArea = 0.0;
        }
        const auto due = (hopPhase + 1) * regionCount / hop;
        while (completedRegions < due) {
            renderRegion(completedRegions++);
        }
        const auto result = std::array<double, 2>{output[0][outputPosition], output[1][outputPosition]};
        output[0][outputPosition] = 0.0;
        output[1][outputPosition] = 0.0;
        if (++outputPosition == ringSize) {
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
            magnitude[bin] = std::hypot(std::abs(spectrum[0][bin]), std::abs(spectrum[1][bin]));
            if (bin > 0 && bin + 1 < bins) {
                if (magnitude[bin] > largest) {
                    largest = magnitude[bin];
                    largestBin = bin;
                }
                smallest = std::min(smallest, magnitude[bin]);
            }
        }
        regionCount = 0;
        if (largest == 0.0) {
            return;
        }
        auto count = std::size_t{0};
        if (largest - smallest <= largest * 1e-12) {
            peaks[count++] = 1;
        } else {
            for (std::size_t bin = 1; bin + 1 < bins; ++bin) {
                if (magnitude[bin] >= magnitude[bin - 1] && magnitude[bin] > magnitude[bin + 1] &&
                    magnitude[bin] >= largest * 1e-4) {
                    peaks[count++] = bin;
                }
            }
        }
        if (count == 0) {
            peaks[count++] = largestBin;
        }
        if (count > maxRegions) {
            const auto end = peaks.begin() + static_cast<std::ptrdiff_t>(count);
            std::sort(peaks.begin(), end, [this](std::size_t a, std::size_t b) {
                return magnitude[a] == magnitude[b] ? a < b : magnitude[a] < magnitude[b];
            });
            std::copy(end - static_cast<std::ptrdiff_t>(maxRegions), end, peaks.begin());
            count = maxRegions;
            std::sort(peaks.begin(), peaks.begin() + static_cast<std::ptrdiff_t>(count));
        }
        for (std::size_t index = 0; index < count; ++index) {
            const auto peak = peaks[index];
            const auto a = std::log(std::max(magnitude[peak - 1], 1e-300));
            const auto b = std::log(std::max(magnitude[peak], 1e-300));
            const auto c = std::log(std::max(magnitude[peak + 1], 1e-300));
            const auto denominator = a - 2.0 * b + c;
            const auto fraction = std::abs(denominator) > 1e-12 ? 0.5 * (a - c) / denominator : 0.0;
            auto omega = binWidth * (static_cast<double>(peak) + std::clamp(fraction, -0.5, 0.5));
            const auto oldMagnitude = std::hypot(std::abs(previousSpectrum[0][peak]),
                                                 std::abs(previousSpectrum[1][peak]));
            if (previousValid && oldMagnitude > largest * 1e-6) {
                // Joint temporal products add energy, including anti-phase
                // stereo, instead of cancelling channels before analysis.
                const auto crossLeft = spectrum[0][peak] * std::conj(previousSpectrum[0][peak]);
                const auto crossRight = spectrum[1][peak] * std::conj(previousSpectrum[1][peak]);
                const auto cross = crossLeft + crossRight;
                const auto crossScale = std::abs(crossLeft) + std::abs(crossRight);
                // Opposing temporal rotations in unrelated channels can nearly
                // cancel their joint phase. Prefer the spectral estimate then.
                if (std::abs(cross) > crossScale * 1e-6) {
                    const auto residual = principal(std::arg(cross) - binOmega[peak] * static_cast<double>(hop));
                    const auto instantaneous = binOmega[peak] + residual / static_cast<double>(hop);
                    if (instantaneous > 0.0 && instantaneous < pi &&
                        std::abs(instantaneous - omega) <= 2.0 * binWidth) {
                        omega = instantaneous;
                    }
                }
            }
            auto rotation = 0.0;
            if (previousRegionCount > 0 && !unitySupport) {
                auto nearest = std::size_t{0};
                auto distance = std::abs(previousRegions[0].omega - omega);
                for (std::size_t old = 1; old < previousRegionCount; ++old) {
                    const auto candidate = std::abs(previousRegions[old].omega - omega);
                    if (candidate < distance) {
                        nearest = old;
                        distance = candidate;
                    }
                }
                const auto& ancestor = previousRegions[nearest];
                rotation = principal(ancestor.rotation + 0.5 * (ancestor.omega + omega) * hopArea);
            }
            regions[index] = Region{peak, omega, rotation};
        }
        regionCount = count;
    }

    void prepareFrame() noexcept {
        frameOutputStart = outputPosition + hop;
        if (frameOutputStart >= ringSize) {
            frameOutputStart -= ringSize;
        }
        completedRegions = 0;
        unitySupport = true;
        auto controlSource = controlPosition;
        for (std::size_t q = 0; q < length; ++q) {
            frameControl[q] = controlHistory[controlSource];
            unitySupport = unitySupport && frameControl[q] == 0.0;
            if (++controlSource == length) {
                controlSource = 0;
            }
        }
        auto suffix = 0.0;
        for (auto q = length; q-- > 0;) {
            negativeSuffix[q] = suffix;
            suffix -= frameControl[q];
        }
        frameRatioMinusOne = frameControl[length - 1];
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            auto source = historyPosition;
            for (std::size_t index = 0; index < n; ++index) {
                time[index] = Complex{history[channel][source] * analysis[index], 0.0};
                if (++source == n) {
                    source = 0;
                }
            }
            fft.fft(time.data(), spectrum[channel].data());
            spectrum[channel][0].imag(0.0);
            spectrum[channel][n / 2].imag(0.0);
            auto destination = frameOutputStart;
            const auto dc = spectrum[channel][0].real() * inverseN;
            for (std::size_t q = 0; q < length; ++q) {
                const auto value = unitySupport ? time[n - length + q].real() : dc;
                output[channel][destination] += value * synthesis[q];
                if (++destination == ringSize) {
                    destination = 0;
                }
            }
        }
        findRegions();
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::copy_n(spectrum[channel].begin(), bins, previousSpectrum[channel].begin());
        }
        std::copy_n(regions.begin(), regionCount, previousRegions.begin());
        previousRegionCount = regionCount;
        previousValid = true;
        if (unitySupport) {
            // No region inverse transforms are needed for exact delayed unity.
            regionCount = 0;
        }
    }

    void renderRegion(std::size_t index) noexcept {
        const auto& region = regions[index];
        const auto begin = index == 0 ? 1 : (regions[index - 1].peak + region.peak) / 2 + 1;
        const auto end = index + 1 == regionCount ? n / 2 : (region.peak + regions[index + 1].peak) / 2 + 1;
        const auto delta = region.omega * frameRatioMinusOne;
        const auto guard = 2.0 * binWidth;
        for (auto bin = begin; bin < end; ++bin) {
            const auto destination = binOmega[bin] + delta;
            auto value = 0.0;
            if (destination > 0.0 && destination < pi) {
                value = destination <= pi - guard ? 1.0 :
                    0.5 - 0.5 * std::cos(pi * (pi - destination) / guard);
            }
            taper[bin] = value;
        }
        auto previousControl = std::numeric_limits<double>::quiet_NaN();
        auto step = Complex{};
        auto current = Complex{};
        for (std::size_t q = 0; q < length; ++q) {
            if (q % 64 == 0) {
                const auto angle = region.rotation + region.omega * negativeSuffix[q];
                current = Complex{std::cos(angle), std::sin(angle)};
            } else {
                // q-1 -> q integrates the command belonging to source sample q.
                if (frameControl[q] != previousControl) {
                    const auto angle = region.omega * frameControl[q];
                    step = Complex{std::cos(angle), std::sin(angle)};
                    previousControl = frameControl[q];
                }
                current *= step;
            }
            // Cache the weighted modulator once for both channel transforms.
            modulation[q] = current * transportSynthesis[q];
        }
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::fill(inverseSpectrum.begin(), inverseSpectrum.end(), Complex{});
            for (auto bin = begin; bin < end; ++bin) {
                inverseSpectrum[bin] = 2.0 * spectrum[channel][bin] * taper[bin];
            }
            fft.ifft(inverseSpectrum.data(), inverseTime.data());
            auto destination = frameOutputStart;
            for (std::size_t q = 0; q < length; ++q) {
                const auto& value = inverseTime[n - length + q];
                const auto& weight = modulation[q];
                output[channel][destination] += value.real() * weight.real() -
                                                value.imag() * weight.imag();
                if (++destination == ringSize) {
                    destination = 0;
                }
            }
        }
    }

    LiveConfig configuration;
    const std::size_t hop;
    const std::size_t length;
    const std::size_t n;
    const std::size_t bins;
    const std::size_t ringSize;
    const std::size_t delay;
    const std::size_t tail;
    double ratioMinusOne;
    const double binWidth;
    const double inverseN;
    Transform fft;
    std::vector<double> analysis;
    std::vector<double> synthesis;
    std::vector<double> transportSynthesis;
    std::array<std::vector<double>, 2> history;
    std::array<std::vector<double>, 2> output;
    std::vector<double> controlHistory;
    std::vector<double> frameControl;
    std::vector<double> negativeSuffix;
    std::vector<double> magnitude;
    std::vector<double> binOmega;
    std::vector<std::size_t> peaks;
    std::vector<Complex> time;
    std::array<std::vector<Complex>, 2> spectrum;
    std::array<std::vector<Complex>, 2> previousSpectrum;
    std::vector<Complex> inverseSpectrum;
    std::vector<Complex> inverseTime;
    std::vector<Complex> modulation;
    std::vector<double> taper;
    std::array<Region, maxRegions> regions{};
    std::array<Region, maxRegions> previousRegions{};
    std::size_t historyPosition = 0;
    std::size_t controlPosition = 0;
    std::size_t outputPosition = 0;
    std::size_t frameOutputStart = 0;
    std::size_t hopPhase = 0;
    std::size_t regionCount = 0;
    std::size_t previousRegionCount = 0;
    std::size_t completedRegions = 0;
    double hopArea = 0.0;
    double frameRatioMinusOne = 0.0;
    bool unitySupport = true;
    bool previousValid = false;
    bool closed = false;
};

LiveEngine::LiveEngine(const LiveConfig& config)
    : impl_(std::make_unique<Impl>(validateConfig(config))) {}
LiveEngine::~LiveEngine() = default;
LiveEngine::LiveEngine(LiveEngine&& other) noexcept = default;
LiveEngine& LiveEngine::operator=(LiveEngine&& other) noexcept = default;

Status LiveEngine::process(const float* left, const float* right, float* outLeft,
                           float* outRight, std::size_t frames) noexcept {
    return impl_ ? impl_->process(left, right, outLeft, outRight, frames) : Status::NotPrepared;
}
Status LiveEngine::process(const double* left, const double* right, double* outLeft,
                           double* outRight, std::size_t frames) noexcept {
    return impl_ ? impl_->process(left, right, outLeft, outRight, frames) : Status::NotPrepared;
}
Status LiveEngine::flush(float* outLeft, float* outRight, std::size_t capacity,
                         std::size_t& written) noexcept {
    written = 0;
    return impl_ ? impl_->flush(outLeft, outRight, capacity, written) : Status::NotPrepared;
}
Status LiveEngine::flush(double* outLeft, double* outRight, std::size_t capacity,
                         std::size_t& written) noexcept {
    written = 0;
    return impl_ ? impl_->flush(outLeft, outRight, capacity, written) : Status::NotPrepared;
}
Status LiveEngine::reset() noexcept {
    if (!impl_) {
        return Status::NotPrepared;
    }
    impl_->reset();
    return Status::Ok;
}
Status LiveEngine::setPitchSemitones(double value) noexcept {
    if (!impl_) {
        return Status::NotPrepared;
    }
    if (!validPitch(value)) {
        return Status::InvalidPitch;
    }
    if (value == impl_->configuration.pitchSemitones) {
        return Status::Ok;
    }
    if (impl_->closed) {
        return Status::StreamClosed;
    }
    impl_->configuration.pitchSemitones = value;
    impl_->ratioMinusOne = std::exp2(value / 12.0) - 1.0;
    return Status::Ok;
}
std::size_t LiveEngine::latencySamples() const noexcept { return impl_ ? impl_->delay : 0; }
std::size_t LiveEngine::tailSamples() const noexcept { return impl_ ? impl_->tail : 0; }
std::size_t LiveEngine::analysisSize() const noexcept { return impl_ ? impl_->n : 0; }
std::size_t LiveEngine::synthesisSize() const noexcept { return impl_ ? impl_->length : 0; }
std::size_t LiveEngine::hopSamples() const noexcept { return impl_ ? impl_->hop : 0; }
LiveConfig LiveEngine::config() const noexcept { return impl_ ? impl_->configuration : LiveConfig{}; }

}  // namespace pitchwing
