// Matched-delay baseline: offline mono render through Signalsmith Stretch (MIT, research/open-source).
// Same CLI contract as tools/pitchwing_live_render.cpp so experiments/transport/evaluate.py --native can drive it:
//   stretch_render <in.f64> <out.f64> <rate> <semitones> [block] [preset]
// Raw little-endian float64 mono in/out; output = input length + tail (block + hop samples).
// preset (6th arg or STRETCH_PRESET env, default "a"): a = 10 ms block / 2 ms hop (480/96 at 48 kHz, 441/88 at 44.1 kHz),
// b = 32/3 ms block / 4/3 ms hop (512/64 at 48 kHz, 470/59 at 44.1 kHz), d = Stretch's own 120 ms / 30 ms default
// (harness sanity reference only, not a matched-delay case). Tonality limit 0 = strict uniform transposition.
#include "signalsmith-stretch.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 5) {
        std::fprintf(stderr, "usage: %s in.f64 out.f64 rate semitones [block] [preset a|b|d]\n", argv[0]);
        return 2;
    }
    const double rate = std::atof(argv[3]);
    const double semitones = std::atof(argv[4]);
    const std::size_t block = argc > 5 ? static_cast<std::size_t>(std::atoi(argv[5])) : 32;
    const char* presetEnv = std::getenv("STRETCH_PRESET");
    const char preset = argc > 6 ? argv[6][0] : (presetEnv && *presetEnv ? presetEnv[0] : 'a');
    int stftBlock, stftHop;
    if (preset == 'a') { stftBlock = int(rate / 100 + 0.5); stftHop = int(rate / 500 + 0.5); }
    else if (preset == 'b') { stftBlock = int(rate * 32 / 3000 + 0.5); stftHop = int(rate * 4 / 3000 + 0.5); }
    else if (preset == 'd') { stftBlock = int(rate * 0.12); stftHop = int(rate * 0.03); }
    else { std::fprintf(stderr, "unknown preset %c\n", preset); return 2; }

    std::vector<double> input;
    {
        std::FILE* f = std::fopen(argv[1], "rb");
        if (!f) return 3;
        double v;
        while (std::fread(&v, sizeof v, 1, f) == 1) input.push_back(v);
        std::fclose(f);
    }
    signalsmith::stretch::SignalsmithStretch<float> stretch(1);  // fixed seed: reproducible noise-filling
    stretch.configure(1, stftBlock, stftHop, false);
    stretch.setTransposeSemitones(static_cast<float>(semitones), 0);
    const int latency = stretch.inputLatency() + stretch.outputLatency();
    const std::size_t tail = static_cast<std::size_t>(stftBlock + stftHop);

    std::vector<float> in(input.begin(), input.end()), out(input.size() + tail, 0.0f);
    for (std::size_t offset = 0; offset < input.size(); offset += block) {
        const int n = static_cast<int>(std::min(block, input.size() - offset));
        float* inPtr[1] = {in.data() + offset};
        float* outPtr[1] = {out.data() + offset};
        stretch.process(inPtr, n, outPtr, n);
    }
    float* tailPtr[1] = {out.data() + input.size()};
    stretch.flush(tailPtr, static_cast<int>(tail));

    std::vector<double> result(out.begin(), out.end());
    std::FILE* f = std::fopen(argv[2], "wb");
    if (!f) return 6;
    std::fwrite(result.data(), sizeof(double), result.size(), f);
    std::fclose(f);
    std::fprintf(stderr, "stretch preset %c block %d hop %d rendered %zu + tail %zu, latency %d\n",
                 preset, stftBlock, stftHop, input.size(), tail, latency);
    return 0;
}
