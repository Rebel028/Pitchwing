"""Ocean reference algorithm, adapted from Nicolas Juillerat's MIT Java source.

Copyright (c) 2018 Nicolas Juillerat. License: LICENSE-OCEAN.txt.
Python adaptation: research prototype, 2026-10-08; NumPy double precision.
Paper: N. Juillerat and B. Hirsbrunner, ICALIP 2010,
"Low Latency Audio Pitch Shifting in the Frequency Domain".

This is a fixed-ratio mono baseline, NOT a production plug-in or a novel engine.
The author explicitly documents residual pure-tone/low-frequency modulation.
"""
from __future__ import annotations

import numpy as np


class Ocean:
    """Fixed-hop Ocean processor; intrinsic block-index delay = N-H samples.

    One call consumes H samples and returns H samples. A plug-in wrapper may
    introduce additional buffering; this object makes no VST latency claim.
    Pitch changes require a new instance: ratio-history demodulation is absent.
    """

    def __init__(self, ratio=1.0, n=512, hop=64, pad=2):
        if n < 8 or n & (n - 1) or hop <= 0 or n % hop or n // hop < 2:
            raise ValueError("N must be a power of two and hop must divide N; O>=2")
        if pad < 1 or int(pad) != pad or not 0.5 <= ratio <= 2.0:
            raise ValueError("integer pad>=1 and ratio in [0.5,2] required")
        self.n, self.hop, self.pad = n, hop, int(pad)
        self.ratio = float(ratio)
        self.overlap = n // hop
        self.cycle = self.overlap * self.pad
        self.frame = -(self.overlap - 1)
        self.window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)
        self.input = np.zeros(n)
        self.ola = np.zeros(n)
        src = np.arange(1, n // 2 + 1)
        dst = np.floor(src * self.pad * self.ratio + 0.5).astype(int)
        valid = (dst > 0) & (dst < n * self.pad // 2 + 1)
        self.src, self.dst = src[valid], dst[valid]
        delta = self.dst - self.src * self.pad
        # NumPy forward FFT uses exp(-i*w*t); positive phase compensation
        # ensures each moved bin advances with the destination frequency.
        # This is the sign adaptation discussed in reference fixSpectrum().
        self.phase = np.exp(2j * np.pi * np.arange(self.cycle)[:, None]
                            * delta[None, :] / self.cycle)
        self.demod = np.empty((self.cycle, hop))
        self.minimum_demod_denominator = float("inf")
        for p in range(self.cycle):
            denominator = np.zeros(hop)
            for k in range(self.overlap):
                offset = k * hop + np.arange(hop)
                denominator += self.modified_window(offset, p - k) * self.window[offset]
            self.minimum_demod_denominator = min(
                self.minimum_demod_denominator, float(denominator.min()))
            self.demod[p] = 1 / np.maximum(denominator, 0.1)

    @property
    def latency_samples(self):
        return self.n - self.hop

    def modified_window(self, indices, frame):
        padded_ratio = self.ratio * self.pad
        low = int(padded_ratio)
        amount = padded_ratio - low

        def integer_window(integer_ratio):
            shift = (self.n * (frame % self.cycle)
                     * ((integer_ratio - self.pad) % self.cycle)) // self.cycle
            offsets = (indices * integer_ratio // self.pad + shift) % self.n
            return self.window[offsets]

        return (1 - amount) * integer_window(low) + amount * integer_window(low + 1)

    def process(self, samples):
        samples = np.asarray(samples, dtype=float)
        if samples.shape != (self.hop,):
            raise ValueError(f"exactly {self.hop} mono samples required")
        self.input[:-self.hop] = self.input[self.hop:]
        self.input[-self.hop:] = samples
        spectrum = np.fft.rfft(self.input * self.window)
        output = np.zeros(self.n * self.pad // 2 + 1, dtype=complex)
        output[0] = spectrum[0]
        np.add.at(output, self.dst, spectrum[self.src] * self.phase[self.frame % self.cycle])
        # NumPy inverse scales by 1/(mN): multiply by m to preserve reference
        # scaling when only synthesis is zero-padded. Keep FIRST N samples.
        block = np.fft.irfft(output, n=self.n * self.pad)[:self.n] * self.pad
        self.ola += block * self.window
        result = self.ola[:self.hop].copy() * self.demod[self.frame % self.cycle]
        self.ola[:-self.hop] = self.ola[self.hop:]
        self.ola[-self.hop:] = 0
        self.frame += 1
        return result


def render(samples, ratio=1.0, n=512, hop=64, pad=2):
    """Render complete input plus drain; no latency trimming or normalization."""
    engine = Ocean(ratio, n, hop, pad)
    samples = np.asarray(samples, dtype=float)
    padded_length = ((len(samples) + n + hop - 1) // hop) * hop
    padded = np.pad(samples, (0, padded_length - len(samples)))
    output = np.concatenate([engine.process(padded[i:i+hop])
                             for i in range(0, padded_length, hop)])
    return output, engine
