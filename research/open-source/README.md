# Public-source latency probe

This folder contains research downloads and a small original C++ probe. For a compact durable research bundle, include only the files listed in `bundle-files.txt`; unrelated reference-source downloads and platform binaries need not be included.

## Build and run

From the `pitch-research` directory:

```sh
g++ -std=c++17 -O2 open-source/latency_probe.cpp -o open-source/latency_probe
./open-source/latency_probe
```

Only a C++17 compiler and the included header files are required. There is no external FFT dependency in this configuration. The probe calls latency APIs; it does not process audio or test perceptual quality.

## Exact dependency snapshots

- `signalsmith-stretch.h`: Signalsmith Stretch 1.3.2, commit `a670068d9aeb64913331d5cc29337b19a457a7df`. Repository: https://github.com/Signalsmith-Audio/signalsmith-stretch . MIT license in `stretch-LICENSE.txt`.
- `signalsmith-linear/stft.h` and `signalsmith-linear/fft.h`: Signalsmith Linear commit `146b26f91b48835d665fa0498d64d9617818d27a`. Repository: https://github.com/Signalsmith-Audio/linear . MIT license in `signalsmith-linear/LICENSE.txt`.

The three exact dependency source files were fetched again at their pinned commit URLs and compared byte-for-byte successfully. Copied include-directory versions are identical to the inspected top-level `linear-*` source downloads. Content hashes are in `source-manifest.json`. No Rubber Band, STN, or stftPitchShift code is compiled or linked into this probe.

## Results CSV columns

The saved `latency-probe-results.csv` is heterogeneous; the first field identifies its schema.

| First field | Remaining fields, in order |
|---|---|
| `stretch` | sample rate Hz; preset ID; block samples; hop samples; input latency samples; output latency samples; total latency milliseconds |
| `linear-asym` | asymmetry value; analysis offset samples; synthesis offset samples; analysis latency samples; synthesis latency samples; total latency milliseconds |

Stretch preset IDs: 0=default; 1=cheaper with its default split-computation flag; 2=custom block 512, hop 64, split computation disabled. Linear-asym rows use sample rate 48000 Hz, block 2048, hop 128. All configurations are mono. Input plus output latency defines the API total at unchanged duration.

The separate `stretch-latency-results.csv` and `linear-asymmetry-results.csv` files repeat the same results with regular headers for convenient analysis. These are API-reported algorithmic delays, not measured audio-interface or host loopback latencies. The asymmetric helper is not a complete pitch shifter.

## Reference-source downloads

Other files in this working folder were used solely for source inspection. The parent report contains findings and direct source URLs. Rubber Band is GPL-2.0-or-later / commercially licensed; the STN repository has no license identified in its tree. These reference source subsets are deliberately omitted from the compact bundle list. Their content hashes remain in the manifest for provenance.
