"""Small, falsifiable mono spectral-transport experiment, not a real-time engine.

NumPy 1.24 compatible. See ENGINE_NOTES.md for equations, timing, and limitations.
No level normalization, file I/O, optional dependencies, or implicit downloads.
"""

import math
from numbers import Integral

import numpy as np


def _integer(name, value, minimum):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError("{} must be an integer >= {}".format(name, minimum))
    return int(value)


def _finite_real(name, value):
    if isinstance(value, (bool, complex, np.complexfloating)):
        raise ValueError("{} must be a finite real number".format(name))
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("{} must be a finite real number".format(name)) from error
    if not math.isfinite(result):
        raise ValueError("{} must be a finite real number".format(name))
    return result


def _pitch(value):
    result = _finite_real("semitones", value)
    if not -12.0 <= result <= 12.0:
        raise ValueError("this experiment supports semitones in [-12, 12]")
    return result


class TransportEngine:
    """Causal, static-ratio, mono research processor with bounded stream state.

    process() accepts finite real one-dimensional samples, returns exactly as
    many float64 samples, and never modifies its argument. Samples larger than
    1e100 in absolute value are rejected to leave numerical headroom. Validate
    whole input blocks before advancing state. Calls are not thread-safe.

    flush() feeds N + (L - 1) + H zeros and closes the stream; these samples
    include the delayed input and any tail due to spectral edits. A subsequent
    flush() is empty. process() then raises until reset(). Pitch changes are
    allowed before the first nonempty process() or after reset(); during an
    active stream only setting the identical semitone value is accepted.
    """

    # Bound memory and work per frame, including dense/noisy spectra. This is a
    # research simplification, not a demonstrated quality-optimal region count.
    _max_regions = 64
    _relative_peak_floor = 1e-4

    def __init__(self, sample_rate=48000, analysis_size=2048,
                 synthesis_size=384, hop=96, semitones=0.0,
                 window="asymmetric"):
        sample_rate = _finite_real("sample_rate", sample_rate)
        if sample_rate <= 0.0:
            raise ValueError("sample_rate must be positive")
        n = _integer("analysis_size", analysis_size, 8)
        length = _integer("synthesis_size", synthesis_size, 8)
        hop = _integer("hop", hop, 1)
        if n % 2 or length % 2 or n < length:
            raise ValueError("analysis/synthesis sizes must be even and N >= L")
        if length % hop or hop > length // 2:
            raise ValueError("hop must divide synthesis_size with >= 2 overlaps")
        if window not in ("asymmetric", "symmetric"):
            raise ValueError("window must be 'asymmetric' or 'symmetric'")
        if window == "symmetric" and n != length:
            raise ValueError("symmetric baseline requires analysis_size == synthesis_size")

        self._sample_rate = sample_rate
        self._analysis_size = n
        self._synthesis_size = length
        self._hop = hop
        self._window = window
        self._semitones = _pitch(semitones)
        self._ratio = 2.0 ** (self._semitones / 12.0)

        index = np.arange(n, dtype=np.float64)
        if window == "asymmetric":
            pivot = n - length // 2
            analysis = np.empty(n, dtype=np.float64)
            analysis[:pivot] = np.sin(np.pi * index[:pivot] / (2.0 * pivot))
            analysis[pivot:] = np.cos(
                np.pi * (index[pivot:] - pivot) / (2.0 * (n - pivot)))
        else:
            analysis = np.sin(np.pi * index / n)
        q = np.arange(length, dtype=np.float64)
        product = (1.0 - np.cos(2.0 * np.pi * q / length)) / (length / hop)
        synthesis = np.zeros(length, dtype=np.float64)
        np.divide(product, analysis[-length:], out=synthesis,
                  where=analysis[-length:] != 0.0)
        self._analysis = analysis
        self._synthesis = synthesis
        self._support_reference = q - (length - 1)
        self._bin_omega = 2.0 * np.pi * np.arange(n // 2 + 1) / n
        self._bin_width = 2.0 * np.pi / n
        self.reset()

    @property
    def sample_rate(self):
        return self._sample_rate

    @property
    def analysis_size(self):
        return self._analysis_size

    @property
    def synthesis_size(self):
        return self._synthesis_size

    @property
    def hop(self):
        return self._hop

    @property
    def window(self):
        return self._window

    @property
    def latency_samples(self):
        """Scheduled delay, not a claim about frequency-dependent settling."""
        return self.synthesis_size - 1

    @property
    def semitones(self):
        return self._semitones

    def set_pitch_semitones(self, value):
        value = _pitch(value)
        if value == self._semitones:
            return
        if self._started or self._closed:
            raise RuntimeError("static-ratio prototype: reset before changing pitch")
        self._semitones = value
        self._ratio = 2.0 ** (value / 12.0)

    def reset(self):
        """Clear history, phase, scheduler, and terminal state; retain config."""
        self._history = np.zeros(self.analysis_size, dtype=np.float64)
        self._output = np.zeros(self.synthesis_size, dtype=np.float64)
        self._previous_spectrum = None
        self._previous_regions = []  # (omega, delta, rotation at frame end)
        self._sample_index = 0
        self._started = False
        self._closed = False

    def process(self, samples):
        if self._closed:
            raise RuntimeError("stream has been flushed; call reset before process")
        source = np.asarray(samples)
        if source.ndim != 1 or source.dtype.kind not in "fiu":
            raise ValueError("samples must be a one-dimensional real numeric array")
        with np.errstate(over="ignore", invalid="ignore"):
            source = source.astype(np.float64, copy=False)
        if not np.all(np.isfinite(source)) or np.any(np.abs(source) > 1e100):
            raise ValueError("samples must be finite with absolute value <= 1e100")
        if source.size:
            self._started = True
        return self._process_validated(source)

    def _process_validated(self, source):
        result = np.empty(source.size, dtype=np.float64)
        n = self.analysis_size
        length = self.synthesis_size
        for offset, value in enumerate(source):
            t = self._sample_index
            self._history[t % n] = value
            if t % self.hop == 0:
                # Frame ends t=0,H,2H,..., including zero-padded startup.
                first = (t + 1) % n
                frame = np.concatenate((self._history[first:], self._history[:first]))
                contribution = self._frame(frame)
                start = t % length
                count = length - start
                self._output[start:] += contribution[:count]
                self._output[:start] += contribution[count:]
            position = t % length
            result[offset] = self._output[position]
            self._output[position] = 0.0
            self._sample_index += 1
        return result

    def flush(self):
        if self._closed:
            return np.empty(0, dtype=np.float64)
        length = self.analysis_size + self.latency_samples + self.hop
        result = self._process_validated(np.zeros(length, dtype=np.float64))
        self._closed = True
        return result

    def _regions(self, spectrum):
        """Estimate peaks; inherit phase on peak motion/splits/merges."""
        magnitude = np.abs(spectrum)
        interior = magnitude[1:-1]
        largest = float(np.max(interior))
        if largest == 0.0:
            return []
        candidate = np.flatnonzero(
            (interior >= magnitude[:-2]) &
            (interior > magnitude[2:]) &
            (interior >= largest * self._relative_peak_floor)) + 1
        if not candidate.size:
            # Low unresolved/DC-dominated lobes can have no interior local max.
            candidate = np.array([1 + int(np.argmax(interior))])
        if candidate.size > self._max_regions:
            loudest = np.argsort(magnitude[candidate])[-self._max_regions:]
            candidate = candidate[loudest]
        candidate = np.sort(candidate)
        result = []
        previous = self._previous_spectrum
        old_regions = self._previous_regions
        for peak in candidate:
            # Log-parabola is only a startup estimate, not an asymmetric-window
            # calibration. Stable same-bin phase differences supersede it.
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
                # More than one child may inherit an old region at a split.
                # A merge inherits its nearest previous peak. This avoids
                # arbitrary resets but is not a complete tracking solution.
                old = min(old_regions, key=lambda item: abs(item[0] - estimate))
                rotation = old[2] + 0.5 * self.hop * (old[1] + delta)
                rotation = (rotation + np.pi) % (2.0 * np.pi) - np.pi
            else:
                rotation = 0.0  # First active frame after zero spectral history.
            result.append((int(peak), float(estimate), float(delta), float(rotation)))
        return result

    def _frame(self, frame):
        spectrum = np.fft.rfft(frame * self._analysis)
        regions = self._regions(spectrum)
        # Unity retains analysis/region lifecycle, but bypasses spectral edits:
        # reconstruction is an independent exact test of the WOLA scheduler.
        if self._ratio == 1.0:
            recent = np.fft.irfft(spectrum, n=self.analysis_size)[-self.synthesis_size:]
        else:
            recent = self._transport(spectrum, regions)
        self._previous_spectrum = spectrum
        self._previous_regions = [(omega, delta, phase)
                                  for _, omega, delta, phase in regions]
        return recent * self._synthesis

    def _transport(self, spectrum, regions):
        n = self.analysis_size
        length = self.synthesis_size
        # DFT bin zero is retained; this does NOT preserve a constant waveform
        # under nonzero shifts. Nyquist has no unique analytic phase direction
        # and is omitted when shifting. End-bin handling is explicit.
        recent = np.full(length, spectrum[0].real / n, dtype=np.float64)
        if not regions:
            return recent
        peaks = [region[0] for region in regions]
        boundaries = [1]
        boundaries.extend((left + right) // 2 + 1
                          for left, right in zip(peaks[:-1], peaks[1:]))
        boundaries.append(n // 2)
        analytic_spectra = np.zeros((len(regions), n), dtype=np.complex128)
        # A two-bin raised-cosine guard reduces abrupt upper-Nyquist crossings.
        # At DC, discard only nonpositive destinations: a two-bin low taper
        # would itself remove much of the required sub-F#1 signal. This is a
        # nominal-bin guard, not a proven rejection specification.
        guard = 2.0 * self._bin_width
        for row, (_, _, delta, _) in enumerate(regions):
            begin, end = boundaries[row:row + 2]
            destination = self._bin_omega[begin:end] + delta
            high = np.clip((np.pi - destination) / guard, 0.0, 1.0)
            taper = (destination > 0.0) * (0.5 - 0.5 * np.cos(np.pi * high))
            analytic_spectra[row, begin:end] = 2.0 * spectrum[begin:end] * taper
        analytic = np.fft.ifft(analytic_spectra, axis=1)[:, -length:]
        delta = np.array([region[2] for region in regions])[:, None]
        phase = np.array([region[3] for region in regions])[:, None]
        modulation = np.exp(1j * (phase + delta * self._support_reference[None, :]))
        recent += np.sum((analytic * modulation).real, axis=0)
        return recent


def render(samples, **config):
    """Return process(samples) plus the documented full terminal tail."""
    engine = TransportEngine(**config)
    return np.concatenate((engine.process(samples), engine.flush()))
