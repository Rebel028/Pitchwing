// Original research probe, 2026-10-08. Source latency API verification, not a quality test.
#include <iostream>
#include "signalsmith-stretch.h"
int main() {
    using Stretch = signalsmith::stretch::SignalsmithStretch<float>;
    for (int fs : {44100, 48000, 96000}) {
        for (int preset=0; preset<3; ++preset) {
            Stretch s(1);
            if (preset==0) s.presetDefault(1, fs);
            if (preset==1) s.presetCheaper(1, fs);
            if (preset==2) s.configure(1, 512, 64, false);
            int latency=s.inputLatency()+s.outputLatency();
            std::cout << "stretch," << fs << ',' << preset << ',' << s.blockSamples()
                      << ',' << s.intervalSamples() << ',' << s.inputLatency() << ','
                      << s.outputLatency() << ',' << 1000.0*latency/fs << '\n';
        }
    }
    for (float asym : {0.0f, 0.5f, 0.75f, 0.9f}) {
        signalsmith::linear::DynamicSTFT<float> stft;
        stft.configure(1, 1, 2048, 0, 128, asym);
        std::cout << "linear-asym," << asym << ',' << stft.analysisOffset() << ','
                  << stft.synthesisOffset() << ',' << stft.analysisLatency() << ','
                  << stft.synthesisLatency() << ',' << 1000.0*stft.latency()/48000 << '\n';
    }
}
