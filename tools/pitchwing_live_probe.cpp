// Bounded offline diagnostics; timing under WSL is not a host deadline guarantee.
#include <pitchwing/LiveEngine.hpp>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstddef>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr double pi = 3.14159265358979323846;
void check(pitchwing::Status status) {
    if (status != pitchwing::Status::Ok) throw std::runtime_error("engine status error");
}

void timing() {
    std::cout << "{\"kind\":\"live-callback-timing\",\"clock\":\"steady_clock\","
                 "\"signal\":\"two distinct synthetic low guitar chords, 12 harmonics per note\","
                 "\"warmup_seconds\":0.25,\"measured_seconds\":0.5,"
                 "\"final_partial_blocks_excluded\":true,\"cases\":[\n";
    bool first = true;
    for (double rate : {44100.0, 48000.0, 96000.0}) {
        const auto warmup = static_cast<std::size_t>(rate / 4);
        const auto measured = static_cast<std::size_t>(rate / 2);
        const auto frames = warmup + measured;
        std::vector<float> left(frames), right(frames), outL(128), outR(128);
        for (std::size_t i = 0; i < frames; ++i) {
            double l = 0, r = 0;
            for (double fundamental : {38.89, 58.27, 77.78, 92.50}) {
                for (int harmonic = 1; harmonic <= 12; ++harmonic) {
                    const double angle = 2 * pi * fundamental * harmonic * static_cast<double>(i) / rate;
                    l += std::sin(angle + harmonic * 0.17) / harmonic;
                    r += std::sin(angle * 1.003 + harmonic * 0.31) / harmonic;
                }
            }
            left[i] = static_cast<float>(l * 0.05);
            right[i] = static_cast<float>(r * 0.05);
        }
        for (std::size_t block : {1U, 32U, 64U, 128U}) {
            for (bool automation : {false, true}) {
                pitchwing::LiveEngine engine({rate, -7});
                std::vector<double> durations;
                durations.reserve(measured / block + 2);
                std::size_t late = 0;
                double checksum = 0;
                for (std::size_t offset = 0; offset < frames;) {
                    auto n = std::min(block, frames - offset);
                    if (offset < warmup) n = std::min(n, warmup - offset);
                    const auto start = std::chrono::steady_clock::now();
                    // Split larger host blocks exactly as ShiftKey splits its control updates.
                    for (std::size_t part = 0; part < n;) {
                        const auto count = std::min<std::size_t>(32, n - part);
                        const double position = static_cast<double>(offset + part) / rate;
                        const double pitch = automation ? -7 + 9 * std::sin(2 * pi * 7 * position) : -7;
                        check(engine.setPitchSemitones(pitch));
                        check(engine.process(left.data() + offset + part, right.data() + offset + part,
                                             outL.data() + part, outR.data() + part, count));
                        part += count;
                    }
                    const double us = std::chrono::duration<double, std::micro>(
                        std::chrono::steady_clock::now() - start).count();
                    if (offset >= warmup && n == block) {
                        durations.push_back(us);
                        if (us > static_cast<double>(n) / rate * 1e6) ++late;
                    }
                    checksum += outL[n - 1] + outR[n - 1];
                    offset += n;
                }
                const double mean = std::accumulate(durations.begin(), durations.end(), 0.0) /
                                    static_cast<double>(durations.size());
                std::sort(durations.begin(), durations.end());
                const auto p95 = static_cast<std::size_t>(std::ceil(0.95 * durations.size())) - 1;
                if (!first) std::cout << ",\n";
                first = false;
                std::cout << "{\"sample_rate\":" << rate << ",\"block\":" << block
                          << ",\"automation\":" << (automation ? "true" : "false")
                          << ",\"latency_samples\":" << engine.latencySamples()
                          << ",\"calls\":" << durations.size() << ",\"mean_us\":" << mean
                          << ",\"p95_us\":" << durations[p95] << ",\"max_us\":" << durations.back()
                          << ",\"deadline_misses\":" << late << ",\"checksum\":" << checksum << "}";
            }
        }
    }
    std::cout << "\n]}\n";
}

// A centered 1024-point periodic Hann DFT, matching ShiftKey's amplitude-share
// definition. Precomputed taps avoid trig per center; phase origin cannot change magnitude.
using Taps = std::array<std::complex<double>, 1024>;
Taps taps(double frequency) {
    Taps result{};
    for (std::size_t k = 0; k < result.size(); ++k) {
        const double w = 0.5 - 0.5 * std::cos(2 * pi * k / result.size());
        result[k] = std::polar(w, 2 * pi * frequency * k / 48000);
    }
    return result;
}
double amplitude(const std::vector<float>& samples, std::size_t center, const Taps& kernel) {
    std::complex<double> sum{};
    for (std::size_t k = 0; k < kernel.size(); ++k)
        sum += static_cast<double>(samples[center - kernel.size() / 2 + k]) * kernel[k];
    return std::abs(sum);
}

void steps() {
    constexpr std::size_t settle = 96000, after = 7200, stride = 8;
    std::cout << "{\"kind\":\"live-pitch-step-response\",\"sample_rate\":48000,"
                 "\"input_hz\":220,\"settle_samples\":96000,\"block_max\":32,"
                 "\"window\":1024,\"scan_stride\":8,\"event_split_exact\":true,"
                 "\"metric\":\"new_frequency_amplitude/(old+new)\",\"cases\":[\n";
    bool first = true;
    for (const auto& change : std::array<std::array<double, 2>, 4>{{{0, 12}, {0, -12}, {12, 0}, {-12, 0}}}) {
        for (std::size_t phase = 0; phase < 96; phase += 8) {
            pitchwing::LiveEngine engine;
            check(engine.setPitchSemitones(change[0]));
            const std::size_t event = settle + phase, frames = event + after;
            std::vector<float> input(frames), output(frames), other(frames);
            for (std::size_t i = 0; i < frames; ++i)
                input[i] = static_cast<float>(0.5 * std::sin(2 * pi * 220 * i / 48000));
            for (std::size_t offset = 0; offset < frames;) {
                if (offset == event) check(engine.setPitchSemitones(change[1]));
                auto n = std::min<std::size_t>(32, frames - offset);
                if (offset < event) n = std::min(n, event - offset);
                check(engine.process(input.data() + offset, input.data() + offset,
                                     output.data() + offset, other.data() + offset, n));
                offset += n;
            }
            const auto old = taps(220 * std::exp2(change[0] / 12));
            const auto next = taps(220 * std::exp2(change[1] / 12));
            std::array<double, 3> crossings{{-1, -1, -1}};
            constexpr std::array<double, 3> thresholds{{0.1, 0.5, 0.9}};
            double previous = -1, firstShare = 0, lastShare = 0;
            const auto begin = event + engine.latencySamples() - 2048;
            const auto end = event + engine.latencySamples() + 4096;
            for (auto center = begin; center <= end; center += stride) {
                const double a = amplitude(output, center, old);
                const double b = amplitude(output, center, next);
                const double share = b / (a + b + 1e-12);
                if (center == begin) firstShare = share;
                lastShare = share;
                for (std::size_t j = 0; j < thresholds.size(); ++j) {
                    if (crossings[j] < 0 && previous >= 0 && previous < thresholds[j] && share >= thresholds[j])
                        crossings[j] = static_cast<double>(center - stride) +
                            stride * (thresholds[j] - previous) / (share - previous);
                }
                previous = share;
            }
            if (!first) std::cout << ",\n";
            first = false;
            std::cout << "{\"from\":" << change[0] << ",\"to\":" << change[1]
                      << ",\"phase\":" << phase << ",\"event\":" << event
                      << ",\"latency_samples\":" << engine.latencySamples()
                      << ",\"start_share\":" << firstShare << ",\"end_share\":" << lastShare;
            const bool valid = firstShare < 0.1 && lastShare > 0.9 && crossings[0] >= 0 &&
                crossings[0] <= crossings[1] && crossings[1] <= crossings[2];
            std::cout << ",\"valid_crossings\":" << (valid ? "true" : "false");
            for (std::size_t j = 0; j < crossings.size(); ++j) {
                std::cout << ",\"t" << static_cast<int>(thresholds[j] * 100) << "\":";
                if (crossings[j] < 0) std::cout << "null"; else std::cout << crossings[j];
            }
            std::cout << ",\"offset_samples\":";
            if (crossings[1] < 0) std::cout << "null";
            else std::cout << crossings[1] - event - engine.latencySamples();
            std::cout << ",\"width_samples\":";
            if (crossings[0] < 0 || crossings[2] < crossings[0]) std::cout << "null";
            else std::cout << crossings[2] - crossings[0];
            std::cout << "}";
        }
    }
    std::cout << "\n]}\n";
}
} // namespace

int main(int argc, char** argv) {
    try {
        std::cout << std::setprecision(12);
        if (argc != 2) throw std::invalid_argument("usage: pitchwing_live_probe timing|steps");
        const std::string mode(argv[1]);
        if (mode == "timing") timing();
        else if (mode == "steps") steps();
        else throw std::invalid_argument("unknown probe mode");
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
