// Offline mono render through LiveEngine for diagnostics.
// usage: pitchwing_live_render <in.f64> <out.f64> <rate> <semitones> [block] [control.f64]
// Input/output are raw little-endian float64 mono; output includes the full
// tail, so output length = input length + tailSamples(). An optional control
// file holds one semitone value per input sample; the target is set before
// every block from the block's first control sample (ShiftKey sets it before
// each <=32-sample chunk), overriding <semitones>.
#include <pitchwing/LiveEngine.hpp>

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 5) {
        std::fprintf(stderr, "usage: %s in.f64 out.f64 rate semitones [block]\n", argv[0]);
        return 2;
    }
    const double rate = std::atof(argv[3]);
    const double semitones = std::atof(argv[4]);
    const std::size_t block = argc > 5 ? static_cast<std::size_t>(std::atoi(argv[5])) : 32;
    std::vector<double> input;
    {
        std::FILE* f = std::fopen(argv[1], "rb");
        if (!f) return 3;
        double v;
        while (std::fread(&v, sizeof v, 1, f) == 1) input.push_back(v);
        std::fclose(f);
    }
    std::vector<double> control;
    if (argc > 6) {
        std::FILE* f = std::fopen(argv[6], "rb");
        if (!f) return 3;
        double v;
        while (std::fread(&v, sizeof v, 1, f) == 1) control.push_back(v);
        std::fclose(f);
        if (control.size() < input.size()) {
            std::fprintf(stderr, "control file shorter than input\n");
            return 3;
        }
    }
    pitchwing::LiveEngine engine({rate, control.empty() ? semitones : control[0]});
    std::vector<double> out(input.size() + engine.tailSamples()), scratch(out.size());
    for (std::size_t offset = 0; offset < input.size(); offset += block) {
        const auto n = std::min(block, input.size() - offset);
        if (!control.empty() && engine.setPitchSemitones(control[offset]) != pitchwing::Status::Ok) {
            std::fprintf(stderr, "setPitchSemitones failed at %zu\n", offset);
            return 4;
        }
        if (engine.process(input.data() + offset, input.data() + offset,
                           out.data() + offset, scratch.data() + offset, n) != pitchwing::Status::Ok) {
            std::fprintf(stderr, "process failed at %zu\n", offset);
            return 4;
        }
    }
    std::size_t written = 0;
    if (engine.flush(out.data() + input.size(), scratch.data() + input.size(),
                     engine.tailSamples(), written) != pitchwing::Status::Ok) {
        std::fprintf(stderr, "flush failed\n");
        return 5;
    }
    std::FILE* f = std::fopen(argv[2], "wb");
    if (!f) return 6;
    std::fwrite(out.data(), sizeof(double), out.size(), f);
    std::fclose(f);
    std::fprintf(stderr, "rendered %zu + tail %zu, latency %zu\n", input.size(), written,
                 engine.latencySamples());
    return 0;
}
