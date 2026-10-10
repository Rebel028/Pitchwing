// Deterministic contract checks for a faithful port of the research baseline.
// Passing these does not repair the documented low-dyad/DC quality failures.
// Tests are in memory, require no packages, and create no files. The parent
// workflow runs builds under /tmp to avoid build I/O on the mounted checkout.
#include "pitchwing/Engine.hpp"

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
using pitchwing::Engine;
using pitchwing::EngineConfig;
using pitchwing::Status;
using pitchwing::Window;
constexpr double pi = 3.141592653589793238462643383279502884;

void require(bool condition, const char* expression, int line) {
    if (!condition) {
        throw std::runtime_error(std::string("line ") + std::to_string(line)
                                 + ": " + expression);
    }
}
#define CHECK(expression) require(static_cast<bool>(expression), #expression, __LINE__)

EngineConfig configuration(Window window, double pitch = 0.0) {
    EngineConfig config;
    config.window = window;
    config.analysisSize = window == Window::Symmetric ? 384 : 2048;
    config.pitchSemitones = pitch;
    return config;
}

std::vector<double> signal(std::size_t count, double sampleRate = 48000.0) {
    std::vector<double> samples(count);
    std::uint32_t state = 20261008;
    for (std::size_t i = 0; i < count; ++i) {
        state = 1664525U * state + 1013904223U;
        const double noise = static_cast<double>(state) / 4294967296.0 - 0.5;
        const double time = static_cast<double>(i) / sampleRate;
        samples[i] = 0.03 * noise + 0.125
            + 0.21 * std::sin(2.0 * pi * 30.867706 * time)
            + 0.09 * std::sin(2.0 * pi * 750.0 * time);
    }
    return samples;
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
std::vector<Sample> render(Engine& engine, const std::vector<Sample>& samples,
                           const std::vector<std::size_t>& blocks = {127, 1, 32, 96, 17}) {
    std::vector<Sample> result(samples.size() + engine.tailSamples());
    std::size_t offset = 0;
    std::size_t blockIndex = 0;
    while (offset < samples.size()) {
        const std::size_t count = std::min(blocks[blockIndex % blocks.size()],
                                           samples.size() - offset);
        CHECK(count > 0);
        CHECK(engine.process(samples.data() + offset, result.data() + offset, count)
              == Status::Ok);
        offset += count;
        ++blockIndex;
    }
    std::size_t written = 0;
    CHECK(engine.flush(result.data() + offset, engine.tailSamples(), written) == Status::Ok);
    CHECK(written == engine.tailSamples());
    return result;
}

void testUnityAllHopPhases() {
    const auto body = signal(1301);
    for (const Window window : {Window::Asymmetric, Window::Symmetric}) {
        Engine engine(configuration(window));
        CHECK(engine.latencySamples() == 383);
        CHECK(engine.tailSamples() == engine.config().analysisSize + 383 + 96);
        // A nonzero final sample also verifies drain at every ending hop phase.
        // DC, noise and a B0 sine exercise reconstruction beyond sparse impulses.
        for (std::size_t phase = 0; phase < 96; ++phase) {
            CHECK(engine.reset() == Status::Ok);
            std::vector<double> samples(phase + body.size(), 0.0);
            std::copy(body.begin(), body.end(), samples.begin() + phase);
            samples[phase] += 1.0;
            const auto original = samples;
            const auto output = render(engine, samples);
            std::vector<double> expected(output.size(), 0.0);
            std::copy(samples.begin(), samples.end(), expected.begin() + 383);
            near(output, expected, 2e-11);
            CHECK(samples == original);

            CHECK(engine.reset() == Status::Ok);
            std::vector<double> impulse(192, 0.0);
            impulse[phase] = 1.0;
            const auto response = render(engine, impulse, {1, 31, 64});
            std::vector<double> expectedImpulse(response.size(), 0.0);
            expectedImpulse[phase + 383] = 1.0;
            near(response, expectedImpulse, 2e-11);
        }
    }
}

void testBlockIndependenceAndReset() {
    const auto samples = signal(8193);
    for (const Window window : {Window::Asymmetric, Window::Symmetric}) {
        Engine whole(configuration(window, -7.0));
        Engine divided(configuration(window, -7.0));
        const auto expected = render(whole, samples, {samples.size()});
        const auto actual = render(divided, samples, {1, 17, 128, 95, 32});
        near(actual, expected, 0.0);
        CHECK(divided.reset() == Status::Ok);
        near(render(divided, samples), expected, 0.0);

        // Reset must discard pending output even before a stream is flushed.
        Engine interrupted(configuration(window, -7.0));
        std::array<double, 129> unused{};
        CHECK(interrupted.process(samples.data(), unused.data(), unused.size()) == Status::Ok);
        CHECK(interrupted.reset() == Status::Ok);
        near(render(interrupted, samples), expected, 0.0);
    }
}

template <class Sample>
void inPlaceAndRejection() {
    const auto sourceDouble = signal(4099);
    const std::vector<Sample> source(sourceDouble.begin(), sourceDouble.end());
    for (const Window window : {Window::Asymmetric, Window::Symmetric}) {
        const auto config = configuration(window, -2.0);
        Engine reference(config);
        const auto expected = render(reference, source);
        Engine inPlace(config);
        auto storage = source;
        CHECK(inPlace.process(storage.data(), storage.data(), storage.size()) == Status::Ok);
        const std::size_t inputCount = storage.size();
        storage.resize(inputCount + inPlace.tailSamples());
        std::size_t written = 0;
        CHECK(inPlace.flush(storage.data() + inputCount, inPlace.tailSamples(), written)
              == Status::Ok);
        CHECK(written == inPlace.tailSamples());
        near(storage, expected, 0.0);

        Engine tested(config);
        Engine control(config);
        std::array<Sample, 129> activeOutput{};
        std::array<Sample, 129> controlOutput{};
        CHECK(tested.process(source.data(), activeOutput.data(), activeOutput.size()) == Status::Ok);
        CHECK(control.process(source.data(), controlOutput.data(), controlOutput.size()) == Status::Ok);
        std::array<Sample, 65> overlap{};
        std::copy_n(source.begin(), overlap.size(), overlap.begin());
        const auto originalOverlap = overlap;
        CHECK(tested.process(overlap.data(), overlap.data() + 1, 64) == Status::InvalidBuffer);
        CHECK(overlap == originalOverlap);
        CHECK(tested.process(overlap.data() + 1, overlap.data(), 64) == Status::InvalidBuffer);
        CHECK(overlap == originalOverlap);

        std::array<Sample, 64> destination{};
        destination.fill(static_cast<Sample>(-0.875));
        const auto originalDestination = destination;
        CHECK(tested.process(nullptr, destination.data(), destination.size()) == Status::InvalidBuffer);
        CHECK(destination == originalDestination);
        CHECK(tested.process(source.data(), static_cast<Sample*>(nullptr), destination.size())
              == Status::InvalidBuffer);
        for (const Sample bad : {std::numeric_limits<Sample>::quiet_NaN(),
                                  std::numeric_limits<Sample>::infinity()}) {
            std::array<Sample, 64> invalid{};
            std::copy_n(source.begin(), invalid.size(), invalid.begin());
            invalid.back() = bad;  // Last element catches partial-block mutation.
            const auto originalInvalid = invalid;
            CHECK(tested.process(invalid.data(), destination.data(), invalid.size())
                  == Status::InvalidSample);
            CHECK(destination == originalDestination);
            CHECK(tested.process(invalid.data(), invalid.data(), invalid.size()) == Status::InvalidSample);
            CHECK(std::memcmp(invalid.data(), originalInvalid.data(), sizeof(invalid)) == 0);
        }
        if constexpr (std::is_same<Sample, double>::value) {
            std::array<double, 64> tooLarge{};
            tooLarge.back() = 1e101;
            CHECK(tested.process(tooLarge.data(), destination.data(), tooLarge.size())
                  == Status::InvalidSample);
            CHECK(destination == originalDestination);
        }
        // Both engines have consumed the same valid prefix, despite rejections.
        near(render(tested, source), render(control, source), 0.0);
    }
}

void testStaticPitchAndFlushLifecycle() {
    Engine engine;
    CHECK(engine.process(static_cast<const double*>(nullptr), static_cast<double*>(nullptr), 0)
          == Status::Ok);
    for (const double bad : {std::numeric_limits<double>::quiet_NaN(),
                             std::numeric_limits<double>::infinity(), -13.0, 13.0}) {
        CHECK(engine.setPitchSemitones(bad) == Status::InvalidPitch);
        CHECK(engine.config().pitchSemitones == 0.0);
    }
    CHECK(engine.setPitchSemitones(7.0) == Status::Ok);
    auto copiedConfig = engine.config();
    copiedConfig.hop = 0;
    CHECK(copiedConfig.hop == 0);
    CHECK(engine.config().hop == 96);  // Configuration returned by value.
    const auto source = signal(207);
    std::vector<double> prefix(source.size());
    CHECK(engine.process(source.data(), prefix.data(), source.size()) == Status::Ok);
    CHECK(engine.setPitchSemitones(7.0) == Status::Ok);
    CHECK(engine.setPitchSemitones(-7.0) == Status::PitchLocked);
    CHECK(engine.config().pitchSemitones == 7.0);

    std::vector<double> tail(engine.tailSamples(), -0.75);
    const auto sentinel = tail;
    std::size_t written = 123;
    CHECK(engine.flush(tail.data(), tail.size() - 1, written) == Status::BufferTooSmall);
    CHECK(written == 0);
    CHECK(tail == sentinel);
    written = 123;
    CHECK(engine.flush(static_cast<double*>(nullptr), tail.size(), written) == Status::InvalidBuffer);
    CHECK(written == 0);
    CHECK(engine.flush(tail.data(), tail.size(), written) == Status::Ok);
    CHECK(written == engine.tailSamples());

    Engine reference(configuration(Window::Asymmetric, 7.0));
    auto expected = render(reference, source);
    prefix.insert(prefix.end(), tail.begin(), tail.end());
    near(prefix, expected, 0.0);  // Failed flushes have not advanced history.
    written = 123;
    CHECK(engine.flush(static_cast<double*>(nullptr), 0, written) == Status::Ok);
    CHECK(written == 0);
    std::array<double, 1> next{{0.25}};
    std::array<double, 1> output{{-0.75}};
    CHECK(engine.process(next.data(), output.data(), 1) == Status::StreamClosed);
    CHECK(output[0] == -0.75);
    CHECK(engine.setPitchSemitones(-7.0) == Status::PitchLocked);
    CHECK(engine.reset() == Status::Ok);
    CHECK(engine.setPitchSemitones(-7.0) == Status::Ok);
    Engine resetReference(configuration(Window::Asymmetric, -7.0));
    near(render(engine, source), render(resetReference, source), 0.0);

    Engine empty;
    std::vector<double> emptyTail(empty.tailSamples(), 1.0);
    CHECK(empty.flush(emptyTail.data(), emptyTail.size(), written) == Status::Ok);
    CHECK(written == empty.tailSamples());
    CHECK(std::all_of(emptyTail.begin(), emptyTail.end(), [](double value) { return value == 0.0; }));
}

void testFloatDoubleParityAndOriginalRate() {
    const auto generated = signal(8193, 44100.0);
    const std::vector<float> floats(generated.begin(), generated.end());
    // Quantize both inputs identically. This isolates the float-output cast
    // from peak/tracker changes caused by feeding different input samples.
    const std::vector<double> doubles(floats.begin(), floats.end());
    for (const Window window : {Window::Asymmetric, Window::Symmetric}) {
        for (const double pitch : {0.0, -2.0, -7.0}) {
            auto config = configuration(window, pitch);
            config.sampleRate = 44100.0;
            Engine floatEngine(config);
            Engine doubleEngine(config);
            CHECK(floatEngine.latencySamples() == 383);
            const auto actual = render(floatEngine, floats);
            const auto fullPrecision = render(doubleEngine, doubles);
            const std::vector<float> expected(fullPrecision.begin(), fullPrecision.end());
            near(actual, expected, 2e-7);
            if (pitch == 0.0) {
                std::vector<double> identity(fullPrecision.size(), 0.0);
                std::copy(doubles.begin(), doubles.end(), identity.begin() + 383);
                near(fullPrecision, identity, 2e-11);
            }
        }
    }
}

void testMovesAndMovedFromState() {
    static_assert(!std::is_copy_constructible<Engine>::value, "engine state must not copy implicitly");
    static_assert(std::is_nothrow_move_constructible<Engine>::value, "move must not throw");
    static_assert(std::is_nothrow_move_assignable<Engine>::value, "move assignment must not throw");
    const auto config = configuration(Window::Asymmetric, -7.0);
    Engine original(config);
    Engine control(config);
    const auto samples = signal(1027);
    std::array<double, 129> beforeMove{};
    std::array<double, 129> controlPrefix{};
    CHECK(original.process(samples.data(), beforeMove.data(), beforeMove.size()) == Status::Ok);
    CHECK(control.process(samples.data(), controlPrefix.data(), controlPrefix.size()) == Status::Ok);
    Engine moved(std::move(original));
    std::size_t written = 42;
    CHECK(original.process(samples.data(), beforeMove.data(), 1) == Status::NotPrepared);
    CHECK(original.reset() == Status::NotPrepared);
    CHECK(original.setPitchSemitones(0.0) == Status::NotPrepared);
    CHECK(original.flush(beforeMove.data(), beforeMove.size(), written) == Status::NotPrepared);
    CHECK(written == 0);
    Engine assigned;
    assigned = std::move(moved);
    CHECK(moved.reset() == Status::NotPrepared);
    near(render(assigned, samples), render(control, samples), 0.0);
    // Move assignment can give a moved-from object a prepared engine again.
    original = Engine(config);
    CHECK(original.reset() == Status::Ok);
}

void testNoAllocationsAfterPreparation() {
    // Include the first callback: preparation, not a warm-up process call, is
    // responsible for allocating FFT plans, peak storage and scratch buffers.
    // All test data/results are allocated before the measured region.
    const auto input = signal(4099);
    std::vector<double> output(input.size());
    for (const Window window : {Window::Asymmetric, Window::Symmetric}) {
        Engine engine(configuration(window, -7.0));
        std::vector<double> tail(engine.tailSamples());
        std::array<Status, 7> statuses{};
        std::size_t written = 0;
        std::size_t allocations = 0;
        {
            allocation_probe::Scope scope;
            statuses[0] = engine.process(input.data(), output.data(), input.size());
            statuses[1] = engine.setPitchSemitones(-7.0);
            statuses[2] = engine.flush(tail.data(), tail.size(), written);
            statuses[3] = engine.reset();
            statuses[4] = engine.setPitchSemitones(7.0);
            statuses[5] = engine.process(input.data(), output.data(), input.size());
            statuses[6] = engine.flush(tail.data(), tail.size(), written);
            allocations = allocation_probe::count.load(std::memory_order_relaxed);
        }
        CHECK(allocations == 0);
        CHECK(std::all_of(statuses.begin(), statuses.end(), [](Status status) { return status == Status::Ok; }));
        CHECK(written == engine.tailSamples());
    }
}

void testInvalidConfigurations() {
    const auto rejects = [](const EngineConfig& config) {
        try {
            Engine engine(config);
        } catch (const std::invalid_argument&) {
            return true;
        }
        return false;
    };
    EngineConfig config;
    config.sampleRate = 0.0;
    CHECK(rejects(config));
    config = EngineConfig{};
    config.hop = 0;
    CHECK(rejects(config));
    config.hop = 95;
    CHECK(rejects(config));
    config = EngineConfig{};
    config.analysisSize = 128;
    CHECK(rejects(config));
    config = EngineConfig{};
    config.window = Window::Symmetric;
    CHECK(rejects(config));
    config = EngineConfig{};
    config.pitchSemitones = 13.0;
    CHECK(rejects(config));
    config.pitchSemitones = std::numeric_limits<double>::quiet_NaN();
    CHECK(rejects(config));
    config = EngineConfig{};
    config.window = static_cast<Window>(-1);
    CHECK(rejects(config));
    config = EngineConfig{};
    config.analysisSize = std::numeric_limits<std::size_t>::max() - 1;
    // An even but enormous N must fail validation before allocation/planning.
    CHECK(rejects(config));
}
}  // namespace

int main() {
    struct Test { const char* name; void (*run)(); };
    const Test tests[] = {
        {"unity at every hop phase (both windows)", testUnityAllHopPhases},
        {"block independence and reset", testBlockIndependenceAndReset},
        {"double in-place and rejected buffers", inPlaceAndRejection<double>},
        {"float in-place and rejected buffers", inPlaceAndRejection<float>},
        {"static pitch and flush lifecycle", testStaticPitchAndFlushLifecycle},
        {"float/double parity at 44.1 kHz", testFloatDoubleParityAndOriginalRate},
        {"moves and moved-from state", testMovesAndMovedFromState},
        {"no allocations after preparation", testNoAllocationsAfterPreparation},
        {"invalid configurations", testInvalidConfigurations},
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
