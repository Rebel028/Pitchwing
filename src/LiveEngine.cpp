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
constexpr std::size_t lobeRange = 48;      // bins; |A| is below -65 dB beyond
constexpr std::size_t lobeOversample = 64;
constexpr std::size_t longFactor = 4;      // long analysis = 4 n; supplies omega only
constexpr double longLimitHz = 700.0;      // long peaks are searched below this
constexpr std::size_t maxSplit = 4;        // components per split region
constexpr std::size_t maxEntries = maxRegions + 16;
constexpr double minSplitBins = 0.35;      // short-bin spacing below which a split is ill-conditioned
constexpr std::size_t lobeSpan = 24;       // bins each side a fitted lobe is transported with its partial
constexpr double lobeQuality = 0.02;       // max residual/energy of a 3-bin fit that earns a lobe
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

// sum_{m < count} e^{j phi m}
Complex geometric(double phi, std::size_t count) noexcept {
    const auto half = std::sin(0.5 * phi);
    const auto c = static_cast<double>(count);
    if (std::abs(half) < 1e-12) {
        return Complex{c, 0.0};  // phi ~ 0: every term is 1 (tables only use |phi| << pi)
    }
    return std::polar(std::sin(0.5 * phi * c) / half, 0.5 * phi * (c - 1.0));
}

// A(theta) = sum_i w[i] e^{-j theta i} for the engine window (sine rise to pivot,
// cosine fall after), in closed form so long windows are cheap to tabulate.
Complex windowSpectrum(std::size_t n, std::size_t pivot, double theta) noexcept {
    const auto alpha = pi / (2.0 * static_cast<double>(pivot));
    const auto beta = pi / (2.0 * static_cast<double>(n - pivot));
    const auto rise = (geometric(alpha - theta, pivot) - geometric(-alpha - theta, pivot)) / Complex{0.0, 2.0};
    const auto fall = 0.5 * (geometric(beta - theta, n - pivot) + geometric(-beta - theta, n - pivot));
    return rise + std::polar(1.0, -theta * static_cast<double>(pivot)) * fall;
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
    // A transport entry. Well-fitted partials own their whole lobe (+-lobeSpan
    // bins, image on the mirrored bins) so their window skirts move with them;
    // Plain and Residual entries own their bins minus every lobe there. Plain:
    // a region (lobe if its fit is good); Residual: a split group's bins, no
    // lobe; Component: one fitted lobe of a split group, no bins.
    enum class Kind { Plain, Residual, Component };
    struct Region {
        std::size_t peak = 0;
        std::size_t begin = 0;
        std::size_t end = 0;
        double omega = 0.0;
        double rotation = 0.0;
        Kind kind = Kind::Plain;
        std::size_t components = 0;          // Residual: count of following components
        std::array<Complex, 2> amplitude{};  // per-channel lobe amplitude
        bool lobe = false;
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
          nLong(longFactor * n), longBinWidth(twoPi / static_cast<double>(nLong)),
          longLimit(std::min(nLong / 2 - 2, static_cast<std::size_t>(
              std::ceil(longLimitHz / config.sampleRate * static_cast<double>(nLong))))),
          fft(n), longFft(nLong), analysis(n), longAnalysis(nLong), synthesis(length), transportSynthesis(length), dcWindow(length), controlHistory(length),
          frameControl(length), negativeSuffix(length), magnitude(bins),
          binOmega(bins), peaks(bins), time(nLong), inverseSpectrum(n), inverseTime(n),
          modulation(length), taper(n / 2), lobe(2 * lobeRange * lobeOversample + 1),
          longLobe(lobe.size()), longMagnitude(longLimit + 2), longPeaks(longLimit + 2),
          longOmega(longLimit + 2) {
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            history[channel].resize(nLong);
            output[channel].resize(ringSize);
            spectrum[channel].resize(n);
            longSpectrum[channel].resize(nLong);
            model[channel].resize(bins);
        }
        // Both windows: sine rise to N - L/2, cosine fall over the last L/2.
        auto makeWindow = [this](std::vector<double>& window, std::vector<Complex>& table, double& sum) {
            const auto size = window.size();
            const auto pivot = size - length / 2;
            for (std::size_t index = 0; index < size; ++index) {
                window[index] = index < pivot
                    ? std::sin(pi * static_cast<double>(index) / (2.0 * static_cast<double>(pivot)))
                    : std::cos(pi * static_cast<double>(index - pivot) /
                               (2.0 * static_cast<double>(size - pivot)));
                sum += window[index];
            }
            // Window spectrum tabulated at 1/lobeOversample bin over +-lobeRange
            // bins (of this window's own size) for the frequency fits.
            for (std::size_t entry = 0; entry < table.size(); ++entry) {
                const auto offset = static_cast<double>(entry) / static_cast<double>(lobeOversample) -
                                    static_cast<double>(lobeRange);
                table[entry] = windowSpectrum(size, pivot, offset * twoPi / static_cast<double>(size));
            }
        };
        makeWindow(analysis, lobe, analysisSum);
        makeWindow(longAnalysis, longLobe, longSum);
        for (std::size_t q = 0; q < length; ++q) {
            const auto product = (1.0 - std::cos(twoPi * static_cast<double>(q) /
                                               static_cast<double>(length))) / 4.0;
            synthesis[q] = product / analysis[n - length + q];
            transportSynthesis[q] = synthesis[q] * inverseN;
            dcWindow[q] = product;  // analysis * synthesis: exact partition of unity
        }
        for (std::size_t bin = 0; bin < bins; ++bin) {
            binOmega[bin] = twoPi * static_cast<double>(bin) / static_cast<double>(n);
        }
        reset();
    }

    Complex lobeAt(double offsetBins) const noexcept { return lobeAt(lobe, offsetBins); }

    static Complex lobeAt(const std::vector<Complex>& table, double offsetBins) noexcept {
        const auto range = static_cast<double>(lobeRange);
        if (offsetBins <= -range || offsetBins >= range) {
            return Complex{};
        }
        const auto position = (offsetBins + range) * static_cast<double>(lobeOversample);
        const auto lower = static_cast<std::size_t>(position);
        const auto fraction = position - static_cast<double>(lower);
        return table[lower] * (1.0 - fraction) + table[lower + 1] * fraction;
    }

    // Least-squares residual of X[k] = a A(w_k - w) + conj(a) A(w_k + w) over the
    // three peak bins, summed over channels (a per channel). The image term is
    // what the parabola and phase-difference estimates lacked: without it the
    // estimate wobbled 150-680 cents frame to frame below bin 4
    // (docs/results/2026-10-10-estimator-probe.txt).
    double lobeFitCost(std::size_t peak, double centreBins,
                       std::array<Complex, 2>* amplitude = nullptr) const noexcept {
        return lobeFitCost(spectrum, lobe, analysisSum, peak, centreBins, amplitude);
    }

    static double lobeFitCost(const std::array<std::vector<Complex>, 2>& spectrum,
                              const std::vector<Complex>& table, double analysisSum,
                              std::size_t peak, double centreBins,
                              std::array<Complex, 2>* amplitude = nullptr) noexcept {
        std::array<double, 3> a0{}, a1{}, b0{}, b1{};
        for (std::size_t i = 0; i < 3; ++i) {
            const auto k = static_cast<double>(peak + i) - 1.0;
            const auto p = lobeAt(table, k - centreBins);
            const auto m = lobeAt(table, k + centreBins);
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

    // Window-skirt ripples of a strong partial are local maxima above the 1e-4
    // floor; as regions they slice that partial's own skirt and re-emit it with
    // another translation (hop-rate combs at about -52 dB, window study Q1).
    // Keep a peak only if it exceeds twice the skirt predicted from the nearest
    // larger peak on each side.
    static std::size_t dropSkirtPeaks(const std::vector<double>& magnitude, std::vector<std::size_t>& peaks,
                                      const std::vector<Complex>& table, std::size_t count) noexcept {
        const auto scale = 1.0 / std::abs(table[lobeRange * lobeOversample]);
        auto predicted = [&](std::size_t from, std::size_t at) {
            const auto distance = std::abs(static_cast<double>(at) - static_cast<double>(from));
            const auto image = static_cast<double>(at + from);
            return magnitude[from] * scale * (std::abs(lobeAt(table, std::max(distance - 0.5, 0.0))) +
                                              std::abs(lobeAt(table, std::max(image - 0.5, 0.0))));
        };
        auto kept = std::size_t{0};
        for (std::size_t i = 0; i < count; ++i) {
            const auto bin = peaks[i];
            auto skirt = 0.0;
            for (auto j = i; j-- > 0;) {
                if (magnitude[peaks[j]] > magnitude[bin]) {
                    skirt += predicted(peaks[j], bin);
                    break;
                }
            }
            for (auto j = i + 1; j < count; ++j) {
                if (magnitude[peaks[j]] > magnitude[bin]) {
                    skirt += predicted(peaks[j], bin);
                    break;
                }
            }
            if (magnitude[bin] >= 2.0 * skirt) {
                peaks[kept++] = bin;
            }
        }
        return kept;
    }

    // Coarse-to-fine 1-D search of cost(centre) over [low, high] (bins).
    template <typename Cost>
    static double searchCentre(double low, double high, int rounds, int points, Cost cost) noexcept {
        for (int round = 0; round < rounds; ++round) {
            const auto step = (high - low) / static_cast<double>(points - 1);
            auto best = std::numeric_limits<double>::max();
            auto centre = low;
            for (int i = 0; i < points; ++i) {
                const auto candidate = low + step * i;
                const auto value = cost(candidate);
                if (value < best) {
                    best = value;
                    centre = candidate;
                }
            }
            low = centre - step;
            high = centre + step;
        }
        return 0.5 * (low + high);
    }

    double fitOmega(std::size_t peak, std::array<Complex, 2>& amplitude, bool& good) noexcept {
        // The range reaches 0 so a DC lobe fits as an untranslated w = 0 tone.
        const auto found = searchCentre(peak <= 1 ? 0.0 : static_cast<double>(peak) - 0.6,
                                        static_cast<double>(peak) + 0.6, 5, 13,
                                        [&](double c) { return lobeFitCost(peak, c); });
        const auto centre = std::clamp(found, 0.0, 0.5 * static_cast<double>(n) - 0.5);
        auto energy = 0.0;
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            for (auto bin = peak - 1; bin <= peak + 1; ++bin) {
                energy += std::norm(spectrum[channel][bin]);
            }
        }
        // Below one bin (a DC lobe) the positive/image split of the lobe is
        // ill-conditioned; such regions keep bins only and bin 0 stays DC.
        good = lobeFitCost(peak, centre, &amplitude) <= lobeQuality * energy && centre >= 1.0;
        return centre * binWidth;
    }

    // Joint least squares of X[k] = sum_c a_c A(k - w_c) + conj(a_c) A(k + w_c)
    // over bins [first, last), a_c per channel; returns the residual energy.
    using Amplitudes = std::array<std::array<Complex, maxSplit>, 2>;
    static double jointFit(const std::array<std::vector<Complex>, 2>& spectrum,
                           const std::vector<Complex>& table, std::size_t first, std::size_t last,
                           const double* centres, std::size_t count, Amplitudes* amplitudes) noexcept {
        constexpr auto maxDim = 2 * maxSplit;
        const auto dim = 2 * count;
        std::array<std::array<double, maxDim>, maxDim> gram{};
        std::array<std::array<double, maxDim>, 2> rhs{};
        std::array<double, 2> energy{};
        std::array<Complex, maxDim> column{};
        for (auto k = first; k < last; ++k) {
            for (std::size_t c = 0; c < count; ++c) {
                const auto p = lobeAt(table, static_cast<double>(k) - centres[c]);
                const auto m = lobeAt(table, static_cast<double>(k) + centres[c]);
                column[2 * c] = p + m;                                     // Re a
                column[2 * c + 1] = Complex{m.imag() - p.imag(), p.real() - m.real()};  // Im a
            }
            for (std::size_t u = 0; u < dim; ++u) {
                for (auto v = u; v < dim; ++v) {
                    gram[u][v] += (std::conj(column[u]) * column[v]).real();
                }
                for (auto channel = std::size_t{0}; channel < 2; ++channel) {
                    rhs[channel][u] += (std::conj(column[u]) * spectrum[channel][k]).real();
                }
            }
            for (auto channel = std::size_t{0}; channel < 2; ++channel) {
                energy[channel] += std::norm(spectrum[channel][k]);
            }
        }
        auto trace = 0.0;
        for (std::size_t u = 0; u < dim; ++u) {
            for (std::size_t v = 0; v < u; ++v) {
                gram[u][v] = gram[v][u];
            }
            trace += gram[u][u];
        }
        for (std::size_t u = 0; u < dim; ++u) {
            gram[u][u] += 1e-12 * trace;
        }
        // Cholesky factor in place (the ridge keeps it positive definite).
        for (std::size_t u = 0; u < dim; ++u) {
            for (std::size_t v = 0; v <= u; ++v) {
                auto sum = gram[u][v];
                for (std::size_t w = 0; w < v; ++w) {
                    sum -= gram[u][w] * gram[v][w];
                }
                gram[u][v] = u == v ? std::sqrt(std::max(sum, 1e-300)) : sum / gram[v][v];
            }
        }
        auto cost = 0.0;
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::array<double, maxDim> solution{};
            for (std::size_t u = 0; u < dim; ++u) {
                auto sum = rhs[channel][u];
                for (std::size_t w = 0; w < u; ++w) {
                    sum -= gram[u][w] * solution[w];
                }
                solution[u] = sum / gram[u][u];
            }
            for (auto u = dim; u-- > 0;) {
                auto sum = solution[u];
                for (auto w = u + 1; w < dim; ++w) {
                    sum -= gram[w][u] * solution[w];
                }
                solution[u] = sum / gram[u][u];
            }
            auto explained = 0.0;
            for (std::size_t u = 0; u < dim; ++u) {
                explained += solution[u] * rhs[channel][u];
            }
            cost += std::max(0.0, energy[channel] - explained);
            if (amplitudes != nullptr) {
                for (std::size_t c = 0; c < count; ++c) {
                    (*amplitudes)[channel][c] = Complex{solution[2 * c], solution[2 * c + 1]};
                }
            }
        }
        return cost;
    }

    // Peaks of the long (omega-only) analysis below longLimitHz, skirt peaks dropped.
    void findLongPeaks(double largest) noexcept {
        longPeakCount = 0;
        if (unitySupport) {
            return;  // no translation, nothing to separate
        }
        for (std::size_t bin = 0; bin < longMagnitude.size(); ++bin) {
            longMagnitude[bin] = std::hypot(std::abs(longSpectrum[0][bin]), std::abs(longSpectrum[1][bin]));
        }
        const auto floor = largest * 1e-4 * longSum / analysisSum;
        for (std::size_t bin = 1; bin <= longLimit; ++bin) {
            if (longMagnitude[bin] >= longMagnitude[bin - 1] && longMagnitude[bin] > longMagnitude[bin + 1] &&
                longMagnitude[bin] >= floor) {
                longPeaks[longPeakCount] = bin;
                longOmega[longPeakCount++] = std::numeric_limits<double>::quiet_NaN();
            }
        }
        longPeakCount = dropSkirtPeaks(longMagnitude, longPeaks, longLobe, longPeakCount);
    }

    // An unresolved short region (two or more long peaks inside its bins) is
    // split: the long analysis supplies each component's omega (joint cluster
    // fit, the neighbours bias single-lobe fits by ~14 cents p-p), the short
    // frame only their amplitudes. Returns the component count (0: no split);
    // centres are in short bins. docs/quality/2026-10-10-multires-gauntlet.md
    std::size_t splitRegion(std::size_t index, std::size_t last, std::size_t begin, std::size_t end,
                            std::size_t room, std::array<double, maxSplit>& centres,
                            Amplitudes& amplitudes) noexcept {
        // Candidates: long peaks inside the bins and near one of the group's short
        // peaks; weaker than -40 dB re the strongest they are long-window skirt
        // ripple (seen at -60...-90 dB on single notes), not a second partial.
        auto candidate = [&](std::size_t j) {
            const auto position = static_cast<double>(longPeaks[j]) / static_cast<double>(longFactor);
            if (position < static_cast<double>(begin) - 0.5 || position >= static_cast<double>(end) - 0.5) {
                return false;
            }
            for (auto i = index; i <= last; ++i) {
                if (std::abs(position - static_cast<double>(peaks[i])) <= 2.5) {
                    return true;
                }
            }
            return false;
        };
        auto strongest = 0.0;
        for (std::size_t j = 0; j < longPeakCount; ++j) {
            strongest = candidate(j) ? std::max(strongest, longMagnitude[longPeaks[j]]) : strongest;
        }
        std::array<std::size_t, maxSplit> chosen{};
        auto count = std::size_t{0};
        for (std::size_t j = 0; j < longPeakCount; ++j) {
            if (candidate(j) && longMagnitude[longPeaks[j]] >= 0.01 * strongest) {
                if (count == maxSplit) {
                    return 0;
                }
                chosen[count++] = longPeaks[j];
            }
        }
        if (count < 2 || count + 1 > room || end - begin < count + 1) {
            return 0;
        }
        std::array<double, maxSplit> fitted{};
        for (std::size_t c = 0; c < count; ++c) {
            const auto peak = chosen[c];
            fitted[c] = searchCentre(peak <= 1 ? 0.0 : static_cast<double>(peak) - 0.6,
                                     static_cast<double>(peak) + 0.6, 5, 13, [&](double centre) {
                                         return lobeFitCost(longSpectrum, longLobe, longSum, peak, centre);
                                     });
        }
        const auto low = chosen[0] > 1 ? chosen[0] - 1 : 0;
        const auto high = chosen[count - 1] + 2;
        for (int sweep = 0; sweep < 3; ++sweep) {
            for (std::size_t c = 0; c < count; ++c) {
                const auto start = fitted[c];
                fitted[c] = searchCentre(std::max(start - 0.6, 0.0), start + 0.6, 4, 9, [&](double centre) {
                    fitted[c] = centre;
                    return jointFit(longSpectrum, longLobe, low, high, fitted.data(), count, nullptr);
                });
            }
        }
        for (std::size_t c = 0; c < count; ++c) {
            centres[c] = fitted[c] / static_cast<double>(longFactor);
            if (c > 0 && centres[c] - centres[c - 1] < minSplitBins) {
                return 0;
            }
        }
        jointFit(spectrum, lobe, begin, end, centres.data(), count, &amplitudes);
        return count;
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
        if (++historyPosition == nLong) {
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
        binZeroShare = {};
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
        count = dropSkirtPeaks(magnitude, peaks, lobe, count);
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
        findLongPeaks(largest);
        auto inherit = [this](double omega) {
            if (previousRegionCount == 0) {
                return 0.0;
            }
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
            auto rotation = principal(ancestor.rotation + advance);
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
            return rotation;
        };
        auto entries = std::size_t{0};
        std::array<double, maxSplit> centres{};
        Amplitudes amplitudes{};
        auto beginOf = [&](std::size_t i) { return i == 0 ? 0 : (peaks[i - 1] + peaks[i]) / 2 + 1; };
        auto endOf = [&](std::size_t i) { return i + 1 == count ? n / 2 : (peaks[i] + peaks[i + 1]) / 2 + 1; };
        // Long peaks inside short region i, as [first, last] indices (first > last: none).
        auto longInside = [&](std::size_t i, std::size_t& first, std::size_t& last) {
            first = longPeakCount;
            last = 0;
            for (std::size_t j = 0; j < longPeakCount; ++j) {
                const auto position = static_cast<double>(longPeaks[j]) / static_cast<double>(longFactor);
                if (position >= static_cast<double>(beginOf(i)) - 0.5 && position < static_cast<double>(endOf(i)) - 0.5) {
                    first = std::min(first, j);
                    last = j;
                }
            }
            return first <= last;
        };
        std::array<Complex, 2> amplitude{};
        auto good = false;
        auto emitPlain = [&](std::size_t index) {
            const auto peak = peaks[index];
            const auto omega = fitOmega(peak, amplitude, good);
            regions[entries++] = Region{peak, beginOf(index), endOf(index), omega, inherit(omega), Kind::Plain, 0,
                                        amplitude, good};
        };
        for (std::size_t index = 0; index < count;) {
            // An unresolved pair can show as two short peaks (phase dependent);
            // merge neighbouring regions whose long peaks are < 3 short bins apart
            // so the split decision does not flip with the beat phase.
            auto last = index;
            std::size_t lowFirst = 0, lowLast = 0, highFirst = 0, highLast = 0;
            while (last + 1 < count && longInside(last, lowFirst, lowLast) &&
                   longInside(last + 1, highFirst, highLast) &&
                   longPeaks[highFirst] - longPeaks[lowLast] < 3 * longFactor) {
                ++last;
            }
            auto strongest = index;
            for (auto i = index + 1; i <= last; ++i) {
                strongest = magnitude[peaks[i]] > magnitude[peaks[strongest]] ? i : strongest;
            }
            const auto begin = beginOf(index);
            const auto end = endOf(last);
            const auto split = splitRegion(index, last, begin, end, maxEntries - entries - (count - last - 1), centres, amplitudes);
            if (split == 0) {
                for (auto i = index; i <= last; ++i) {
                    emitPlain(i);
                }
                index = last + 1;
                continue;
            }
            const auto peak = peaks[strongest];
            const auto omega = fitOmega(peak, amplitude, good);
            regions[entries++] = Region{peak, begin, end, omega, inherit(omega), Kind::Residual, split, {}, false};
            for (std::size_t c = 0; c < split; ++c) {
                const auto component = centres[c] * binWidth;
                regions[entries++] = Region{peak, begin, end, component, inherit(component), Kind::Component, 0,
                                            {amplitudes[0][c], amplitudes[1][c]}, true};
            }
            index = last + 1;
        }
        regionCount = entries;
        // Sum of all transported lobes; owners render X - model in their bins and
        // the bin-0 remainder X[0] - model[0] is the untranslated DC term.
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            std::fill(model[channel].begin(), model[channel].end(), Complex{});
        }
        for (std::size_t index = 0; index < entries; ++index) {
            const auto& region = regions[index];
            if (!region.lobe) {
                continue;
            }
            const auto centre = region.omega / binWidth;
            std::size_t first = 0, last = 0;
            lobeBins(centre, first, last);
            for (auto bin = first; bin < last; ++bin) {
                const auto k = static_cast<double>(bin);
                const auto p = lobeAt(k - centre);
                const auto m = lobeAt(k + centre);
                for (auto channel = std::size_t{0}; channel < 2; ++channel) {
                    const auto& a = region.amplitude[channel];
                    model[channel][bin] += a * p + std::conj(a) * m;
                }
            }
        }
        binZeroShare = {model[0][0].real(), model[1][0].real()};
        if (entries > 0 && regions[0].kind == Kind::Plain && !regions[0].lobe) {
            // A lobe-less lowest region (a DC lobe) keeps its fitted bin-0 share.
            const auto centre = regions[0].omega / binWidth;
            for (auto channel = std::size_t{0}; channel < 2; ++channel) {
                const auto& a = regions[0].amplitude[channel];
                binZeroShare[channel] += (a * lobeAt(-centre) + std::conj(a) * lobeAt(centre)).real();
            }
        }
    }

    void lobeBins(double centre, std::size_t& first, std::size_t& last) const noexcept {
        const auto base = static_cast<std::size_t>(centre);
        first = base > lobeSpan ? base - lobeSpan : 0;
        last = std::min(n / 2, base + lobeSpan + 2);
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
            auto source = historyPosition + nLong - n;
            if (source >= nLong) {
                source -= nLong;
            }
            for (std::size_t index = 0; index < n; ++index) {
                time[index] = Complex{history[channel][source] * analysis[index], 0.0};
                if (++source == nLong) {
                    source = 0;
                }
            }
            fft.fft(time.data(), spectrum[channel].data());
            spectrum[channel][0].imag(0.0);
            spectrum[channel][n / 2].imag(0.0);
            if (!unitySupport) {
                source = historyPosition;
                for (std::size_t index = 0; index < nLong; ++index) {
                    time[index] = Complex{history[channel][source] * longAnalysis[index], 0.0};
                    if (++source == nLong) {
                        source = 0;
                    }
                }
                longFft.fft(time.data(), longSpectrum[channel].data());
            }
        }
        findRegions();
        // Exact delayed unity only once every inherited rotation has settled to
        // zero; until then unity frames render regions with delta 0 like any other.
        const auto exactUnity = unitySupport && !settling;
        for (auto channel = std::size_t{0}; channel < 2; ++channel) {
            auto destination = frameOutputStart;
            const auto dc = (spectrum[channel][0].real() - binZeroShare[channel]) / analysisSum;
            auto source = historyPosition + nLong - length;
            if (source >= nLong) {
                source -= nLong;
            }
            for (std::size_t q = 0; q < length; ++q) {
                output[channel][destination] += exactUnity
                    ? history[channel][source] * analysis[n - length + q] * synthesis[q]
                    : dc * dcWindow[q];
                if (++destination == ringSize) {
                    destination = 0;
                }
                if (++source == nLong) {
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
        const auto begin = region.begin;
        const auto end = region.end;
        const auto delta = region.omega * frameRatioMinusOne;
        const auto guard = 2.0 * binWidth;
        const auto centre = region.omega / binWidth;
        std::size_t lobeFirst = 0, lobeLast = 0;
        if (region.lobe) {
            lobeBins(centre, lobeFirst, lobeLast);
        }
        const auto taperFirst = region.lobe ? std::min(begin, lobeFirst) : begin;
        const auto taperLast = region.lobe ? std::max(end, lobeLast) : end;
        for (auto bin = taperFirst; bin < taperLast; ++bin) {
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
            if (region.lobe) {
                // The image term conj(a)*A(k+w) is the negative-frequency partial's
                // leakage: conjugated on the mirrored bins the modulator moves it
                // by -delta with its partial (as positive content it left f - delta
                // lines at -31 dB on the warble dyad). Bin 0 carries 2*a*A(-w),
                // whose real part is the whole bin-0 share.
                const auto& a = region.amplitude[channel];
                for (auto bin = lobeFirst; bin < lobeLast; ++bin) {
                    const auto k = static_cast<double>(bin);
                    inverseSpectrum[bin] += 2.0 * a * lobeAt(k - centre) * taper[bin];
                    if (bin > 0) {
                        inverseSpectrum[n - bin] += 2.0 * a * std::conj(lobeAt(k + centre)) * taper[bin];
                    }
                }
            }
            if (region.kind == Kind::Plain && !region.lobe && begin == 0) {
                inverseSpectrum[0] += 2.0 * region.amplitude[channel] * lobeAt(-centre) * taper[0];
            }
            if (region.kind != Kind::Component) {
                for (auto bin = std::max<std::size_t>(begin, 1); bin < end; ++bin) {
                    inverseSpectrum[bin] += 2.0 * (spectrum[channel][bin] - model[channel][bin]) * taper[bin];
                }
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
    const std::size_t nLong;
    const double longBinWidth;
    const std::size_t longLimit;
    Transform fft;
    Transform longFft;
    std::vector<double> analysis;
    std::vector<double> longAnalysis;
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
    std::vector<Complex> longLobe;
    std::array<std::vector<Complex>, 2> longSpectrum;
    std::vector<double> longMagnitude;
    std::vector<std::size_t> longPeaks;
    std::vector<double> longOmega;  // fitted, in long bins; NaN until needed this frame
    double analysisSum = 0.0;
    double longSum = 0.0;
    std::array<std::vector<Complex>, 2> model;
    std::array<Region, maxEntries> regions{};
    std::array<Region, maxEntries> previousRegions{};
    std::array<double, 2> binZeroShare{};
    std::size_t historyPosition = 0;
    std::size_t controlPosition = 0;
    std::size_t outputPosition = 0;
    std::size_t frameOutputStart = 0;
    std::size_t hopPhase = 0;
    std::size_t regionCount = 0;
    std::size_t longPeakCount = 0;
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
