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
constexpr std::size_t lobeRange = 24;      // bins; |A| is below -59 dB beyond
constexpr std::size_t lobeOversample = 64;
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
          settleFloorOmega(twoPi * 100.0 / config.sampleRate),
          fft(n), analysis(n), synthesis(length), transportSynthesis(length), dcWindow(length), controlHistory(length),
          frameControl(length), negativeSuffix(length), magnitude(bins),
          binOmega(bins), peaks(bins), time(n), inverseSpectrum(n), inverseTime(n),
          modulation(length), taper(n / 2), lobe(2 * lobeRange * lobeOversample + 1) {
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            history[channel].resize(n);
            output[channel].resize(ringSize);
            spectrum[channel].resize(n);
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
            dcWindow[q] = product;  // analysis * synthesis: exact partition of unity
        }
        for (std::size_t index = 0; index < n; ++index) {
            analysisSum += analysis[index];
        }
        for (std::size_t bin = 0; bin < bins; ++bin) {
            binOmega[bin] = twoPi * static_cast<double>(bin) / static_cast<double>(n);
        }
        // Window spectrum A(theta) = sum_n analysis[n] e^{-j theta n}, tabulated at
        // 1/lobeOversample bin over +-lobeRange bins for the region frequency fit.
        for (std::size_t entry = 0; entry < lobe.size(); ++entry) {
            const auto theta = (static_cast<double>(entry) / static_cast<double>(lobeOversample) -
                                static_cast<double>(lobeRange)) * binWidth;
            const auto step = Complex{std::cos(theta), -std::sin(theta)};
            auto phasor = Complex{1.0, 0.0};
            auto sum = Complex{};
            for (std::size_t index = 0; index < n; ++index) {
                sum += analysis[index] * phasor;
                phasor *= step;
            }
            lobe[entry] = sum;
        }
        reset();
    }

    Complex lobeAt(double offsetBins) const noexcept {
        const auto range = static_cast<double>(lobeRange);
        if (offsetBins <= -range || offsetBins >= range) {
            return Complex{};
        }
        const auto position = (offsetBins + range) * static_cast<double>(lobeOversample);
        const auto lower = static_cast<std::size_t>(position);
        const auto fraction = position - static_cast<double>(lower);
        return lobe[lower] * (1.0 - fraction) + lobe[lower + 1] * fraction;
    }

    // Least-squares residual of X[k] = a A(w_k - w) + conj(a) A(w_k + w) over the
    // three peak bins, summed over channels (a per channel). The image term is
    // what the parabola and phase-difference estimates lacked: without it the
    // estimate wobbled 150-680 cents frame to frame below bin 4
    // (docs/results/2026-10-10-estimator-probe.txt).
    double lobeFitCost(std::size_t peak, double centreBins,
                       std::array<Complex, 2>* amplitude = nullptr) const noexcept {
        std::array<double, 3> a0{}, a1{}, b0{}, b1{};
        for (std::size_t i = 0; i < 3; ++i) {
            const auto k = static_cast<double>(peak + i) - 1.0;
            const auto p = lobeAt(k - centreBins);
            const auto m = lobeAt(k + centreBins);
            a0[i] = p.real() + m.real();
            a1[i] = m.imag() - p.imag();
            b0[i] = p.imag() + m.imag();
            b1[i] = p.real() - m.real();
        }
        auto cost = 0.0;
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            double g00 = 0.0, g01 = 0.0, g11 = 0.0, h0 = 0.0, h1 = 0.0, energy = 0.0;
            for (std::size_t i = 0; i < 3; ++i) {
                const auto& x = spectrum[channel][peak + i - 1];
                g00 += a0[i] * a0[i] + b0[i] * b0[i];
                g01 += a0[i] * a1[i] + b0[i] * b1[i];
                g11 += a1[i] * a1[i] + b1[i] * b1[i];
                h0 += a0[i] * x.real() + b0[i] * x.imag();
                h1 += a1[i] * x.real() + b1[i] * x.imag();
                energy += std::norm(x);
            }
            const auto determinant = g00 * g11 - g01 * g01;
            if (g00 <= 0.0) {
                cost += energy;
                continue;
            }
            // At w = 0 the image coincides with the lobe and only Re(a) is
            // determined (a DC lobe); fall back to that one-parameter fit.
            auto re = (g11 * h0 - g01 * h1) / determinant;
            auto im = (g00 * h1 - g01 * h0) / determinant;
            // Near w = 0 the two basis vectors are almost parallel and the
            // solution cancels two huge terms; an amplitude far above the data
            // is that ill-conditioning, not signal.
            if (determinant <= 1e-12 * g00 * g00 ||
                std::hypot(re, im) * analysisSum > 4.0 * std::sqrt(3.0 * energy)) {
                re = h0 / g00;
                im = 0.0;
            }
            cost += std::max(0.0, energy - (re * h0 + im * h1));
            if (amplitude != nullptr) {
                (*amplitude)[channel] = Complex{re, im};
            }
        }
        return cost;
    }

    double fitOmega(std::size_t peak) noexcept {
        // The range reaches 0 so a DC lobe fits as an untranslated w = 0 tone.
        auto low = peak <= 1 ? 0.0 : static_cast<double>(peak) - 0.6;
        auto high = static_cast<double>(peak) + 0.6;
        for (int round = 0; round < 5; ++round) {
            const auto step = (high - low) / 12.0;
            auto best = std::numeric_limits<double>::max();
            auto centre = low;
            for (int i = 0; i <= 12; ++i) {
                const auto candidate = low + step * i;
                const auto cost = lobeFitCost(peak, candidate);
                if (cost < best) {
                    best = cost;
                    centre = candidate;
                }
            }
            low = centre - step;
            high = centre + step;
        }
        const auto centre = std::clamp(0.5 * (low + high), 0.0, 0.5 * static_cast<double>(n) - 0.5);
        if (peak == peaks[0]) {
            // Lowest region: split bin 0 into the fitted tone's share (translated
            // with the region) and the true DC residual (rendered untranslated).
            lobeFitCost(peak, centre, &lowestAmplitude);
            lowestImage = lobeAt(centre);
            lowestPositive = lobeAt(-centre);
        }
        return centre * binWidth;
    }

    void reset() noexcept {
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::fill(history[channel].begin(), history[channel].end(), 0.0);
            std::fill(output[channel].begin(), output[channel].end(), 0.0);
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
        settling = false;
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
        settling = false;
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
            const auto omega = fitOmega(peak);
            auto rotation = 0.0;
            if (previousRegionCount > 0) {
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
                const auto advance = 0.5 * (ancestor.omega + omega) * hopArea;
                rotation = principal(ancestor.rotation + advance);
                if (std::abs(advance) < 1e-3) {
                    // Zero translation (unity frames, a DC lobe at omega ~ 0): an
                    // inherited rotation is then an audible constant phase or sign
                    // error, and resetting it would mix rotated and unrotated copies
                    // in the overlap ring (measured dips to -15 dB). Slew it out
                    // instead: at most a 10-cent glide, with a 100 Hz floor so
                    // sub-bass regions settle within ~1 s.
                    const auto slew = std::max(omega, settleFloorOmega) * static_cast<double>(hop) * 0.006;
                    rotation -= std::clamp(rotation, -slew, slew);
                    settling = settling || (unitySupport && rotation != 0.0);
                }
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
        }
        findRegions();
        // Exact delayed unity only once every inherited rotation has settled to
        // zero; until then unity frames render regions with delta 0 like any other.
        const auto exactUnity = unitySupport && !settling;
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            auto destination = frameOutputStart;
            auto dc = spectrum[channel][0].real();
            if (regionCount > 0) {
                const auto& a = lowestAmplitude[channel];
                dc -= (a * lowestPositive + std::conj(a) * lowestImage).real();
            }
            dc /= analysisSum;
            auto source = historyPosition + n - length;
            if (source >= n) {
                source -= n;
            }
            for (std::size_t q = 0; q < length; ++q) {
                output[channel][destination] += exactUnity
                    ? history[channel][source] * analysis[n - length + q] * synthesis[q]
                    : dc * dcWindow[q];
                if (++destination == ringSize) {
                    destination = 0;
                }
                if (++source == n) {
                    source = 0;
                }
            }
        }
        std::copy_n(regions.begin(), regionCount, previousRegions.begin());
        previousRegionCount = regionCount;
        if (exactUnity) {
            // No region inverse transforms are needed for exact delayed unity.
            regionCount = 0;
        }
    }

    void renderRegion(std::size_t index) noexcept {
        const auto& region = regions[index];
        const auto begin = index == 0 ? 0 : (regions[index - 1].peak + region.peak) / 2 + 1;
        const auto end = index + 1 == regionCount ? n / 2 : (region.peak + regions[index + 1].peak) / 2 + 1;
        const auto delta = region.omega * frameRatioMinusOne;
        const auto guard = 2.0 * binWidth;
        for (auto bin = begin; bin < end; ++bin) {
            const auto destination = binOmega[bin] + delta;
            // Destinations below zero fold to |destination| through the real
            // part: the conjugate reflection of a real signal's lobe, not a loss.
            auto value = 0.0;
            if (destination < pi) {
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
            if (begin == 0) {
                inverseSpectrum[0] = 2.0 * lowestAmplitude[channel] * lowestPositive * taper[0];
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
    const double settleFloorOmega;
    Transform fft;
    std::vector<double> analysis;
    std::vector<double> synthesis;
    std::vector<double> transportSynthesis;
    std::vector<double> dcWindow;
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
    std::vector<Complex> inverseSpectrum;
    std::vector<Complex> inverseTime;
    std::vector<Complex> modulation;
    std::vector<double> taper;
    std::vector<Complex> lobe;
    double analysisSum = 0.0;
    std::array<Complex, 2> lowestAmplitude{};
    Complex lowestPositive{};
    Complex lowestImage{};
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
    bool settling = false;
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
