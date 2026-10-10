"""Deterministic native-port reference; the accepted engine.py stays unchanged.

The only DSP changes are canonical bin-1 selection for flat interior magnitudes
and deterministic bin-index tie ordering at the 64-peak cap. See native-core.md.
"""

import numpy as np

if __package__:
    from .engine import TransportEngine
else:
    from engine import TransportEngine


class StableTransportEngine(TransportEngine):
    """TransportEngine with explicit flat-spectrum/peak-cap tie policies."""

    _flat_spectrum_tolerance = 1e-12

    def _regions(self, spectrum):
        magnitude = np.abs(spectrum)
        interior = magnitude[1:-1]
        largest = float(np.max(interior))
        if largest == 0.0:
            return []
        if largest - float(np.min(interior)) <= largest * self._flat_spectrum_tolerance:
            # A lone effective input sample has no frequency-local peak. Make
            # this decision independent of FFT roundoff and plateau argmax.
            candidate = np.array([1], dtype=np.intp)
        else:
            candidate = np.flatnonzero(
                (interior >= magnitude[:-2]) &
                (interior > magnitude[2:]) &
                (interior >= largest * self._relative_peak_floor)) + 1
        if not candidate.size:
            candidate = np.array([1 + int(np.argmax(interior))])
        if candidate.size > self._max_regions:
            # Ascending magnitude, then ascending bin: retain the largest 64,
            # favoring higher bin indices when magnitudes are exactly equal.
            loudest = np.lexsort((candidate, magnitude[candidate]))[-self._max_regions:]
            candidate = candidate[loudest]
        candidate = np.sort(candidate)
        result = []
        previous = self._previous_spectrum
        old_regions = self._previous_regions
        for peak in candidate:
            triplet = np.log(np.maximum(magnitude[peak - 1:peak + 2], 1e-300))
            denominator = triplet[0] - 2.0 * triplet[1] + triplet[2]
            fraction = (0.5 * (triplet[0] - triplet[2]) / denominator
                        if abs(denominator) > 1e-12 else 0.0)
            estimate = self._bin_width * (peak + np.clip(fraction, -0.5, 0.5))
            if previous is not None and abs(previous[peak]) > largest * 1e-6:
                residual = (np.angle(spectrum[peak]) - np.angle(previous[peak])
                            - self._bin_omega[peak] * self.hop)
                residual = (residual + np.pi) % (2.0 * np.pi) - np.pi
                instantaneous = self._bin_omega[peak] + residual / self.hop
                if (0.0 < instantaneous < np.pi and
                        abs(instantaneous - estimate) <= 2.0 * self._bin_width):
                    estimate = instantaneous
            delta = (self._ratio - 1.0) * estimate
            if old_regions:
                old = min(old_regions, key=lambda item: abs(item[0] - estimate))
                rotation = old[2] + 0.5 * self.hop * (old[1] + delta)
                rotation = (rotation + np.pi) % (2.0 * np.pi) - np.pi
            else:
                rotation = 0.0
            result.append((int(peak), float(estimate), float(delta), float(rotation)))
        return result
