// Deterministic LiveEngine contract checks, including automation and linked stereo.
// Passing these does not establish perceptual quality or callback deadlines.
// Tests are in memory, require no packages, and create no files. The parent
// workflow runs builds under /tmp to avoid build I/O on the mounted checkout.
#include "pitchwing/LiveEngine.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#if defined(_MSC_VER)
#include <malloc.h>
#endif

namespace allocation_probe {
std::atomic<bool> enabled{false};
std::atomic<std::size_t> count{0};

void record() noexcept {
    if (enabled.load(std::memory_order_relaxed)) {
        count.fetch_add(1, std::memory_order_relaxed);
    }
}

void* allocate(std::size_t size) {
    record();
    if (void* memory = std::malloc(size == 0 ? 1 : size)) {
        return memory;
    }
    throw std::bad_alloc();
}

void* allocateAligned(std::size_t size, std::size_t alignment) {
    record();
#if defined(_MSC_VER)
    if (void* memory = _aligned_malloc(size == 0 ? 1 : size, alignment)) {
        return memory;
    }
#else
    void* memory = nullptr;
    if (posix_memalign(&memory, alignment, size == 0 ? 1 : size) == 0) {
        return memory;
    }
#endif
    throw std::bad_alloc();
}

void freeAligned(void* memory) noexcept {
#if defined(_MSC_VER)
    _aligned_free(memory);
#else
    std::free(memory);
#endif
}

class Scope {
public:
    Scope() {
        count.store(0, std::memory_order_relaxed);
        enabled.store(true, std::memory_order_relaxed);
    }
    ~Scope() { enabled.store(false, std::memory_order_relaxed); }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;
};
}  // namespace allocation_probe

// These replacements catch standard allocator traffic, including aligned new.
// They are a regression check, not instrumentation for direct malloc/realloc
// calls or a proof about every platform's FFT/runtime implementation.
void* operator new(std::size_t size) { return allocation_probe::allocate(size); }
void* operator new[](std::size_t size) { return allocation_probe::allocate(size); }
void operator delete(void* memory) noexcept { std::free(memory); }
void operator delete[](void* memory) noexcept { std::free(memory); }
void operator delete(void* memory, std::size_t) noexcept { std::free(memory); }
void operator delete[](void* memory, std::size_t) noexcept { std::free(memory); }
void* operator new(std::size_t size, std::align_val_t alignment) {
    return allocation_probe::allocateAligned(size, static_cast<std::size_t>(alignment));
}
void* operator new[](std::size_t size, std::align_val_t alignment) {
    return allocation_probe::allocateAligned(size, static_cast<std::size_t>(alignment));
}
void operator delete(void* memory, std::align_val_t) noexcept {
    allocation_probe::freeAligned(memory);
}
void operator delete[](void* memory, std::align_val_t) noexcept {
    allocation_probe::freeAligned(memory);
}
void operator delete(void* memory, std::size_t, std::align_val_t) noexcept {
    allocation_probe::freeAligned(memory);
}
void operator delete[](void* memory, std::size_t, std::align_val_t) noexcept {
    allocation_probe::freeAligned(memory);
}
void* operator new(std::size_t size, const std::nothrow_t&) noexcept {
    try { return ::operator new(size); } catch (...) { return nullptr; }
}
void* operator new[](std::size_t size, const std::nothrow_t&) noexcept {
    try { return ::operator new[](size); } catch (...) { return nullptr; }
}
void operator delete(void* memory, const std::nothrow_t&) noexcept { std::free(memory); }
void operator delete[](void* memory, const std::nothrow_t&) noexcept { std::free(memory); }
void* operator new(std::size_t size, std::align_val_t alignment,
                   const std::nothrow_t&) noexcept {
    try { return ::operator new(size, alignment); } catch (...) { return nullptr; }
}
void* operator new[](std::size_t size, std::align_val_t alignment,
                     const std::nothrow_t&) noexcept {
    try { return ::operator new[](size, alignment); } catch (...) { return nullptr; }
}
void operator delete(void* memory, std::align_val_t,
                     const std::nothrow_t&) noexcept {
    allocation_probe::freeAligned(memory);
}
void operator delete[](void* memory, std::align_val_t,
                       const std::nothrow_t&) noexcept {
    allocation_probe::freeAligned(memory);
}


namespace {
using pitchwing::LiveConfig;
using pitchwing::LiveEngine;
using pitchwing::Status;
constexpr double pi = 3.141592653589793238462643383279502884;

void require(bool condition, const char* expression, int line) {
    if (!condition) {
        throw std::runtime_error(std::string("line ") + std::to_string(line)
                                 + ": " + expression);
    }
}
#define CHECK(expression) require(static_cast<bool>(expression), #expression, __LINE__)

template <class Sample> struct Stereo {
    std::vector<Sample> left;
    std::vector<Sample> right;
    explicit Stereo(std::size_t size) : left(size), right(size) {}
};

struct Command {
    std::size_t sample;
    double semitones;
};

Stereo<double> signal(std::size_t count, double rate = 48000.0) {
    Stereo<double> result(count);
    std::uint32_t state = 20261009;
    for (std::size_t i = 0; i < count; ++i) {
        state = 1664525U * state + 1013904223U;
        const double noise = static_cast<double>(state) / 4294967296.0 - 0.5;
        const double time = static_cast<double>(i) / rate;
        result.left[i] = 0.015 * noise + 0.12
            + 0.21 * std::sin(2.0 * pi * 30.867706 * time)
            + 0.09 * std::sin(2.0 * pi * 750.0 * time);
        result.right[i] = 0.012 * noise - 0.07
            + 0.18 * std::cos(2.0 * pi * 46.249303 * time)
            + 0.08 * std::sin(2.0 * pi * 1100.0 * time);
    }
    return result;
}

template <class To, class From>
Stereo<To> convert(const Stereo<From>& source) {
    Stereo<To> result(source.left.size());
    std::copy(source.left.begin(), source.left.end(), result.left.begin());
    std::copy(source.right.begin(), source.right.end(), result.right.begin());
    return result;
}

template <class Sample>
void near(const std::vector<Sample>& actual, const std::vector<Sample>& expected,
          double tolerance) {
    CHECK(actual.size() == expected.size());
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const double error = std::abs(static_cast<double>(actual[i])
                                      - static_cast<double>(expected[i]));
        if (!(error <= tolerance)) {
            throw std::runtime_error("sample " + std::to_string(i)
                                     + " absolute error " + std::to_string(error));
        }
    }
}

template <class Sample>
void near(const Stereo<Sample>& actual, const Stereo<Sample>& expected,
          double tolerance) {
    near(actual.left, expected.left, tolerance);
    near(actual.right, expected.right, tolerance);
}

template <class Sample>
Stereo<Sample> render(LiveEngine& engine, const Stereo<Sample>& source,
                      const std::vector<Command>& commands = {},
                      const std::vector<std::size_t>& blocks = {127, 1, 32, 96, 17}) {
    CHECK(source.left.size() == source.right.size());
    Stereo<Sample> output(source.left.size() + engine.tailSamples());
    std::size_t offset = 0;
    std::size_t blockIndex = 0;
    std::size_t commandIndex = 0;
    while (offset < source.left.size()) {
        while (commandIndex < commands.size() && commands[commandIndex].sample == offset) {
            CHECK(engine.setPitchSemitones(commands[commandIndex++].semitones) == Status::Ok);
        }
        std::size_t count = std::min(blocks[blockIndex % blocks.size()],
                                     source.left.size() - offset);
        if (commandIndex < commands.size()) {
            CHECK(commands[commandIndex].sample > offset);
            count = std::min(count, commands[commandIndex].sample - offset);
        }
        CHECK(count > 0);
        CHECK(engine.process(source.left.data() + offset, source.right.data() + offset,
                             output.left.data() + offset, output.right.data() + offset,
                             count) == Status::Ok);
        offset += count;
        ++blockIndex;
    }
    CHECK(commandIndex == commands.size());
    std::size_t written = 0;
    CHECK(engine.flush(output.left.data() + offset, output.right.data() + offset,
                       engine.tailSamples(), written) == Status::Ok);
    CHECK(written == engine.tailSamples());
    return output;
}

std::vector<Command> automation() {
    return {{0, -7.0}, {17, 2.5}, {97, 0.0}, {109, -0.25}, {384, 12.0},
            {479, -12.0}, {777, 7.0}, {1013, 0.0}, {1099, -2.0}, {1603, 0.0}};
}

void testConfigurationsAndRange() {
    const auto rejects = [](const LiveConfig& config) {
        try {
            LiveEngine engine(config);
        } catch (const std::invalid_argument&) {
            return true;
        }
        return false;
    };
    for (const double rate : {0.0, 7999.0, 192001.0,
                              std::numeric_limits<double>::infinity(),
                              std::numeric_limits<double>::quiet_NaN()}) {
        CHECK(rejects({rate, 0.0}));
    }
    for (const double pitch : {-49.001, 49.001, std::numeric_limits<double>::infinity(),
                               std::numeric_limits<double>::quiet_NaN()}) {
        CHECK(rejects({48000.0, pitch}));
    }
    for (const double rate : {8000.0, 44100.0, 48000.0, 96000.0, 192000.0}) {
        LiveEngine engine({rate, -49.0});
        CHECK(engine.config().sampleRate == rate);
        CHECK(engine.config().pitchSemitones == -49.0);
        const auto hop = static_cast<std::size_t>(std::floor(rate * 0.002));
        CHECK(engine.hopSamples() == hop);
        CHECK(engine.synthesisSize() == 4 * hop);
        CHECK(engine.latencySamples() == 5 * hop - 1);
        CHECK(static_cast<double>(engine.latencySamples()) / rate <= 0.01);
        CHECK(engine.analysisSize() >= static_cast<std::size_t>(std::ceil(rate * 2048.0 / 48000.0)));
        CHECK(engine.tailSamples() > engine.latencySamples());
        CHECK(engine.setPitchSemitones(49.0) == Status::Ok);
        auto copy = engine.config();
        copy.pitchSemitones = 0.0;
        CHECK(copy.pitchSemitones == 0.0);
        CHECK(engine.config().pitchSemitones == 49.0);
    }
}

void testUnityRatesAndSamplePhases() {
    for (const double rate : {44100.0, 48000.0, 96000.0}) {
        LiveEngine engine({rate, 0.0});
        const auto hop = engine.hopSamples();
        // Both channels contain nonzero samples at every hop phase. Varying
        // ending phases also exercises draining partially scheduled frames.
        for (const std::size_t phase : {std::size_t{0}, std::size_t{1}, hop - 1}) {
            CHECK(engine.reset() == Status::Ok);
            const auto source = signal(3 * hop + phase + 1, rate);
            const auto actual = render(engine, source, {}, {1, 32, 95});
            Stereo<double> expected(actual.left.size());
            std::copy(source.left.begin(), source.left.end(),
                      expected.left.begin() + static_cast<std::ptrdiff_t>(engine.latencySamples()));
            std::copy(source.right.begin(), source.right.end(),
                      expected.right.begin() + static_cast<std::ptrdiff_t>(engine.latencySamples()));
            near(actual, expected, 2e-11);
        }
        // Explicit sparse onset and final sample, spanning all scheduling phases.
        CHECK(engine.reset() == Status::Ok);
        Stereo<double> impulses(2 * hop + 1);
        for (std::size_t phase = 0; phase < hop; ++phase) {
            impulses.left[phase] = phase % 2 == 0 ? 0.5 : -0.25;
            impulses.right[hop + phase] = phase % 2 == 0 ? -0.3 : 0.4;
        }
        impulses.left.back() = 0.7;
        const auto actual = render(engine, impulses);
        Stereo<double> expected(actual.left.size());
        std::copy(impulses.left.begin(), impulses.left.end(),
                  expected.left.begin() + static_cast<std::ptrdiff_t>(engine.latencySamples()));
        std::copy(impulses.right.begin(), impulses.right.end(),
                  expected.right.begin() + static_cast<std::ptrdiff_t>(engine.latencySamples()));
        near(actual, expected, 2e-11);
    }
}

void testAutomationAndPartitions() {
    const auto source = signal(2401);
    const auto commands = automation();
    LiveEngine whole;
    LiveEngine divided;
    LiveEngine individual;
    const auto expected = render(whole, source, commands, {source.left.size()});
    near(render(divided, source, commands), expected, 0.0);
    near(render(individual, source, commands, {1}), expected, 0.0);
    CHECK(divided.reset() == Status::Ok);
    near(render(divided, source, commands, {32}), expected, 0.0);
}

void testStereoInvariants() {
    auto source = signal(2401);
    const auto commands = automation();
    LiveEngine original;
    const auto expected = render(original, source, commands);
    std::swap(source.left, source.right);
    LiveEngine swapped;
    auto actual = render(swapped, source, commands);
    std::swap(actual.left, actual.right);
    near(actual, expected, 2e-12);

    for (const int relation : {-1, 0, 1}) {
        source = signal(2401);
        for (std::size_t i = 0; i < source.left.size(); ++i) {
            source.right[i] = static_cast<double>(relation) * source.left[i];
        }
        LiveEngine engine;
        const auto output = render(engine, source, commands);
        double leftEnergy = 0.0;
        for (std::size_t i = 0; i < output.left.size(); ++i) {
            CHECK(std::isfinite(output.left[i]));
            CHECK(std::isfinite(output.right[i]));
            CHECK(std::abs(output.right[i] - static_cast<double>(relation) * output.left[i]) < 2e-11);
            leftEnergy += output.left[i] * output.left[i];
        }
        CHECK(leftEnergy > 1.0);  // Anti-phase input must not disappear in a downmix.
    }
    // The API also permits a single mono input pointer duplicated into stereo.
    LiveEngine duplicate;
    const auto mono = signal(601);
    Stereo<double> out(mono.left.size() + duplicate.tailSamples());
    CHECK(duplicate.setPitchSemitones(-7.0) == Status::Ok);
    CHECK(duplicate.process(mono.left.data(), mono.left.data(), out.left.data(),
                            out.right.data(), mono.left.size()) == Status::Ok);
    std::size_t written = 0;
    CHECK(duplicate.flush(out.left.data() + mono.left.size(), out.right.data() + mono.left.size(),
                          duplicate.tailSamples(), written) == Status::Ok);
    near(out.left, out.right, 0.0);
}

void testSubHopControlAndUnityReturn() {
    const auto source = signal(60001);
    LiveEngine reference;
    const auto identity = render(reference, source);
    const auto pulse = 8 * reference.hopSamples() + 13;
    for (const double pitch : {-12.0, 12.0}) {
        LiveEngine engine;
        const auto output = render(engine, source, {{pulse, pitch}, {pulse + 1, 0.0}}, {32});
        double largestDifference = 0.0;
        for (std::size_t i = 0; i < output.left.size(); ++i) {
            largestDifference = std::max(largestDifference,
                                         std::abs(output.left[i] - identity.left[i]));
        }
        CHECK(largestDifference > 1e-8);  // A one-sample command between frames survives.
    }

    LiveEngine returning({48000.0, -7.0});
    constexpr std::size_t release = 1027;
    const auto output = render(returning, source, {{release, 0.0}});
    // Allow full old support and pending frames to drain, plus the rotation
    // settling glide (pi at the 100 Hz floor and 0.006 per hop: <= 417 hops).
    // Eventual identity, not a claim that the transition is inaudible.
    const auto stable = release + 3 * returning.synthesisSize()
                        + 420 * returning.hopSamples() + returning.latencySamples();
    CHECK(stable < source.left.size());
    for (std::size_t i = stable; i < output.left.size(); ++i) {
        CHECK(std::abs(output.left[i] - identity.left[i]) < 2e-11);
        CHECK(std::abs(output.right[i] - identity.right[i]) < 2e-11);
    }
}

template <class Sample>
void testInPlaceAndValidation() {
    const auto source = convert<Sample>(signal(1201));
    LiveEngine reference({48000.0, -7.0});
    const auto expected = render(reference, source);
    LiveEngine inPlace({48000.0, -7.0});
    auto actual = source;
    CHECK(inPlace.process(actual.left.data(), actual.right.data(), actual.left.data(),
                          actual.right.data(), actual.left.size()) == Status::Ok);
    const auto size = actual.left.size();
    actual.left.resize(size + inPlace.tailSamples());
    actual.right.resize(size + inPlace.tailSamples());
    std::size_t written = 0;
    CHECK(inPlace.flush(actual.left.data() + size, actual.right.data() + size,
                        inPlace.tailSamples(), written) == Status::Ok);
    near(actual, expected, 0.0);

    LiveEngine tested({48000.0, -7.0});
    LiveEngine control({48000.0, -7.0});
    Stereo<Sample> prefix(97);
    CHECK(tested.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), prefix.left.size()) == Status::Ok);
    CHECK(control.process(source.left.data(), source.right.data(), prefix.left.data(),
                          prefix.right.data(), prefix.left.size()) == Status::Ok);
    std::array<Sample, 66> left{};
    std::array<Sample, 66> right{};
    std::array<Sample, 66> outLeft{};
    std::array<Sample, 66> outRight{};
    std::copy_n(source.left.begin(), left.size(), left.begin());
    std::copy_n(source.right.begin(), right.size(), right.begin());
    outLeft.fill(static_cast<Sample>(-0.875));
    outRight.fill(static_cast<Sample>(0.625));
    const auto oldLeft = left;
    const auto oldRight = right;
    const auto oldOutLeft = outLeft;
    const auto oldOutRight = outRight;
    CHECK(tested.process(left.data(), right.data(), left.data() + 1, outRight.data(), 64)
          == Status::InvalidBuffer);
    CHECK(tested.process(left.data(), right.data(), outLeft.data(), outLeft.data(), 64)
          == Status::InvalidBuffer);
    CHECK(tested.process(left.data(), right.data(), outLeft.data(), outLeft.data() + 1, 64)
          == Status::InvalidBuffer);
    CHECK(tested.process(static_cast<const Sample*>(nullptr), right.data(), outLeft.data(),
                         outRight.data(), 64) == Status::InvalidBuffer);
    CHECK(tested.process(left.data(), static_cast<const Sample*>(nullptr), outLeft.data(),
                         outRight.data(), 64) == Status::InvalidBuffer);
    CHECK(tested.process(left.data(), right.data(), static_cast<Sample*>(nullptr),
                         outRight.data(), 64) == Status::InvalidBuffer);
    CHECK(tested.process(left.data(), right.data(), outLeft.data(),
                         static_cast<Sample*>(nullptr), 64) == Status::InvalidBuffer);
    CHECK(left == oldLeft && right == oldRight);
    CHECK(outLeft == oldOutLeft && outRight == oldOutRight);
    CHECK(tested.process(left.data(), right.data(), outLeft.data(), outRight.data(),
                         std::numeric_limits<std::size_t>::max()) == Status::InvalidBuffer);
    Sample excessive{};
    if constexpr (std::is_same<Sample, float>::value) {
        excessive = 1e31F;
    } else {
        excessive = 1e31;
    }
    Sample oldDoubleLimit = excessive;
    if constexpr (std::is_same<Sample, double>::value) {
        oldDoubleLimit = 1e100;
    }
    for (const Sample bad : {std::numeric_limits<Sample>::quiet_NaN(),
                             std::numeric_limits<Sample>::infinity(), excessive, -excessive,
                             oldDoubleLimit, -oldDoubleLimit}) {
        for (const bool badRight : {false, true}) {
            auto invalidLeft = left;
            auto invalidRight = right;
            (badRight ? invalidRight : invalidLeft).back() = bad;
            const auto savedLeft = invalidLeft;
            const auto savedRight = invalidRight;
            CHECK(tested.process(invalidLeft.data(), invalidRight.data(), outLeft.data(),
                                 outRight.data(), invalidLeft.size()) == Status::InvalidSample);
            CHECK(outLeft == oldOutLeft && outRight == oldOutRight);
            CHECK(tested.process(invalidLeft.data(), invalidRight.data(), invalidLeft.data(),
                                 invalidRight.data(), invalidLeft.size()) == Status::InvalidSample);
            CHECK(std::memcmp(invalidLeft.data(), savedLeft.data(), sizeof(invalidLeft)) == 0);
            CHECK(std::memcmp(invalidRight.data(), savedRight.data(), sizeof(invalidRight)) == 0);
        }
    }
    for (const double bad : {-49.01, 49.01, std::numeric_limits<double>::quiet_NaN(),
                             std::numeric_limits<double>::infinity()}) {
        CHECK(tested.setPitchSemitones(bad) == Status::InvalidPitch);
        CHECK(tested.config().pitchSemitones == -7.0);
    }
    near(render(tested, source), render(control, source), 0.0);

    // Boundary acceptance is checked independently of loud-signal quality.
    // The largest float <=1e30 avoids a binary32 rounding-up ambiguity.
    Sample limit{};
    if constexpr (std::is_same<Sample, float>::value) {
        limit = std::nextafter(static_cast<float>(1e30), 0.0F);
    } else {
        limit = 1e30;
    }
    LiveEngine boundary;
    std::array<Sample, 2> accepted{{limit, -limit}};
    std::array<Sample, 2> destinationLeft{};
    std::array<Sample, 2> destinationRight{};
    CHECK(boundary.process(accepted.data(), accepted.data(), destinationLeft.data(),
                           destinationRight.data(), accepted.size()) == Status::Ok);
}

void testPrecisionChangesAtCommonBound() {
    // Delayed state is shared by float/double overloads. A double callback
    // must never admit values which later overflow a float process or flush.
    for (const double pitch : {0.0, -7.0, -49.0, 49.0}) {
        LiveEngine engine({48000.0, pitch});
        const auto firstCount = engine.latencySamples() / 2 + 1;
        const auto middleCount = engine.latencySamples() + 17;
        const auto lastCount = engine.hopSamples() + 1;
        const auto count = firstCount + middleCount + lastCount;
        Stereo<double> source(count);
        source.left[0] = 1e30;
        source.right[0] = -1e30;
        source.left[firstCount - 1] = -9e29;
        source.right[firstCount - 1] = 7e29;
        const float nearLimit = std::nextafter(1e30F, 0.0F);
        source.left[firstCount + 3] = static_cast<double>(nearLimit);
        source.right[firstCount + 3] = -static_cast<double>(nearLimit);
        source.left.back() = -1e30;
        source.right.back() = 1e30;
        Stereo<float> middle(middleCount);
        std::copy_n(source.left.begin() + static_cast<std::ptrdiff_t>(firstCount),
                    middleCount, middle.left.begin());
        std::copy_n(source.right.begin() + static_cast<std::ptrdiff_t>(firstCount),
                    middleCount, middle.right.begin());
        Stereo<double> doubleOutput(count);
        Stereo<float> actual(count + engine.tailSamples());
        CHECK(engine.process(source.left.data(), source.right.data(), doubleOutput.left.data(),
                             doubleOutput.right.data(), firstCount) == Status::Ok);
        std::copy_n(doubleOutput.left.begin(), firstCount, actual.left.begin());
        std::copy_n(doubleOutput.right.begin(), firstCount, actual.right.begin());
        CHECK(engine.process(middle.left.data(), middle.right.data(),
                             actual.left.data() + firstCount, actual.right.data() + firstCount,
                             middleCount) == Status::Ok);
        const auto lastOffset = firstCount + middleCount;
        CHECK(engine.process(source.left.data() + lastOffset, source.right.data() + lastOffset,
                             doubleOutput.left.data() + lastOffset,
                             doubleOutput.right.data() + lastOffset, lastCount) == Status::Ok);
        std::copy_n(doubleOutput.left.begin() + static_cast<std::ptrdiff_t>(lastOffset), lastCount,
                    actual.left.begin() + static_cast<std::ptrdiff_t>(lastOffset));
        std::copy_n(doubleOutput.right.begin() + static_cast<std::ptrdiff_t>(lastOffset), lastCount,
                    actual.right.begin() + static_cast<std::ptrdiff_t>(lastOffset));
        std::size_t written = 0;
        CHECK(engine.flush(actual.left.data() + count, actual.right.data() + count,
                           engine.tailSamples(), written) == Status::Ok);
        CHECK(written == engine.tailSamples());
        for (const auto* channel : {&actual.left, &actual.right}) {
            CHECK(std::all_of(channel->begin(), channel->end(),
                              [](float value) { return std::isfinite(value); }));
        }
        LiveEngine reference({48000.0, pitch});
        near(actual, convert<float>(render(reference, source)), 2e24);
        if (pitch == 0.0) {
            // A large sample must actually emerge during float process, and
            // the final double input must emerge during float flush.
            CHECK(actual.left[engine.latencySamples()] > 9e29F);
            CHECK(actual.left[count - 1 + engine.latencySamples()] < -9e29F);
        }
    }
}

void testFloatParityAndExtremeTargets() {
    const auto source = convert<float>(signal(2401, 44100.0));
    const auto exactInput = convert<double>(source);
    const std::vector<Command> commands{{0, -49.0}, {321, 49.0}, {769, -24.25},
                                        {1107, 24.5}, {1603, 0.0}};
    LiveEngine floatEngine({44100.0, 0.0});
    LiveEngine doubleEngine({44100.0, 0.0});
    const auto actual = render(floatEngine, source, commands);
    const auto precise = render(doubleEngine, exactInput, commands);
    near(actual, convert<float>(precise), 2e-6);
    for (const auto* channel : {&actual.left, &actual.right}) {
        CHECK(std::all_of(channel->begin(), channel->end(),
                          [](float value) { return std::isfinite(value); }));
    }
}

void testLifecycleMovesAndFlush() {
    static_assert(!std::is_copy_constructible<LiveEngine>::value, "live state must not copy");
    static_assert(std::is_nothrow_move_constructible<LiveEngine>::value, "move must not throw");
    static_assert(std::is_nothrow_move_assignable<LiveEngine>::value, "move assignment must not throw");
    LiveEngine engine({48000.0, -7.0});
    CHECK(engine.process(static_cast<const double*>(nullptr), static_cast<const double*>(nullptr),
                         static_cast<double*>(nullptr), static_cast<double*>(nullptr), 0)
          == Status::Ok);
    const auto source = signal(301);
    Stereo<double> prefix(source.left.size());
    CHECK(engine.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), prefix.left.size()) == Status::Ok);
    CHECK(engine.setPitchSemitones(7.0) == Status::Ok);
    CHECK(engine.setPitchSemitones(-7.0) == Status::Ok);
    Stereo<double> tail(engine.tailSamples());
    std::fill(tail.left.begin(), tail.left.end(), -0.75);
    std::fill(tail.right.begin(), tail.right.end(), 0.625);
    const auto sentinel = tail;
    std::size_t written = 123;
    CHECK(engine.flush(tail.left.data(), tail.right.data(), engine.tailSamples() - 1, written)
          == Status::BufferTooSmall);
    CHECK(written == 0);
    near(tail, sentinel, 0.0);
    CHECK(engine.flush(static_cast<double*>(nullptr), tail.right.data(),
                       engine.tailSamples(), written) == Status::InvalidBuffer);
    CHECK(written == 0);
    CHECK(engine.flush(tail.left.data(), tail.left.data(), engine.tailSamples(), written)
          == Status::InvalidBuffer);
    CHECK(written == 0);
    near(tail, sentinel, 0.0);
    CHECK(engine.flush(tail.left.data(), tail.right.data(), engine.tailSamples(), written) == Status::Ok);
    CHECK(written == engine.tailSamples());
    prefix.left.insert(prefix.left.end(), tail.left.begin(), tail.left.end());
    prefix.right.insert(prefix.right.end(), tail.right.begin(), tail.right.end());
    LiveEngine reference({48000.0, -7.0});
    near(prefix, render(reference, source), 0.0);
    written = 123;
    CHECK(engine.flush(static_cast<double*>(nullptr), static_cast<double*>(nullptr), 0, written)
          == Status::Ok);
    CHECK(written == 0);
    CHECK(engine.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), 1) == Status::StreamClosed);
    CHECK(engine.reset() == Status::Ok);
    CHECK(engine.config().pitchSemitones == -7.0);

    LiveEngine activeReference({48000.0, -7.0});
    CHECK(engine.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), 97) == Status::Ok);
    CHECK(activeReference.process(source.left.data(), source.right.data(), prefix.left.data(),
                                  prefix.right.data(), 97) == Status::Ok);
    LiveEngine moved(std::move(engine));
    CHECK(engine.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), 1) == Status::NotPrepared);
    CHECK(engine.reset() == Status::NotPrepared);
    CHECK(engine.setPitchSemitones(0.0) == Status::NotPrepared);
    written = 123;
    CHECK(engine.flush(tail.left.data(), tail.right.data(), tail.left.size(), written)
          == Status::NotPrepared);
    CHECK(written == 0);
    LiveEngine assigned;
    assigned = std::move(moved);
    CHECK(moved.reset() == Status::NotPrepared);
    near(render(assigned, source), render(activeReference, source), 0.0);
    engine = LiveEngine({48000.0, -7.0});
    CHECK(engine.process(source.left.data(), source.right.data(), prefix.left.data(),
                         prefix.right.data(), 97) == Status::Ok);
    CHECK(engine.reset() == Status::Ok);  // Reset interrupts unfinished frame tasks.
    LiveEngine resetReference({48000.0, -7.0});
    near(render(engine, source), render(resetReference, source), 0.0);

    LiveEngine empty;
    Stereo<double> silence(empty.tailSamples());
    CHECK(empty.flush(silence.left.data(), silence.right.data(), empty.tailSamples(), written)
          == Status::Ok);
    CHECK(written == empty.tailSamples());
    CHECK(std::all_of(silence.left.begin(), silence.left.end(), [](double x) { return x == 0.0; }));
    CHECK(std::all_of(silence.right.begin(), silence.right.end(), [](double x) { return x == 0.0; }));
}

void testNoRealtimeAllocations() {
    const auto source = signal(1201);
    Stereo<double> output(source.left.size());
    LiveEngine engine({48000.0, -7.0});
    Stereo<double> tail(engine.tailSamples());
    std::array<Status, 9> statuses{};
    std::size_t written = 0;
    std::size_t allocations = 0;
    {
        allocation_probe::Scope probe;
        statuses[0] = engine.process(source.left.data(), source.right.data(), output.left.data(),
                                     output.right.data(), 97);
        statuses[1] = engine.setPitchSemitones(49.0);
        statuses[2] = engine.process(source.left.data(), source.right.data(), output.left.data(),
                                     output.right.data(), source.left.size());
        statuses[3] = engine.flush(tail.left.data(), tail.right.data(), tail.left.size(), written);
        statuses[4] = engine.reset();
        statuses[5] = engine.setPitchSemitones(-49.0);
        statuses[6] = engine.process(source.left.data(), source.right.data(), output.left.data(),
                                     output.right.data(), source.left.size());
        statuses[7] = engine.setPitchSemitones(0.0);
        statuses[8] = engine.flush(tail.left.data(), tail.right.data(), tail.left.size(), written);
        allocations = allocation_probe::count.load(std::memory_order_relaxed);
    }
    CHECK(allocations == 0);
    CHECK(std::all_of(statuses.begin(), statuses.end(), [](Status status) { return status == Status::Ok; }));
    CHECK(written == engine.tailSamples());
}
}  // namespace

int main() {
    struct Test { const char* name; void (*run)(); };
    const Test tests[] = {
        {"configuration and full consumer range", testConfigurationsAndRange},
        {"unity delay at 44.1/48/96 kHz and all sample phases", testUnityRatesAndSamplePhases},
        {"automation command and callback partition equivalence", testAutomationAndPartitions},
        {"linked stereo invariants and duplicated mono", testStereoInvariants},
        {"sub-hop commands and eventual unity return", testSubHopControlAndUnityReturn},
        {"double in-place and transactional rejection", testInPlaceAndValidation<double>},
        {"float in-place and transactional rejection", testInPlaceAndValidation<float>},
        {"float/double callback changes at common sample bound", testPrecisionChangesAtCommonBound},
        {"float/double parity and extreme live targets", testFloatParityAndExtremeTargets},
        {"lifecycle moves reset and terminal drain", testLifecycleMovesAndFlush},
        {"no realtime allocations including first call", testNoRealtimeAllocations},
    };
    std::size_t failures = 0;
    for (const auto& test : tests) {
        try {
            test.run();
            std::cout << "PASS " << test.name << '\n';
        } catch (const std::exception& error) {
            ++failures;
            std::cerr << "FAIL " << test.name << ": " << error.what() << '\n';
        }
    }
    std::cout << (sizeof(tests) / sizeof(tests[0]) - failures) << '/'
              << sizeof(tests) / sizeof(tests[0]) << " checks passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}

