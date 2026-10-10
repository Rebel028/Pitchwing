#include "pitchwing/Engine.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct Options {
    pitchwing::EngineConfig engine;
    std::filesystem::path input;
    std::filesystem::path output;
    std::size_t block = 128;
    std::optional<std::size_t> warmupFrames;
    bool benchmark = false;
};

const char* statusName(const pitchwing::Status status) noexcept {
    switch (status) {
    case pitchwing::Status::Ok: return "Ok";
    case pitchwing::Status::InvalidBuffer: return "InvalidBuffer";
    case pitchwing::Status::InvalidSample: return "InvalidSample";
    case pitchwing::Status::InvalidPitch: return "InvalidPitch";
    case pitchwing::Status::PitchLocked: return "PitchLocked";
    case pitchwing::Status::StreamClosed: return "StreamClosed";
    case pitchwing::Status::BufferTooSmall: return "BufferTooSmall";
    case pitchwing::Status::NotPrepared: return "NotPrepared";
    }
    return "Unknown";
}

void requireOk(const pitchwing::Status status, const char* operation) {
    if (status != pitchwing::Status::Ok) {
        throw std::runtime_error(std::string(operation) + " failed: " + statusName(status));
    }
}

std::size_t integerValue(const std::string& text, const std::string& option, const bool allowZero = false) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos) {
        throw std::invalid_argument(option + " requires a positive integer");
    }
    std::size_t consumed = 0;
    const auto number = std::stoull(text, &consumed);
    if (consumed != text.size() || (!allowZero && number == 0) || number > std::numeric_limits<std::size_t>::max()) {
        throw std::invalid_argument(option + " is out of range");
    }
    return static_cast<std::size_t>(number);
}

double finiteNumber(const std::string& text, const std::string& option) {
    std::size_t consumed = 0;
    const auto number = std::stod(text, &consumed);
    if (consumed != text.size() || !std::isfinite(number)) {
        throw std::invalid_argument(option + " requires a finite number");
    }
    return number;
}

void usage() {
    std::cout << "Usage: pitchwing_render --input INPUT.f64 --output NEW_OUTPUT.f64 [options]\n"
                 "Raw files contain mono little-endian IEEE float64 samples, without a header.\n"
                 "Options: --sample-rate 48000 --semitones 0 --analysis-size 2048\n"
                 "         --synthesis-size 384 --hop 96 --window asymmetric|symmetric\n"
                 "         --block 128 --benchmark --warmup-frames N\n"
                 "Default benchmark warmup: analysis-size + synthesis-size source frames.\n"
                 "Outputs the complete process + flush stream and a JSON report on stdout.\n"
                 "Benchmarking times only preloaded process calls; WSL is not a native deadline test.\n";
}

Options parseOptions(const int argc, char** argv) {
    auto options = Options{};
    for (int index = 1; index < argc; ++index) {
        const auto option = std::string(argv[index]);
        if (option == "--benchmark") {
            options.benchmark = true;
            continue;
        }
        if (index + 1 >= argc) {
            throw std::invalid_argument("missing value for " + option);
        }
        const auto value = std::string(argv[++index]);
        if (option == "--input") options.input = value;
        else if (option == "--output") options.output = value;
        else if (option == "--sample-rate") options.engine.sampleRate = finiteNumber(value, option);
        else if (option == "--semitones") options.engine.pitchSemitones = finiteNumber(value, option);
        else if (option == "--analysis-size") options.engine.analysisSize = integerValue(value, option);
        else if (option == "--synthesis-size") options.engine.synthesisSize = integerValue(value, option);
        else if (option == "--hop") options.engine.hop = integerValue(value, option);
        else if (option == "--block") options.block = integerValue(value, option);
        else if (option == "--warmup-frames") options.warmupFrames = integerValue(value, option, true);
        else if (option == "--window") {
            if (value == "asymmetric") options.engine.window = pitchwing::Window::Asymmetric;
            else if (value == "symmetric") options.engine.window = pitchwing::Window::Symmetric;
            else throw std::invalid_argument("--window must be asymmetric or symmetric");
        } else {
            throw std::invalid_argument("unknown option: " + option);
        }
    }
    if (options.input.empty() || options.output.empty()) {
        throw std::invalid_argument("--input and --output are required");
    }
    if (options.engine.sampleRate <= 0.0) {
        throw std::invalid_argument("--sample-rate must be positive");
    }
    if (std::filesystem::exists(options.output)) {
        throw std::invalid_argument("output already exists; choose a new path");
    }
    return options;
}

std::vector<double> readSamples(const std::filesystem::path& path) {
    static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
                  "raw format requires 64-bit IEEE doubles");
    const auto endianProbe = std::uint16_t{1};
    if (*reinterpret_cast<const unsigned char*>(&endianProbe) != 1) {
        throw std::runtime_error("raw float64 runner currently requires a little-endian machine");
    }
    auto stream = std::ifstream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("cannot open raw input");
    const auto end = stream.tellg();
    if (end < 0) throw std::runtime_error("cannot determine raw input size");
    const auto bytes = static_cast<std::uintmax_t>(end);
    if (bytes % sizeof(double) != 0
        || bytes > static_cast<std::uintmax_t>(std::numeric_limits<std::streamsize>::max())
        || bytes / sizeof(double) > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error("raw input size is invalid or too large");
    }
    auto samples = std::vector<double>(static_cast<std::size_t>(bytes / sizeof(double)));
    stream.seekg(0, std::ios::beg);
    if (bytes != 0) {
        stream.read(reinterpret_cast<char*>(samples.data()), static_cast<std::streamsize>(bytes));
        if (!stream) throw std::runtime_error("cannot read complete raw input");
    }
    return samples;
}

void writeSamples(const std::filesystem::path& path, const std::vector<double>& samples) {
    if (samples.size() > static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max()) / sizeof(double)) {
        throw std::runtime_error("raw output is too large");
    }
    // This offline tool assumes one writer per requested new output path.
    auto stream = std::ofstream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open raw output");
    if (!samples.empty()) {
        stream.write(reinterpret_cast<const char*>(samples.data()),
                     static_cast<std::streamsize>(samples.size() * sizeof(double)));
    }
    stream.close();
    if (!stream) throw std::runtime_error("cannot write complete raw output");
}

} // namespace

int main(const int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            usage();
            return 0;
        }
        const auto options = parseOptions(argc, argv);
        const auto input = readSamples(options.input);
        auto engine = pitchwing::Engine(options.engine);
        const auto warmupFrames = options.warmupFrames.value_or(options.engine.analysisSize + options.engine.synthesisSize);
        const auto tailCapacity = engine.tailSamples();
        if (tailCapacity > std::numeric_limits<std::size_t>::max() - input.size()) {
            throw std::runtime_error("output sample count overflow");
        }
        auto output = std::vector<double>(input.size() + tailCapacity);
        auto elapsedMicroseconds = std::vector<double>{};
        if (options.benchmark) {
            elapsedMicroseconds.reserve(input.size() / options.block + (input.size() % options.block != 0 ? 1 : 0));
        }
        auto worstObservedDeadlineRatio = 0.0;
        auto deadlineMisses = std::size_t{0};
        auto timedFrames = std::size_t{0};
        auto excludedCalls = std::size_t{0};
        for (std::size_t position = 0; position < input.size();) {
            const auto count = std::min(options.block, input.size() - position);
            if (options.benchmark && position >= warmupFrames) {
                const auto begin = std::chrono::steady_clock::now();
                const auto status = engine.process(input.data() + position, output.data() + position, count);
                const auto end = std::chrono::steady_clock::now();
                requireOk(status, "process");
                const auto duration = std::chrono::duration<double, std::micro>(end - begin).count();
                elapsedMicroseconds.push_back(duration);
                timedFrames += count;
                const auto deadlineMicroseconds = 1e6 * static_cast<double>(count) / options.engine.sampleRate;
                worstObservedDeadlineRatio = std::max(worstObservedDeadlineRatio, duration / deadlineMicroseconds);
                if (duration > deadlineMicroseconds) ++deadlineMisses;
            } else {
                requireOk(engine.process(input.data() + position, output.data() + position, count), "process");
                if (options.benchmark) ++excludedCalls;
            }
            position += count;
        }
        auto written = std::size_t{0};
        auto* tailOutput = tailCapacity == 0 ? nullptr : output.data() + input.size();
        requireOk(engine.flush(tailOutput, tailCapacity, written), "flush");
        if (written > tailCapacity) throw std::runtime_error("engine wrote an invalid tail count");
        output.resize(input.size() + written);
        if (!std::all_of(output.begin(), output.end(), [](const double value) { return std::isfinite(value); })) {
            throw std::runtime_error("engine produced nonfinite samples");
        }
        writeSamples(options.output, output);
        std::cout << std::setprecision(17)
                  << "{\"input_frames\":" << input.size()
                  << ",\"output_frames\":" << output.size()
                  << ",\"tail_frames\":" << written
                  << ",\"latency_samples\":" << engine.latencySamples()
                  << ",\"block_frames\":" << options.block
                  << ",\"sample_rate\":" << options.engine.sampleRate
                  << ",\"benchmark\":";
        if (options.benchmark && !elapsedMicroseconds.empty()) {
            const auto total = std::accumulate(elapsedMicroseconds.begin(), elapsedMicroseconds.end(), 0.0);
            std::sort(elapsedMicroseconds.begin(), elapsedMicroseconds.end());
            const auto count = elapsedMicroseconds.size();
            const auto p95Index = static_cast<std::size_t>(std::ceil(0.95 * static_cast<double>(count))) - 1;
            std::cout << "{\"process_calls\":" << count
                      << ",\"warmup_frames\":" << warmupFrames
                      << ",\"excluded_process_calls\":" << excludedCalls
                      << ",\"timed_input_frames\":" << timedFrames
                      << ",\"mean_microseconds\":" << total / static_cast<double>(count)
                      << ",\"p95_microseconds\":" << elapsedMicroseconds[p95Index]
                      << ",\"max_microseconds\":" << elapsedMicroseconds.back()
                      << ",\"process_total_seconds\":" << total / 1e6
                      << ",\"worst_observed_block_deadline_ratio\":" << worstObservedDeadlineRatio
                      << ",\"observed_deadline_misses\":" << deadlineMisses
                      << ",\"throughput_input_frames_per_second\":";
            if (total > 0.0) std::cout << 1e6 * static_cast<double>(timedFrames) / total;
            else std::cout << "null";
            std::cout << ",\"limitations\":\"WSL diagnostic; includes timer overhead and partial final block; excludes preparation, warmup, I/O and flush; not a target-native real-time guarantee\"}";
        } else {
            std::cout << "null";
        }
        std::cout << "}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "pitchwing_render: " << error.what() << '\n';
        return 1;
    }
}
