package ch.tachyon.sonics.ocean;

import java.util.*;

import ch.tachyon.sonics.ocean.fft.BooFFT;
import ch.tachyon.sonics.ocean.fft.Cmplx;
import ch.tachyon.sonics.ocean.fft.UnityRoots;
import ch.tachyon.sonics.ocean.fft.Windows;
import ch.tachyon.tunnel.common.*;
import ch.tachyon.tunnel.plugin.*;
import ch.tachyon.tunnel.plugin.opt.callback.*;
import ch.tachyon.tunnel.plugin.opt.doc.*;
import ch.tachyon.tunnel.plugin.opt.spec.*;
import ch.tachyon.tunnel.plugin.param.*;

/**
 * Ocean Pitch Shifting algorithm.
 * <p>
 * Based on the following scientific paper:
 * N. Juillerat, B. Hirsbrunner, "Low Latency Audio Pitch Shifting in the Frequency Domain",
 * IEEE International Conference on Audio, Language and Image Processing, ICALIP 2010, 2010.
 * <p>
 * This implementation is for mono audio signals. To process stereo audio signals, create two instances
 * (one per channel). You should NOT use the same instance for multiple channels.
 * MIT License. See LICENSE.txt
 * @author Nicolas Juillerat
 */
@Category("Pitch")
@Name("Pitch Shift Ocean")
@Description("Change the pitch without affecting the tempo\nUsing the 'Ocean' algorithm")
public class PitchShiftOcean implements ISimpleEffect, IFixedChunkLength, IStartStop, ILatency {

    private double pitchShiftRatio;
    private int logBlockSize; // log2 of block size
    private int logOverlap; // log2 of overlap
    private int logZeroPad; // log2 of zero padding

    private int blockSize; // 'N' in the paper
    private int overlap; // 'O' in the paper
    private int hopSize; // size of input and output audio chunks, N/O
    private int zeroPad; // 'm' in the paper
    private int nbInputBins; // Number of spectral bins, input
    private int nbOutputBins; // Number of spectral bins, output

    private long processHopIndex; // Running index of processed STFT frames since the beginning
    private long outputHopIndex; // Running index of synthesized STFT frames since the beginning
    private boolean overflowWarned;

    private float[] inputBlock;
    private float[] windowedInputBlock;
    private float[] analysisWindow;
    private float[] synthesisWindow;
    private BooFFT forwFft;
    private Cmplx[] inputSpectrum;
    private Cmplx[] unityRoots;
    private Cmplx[] outputSpectrum;
    private BooFFT backFft;
    private float[] outputBlock;
    private float[] overlapAddBuffer;


    @Description("Pitch Shifting ratio\n"
            + "Values > 1 raise the pitch\n"
            + "Values < 1 lower the pitch")
    @Scale(ScaleType.LOGARITHMIC)
    @Range(minValue=0.5, maxValue=2.0, defaultValue=1.0)
    @Order(1)
    public double getPitchShiftRatio() {
        return pitchShiftRatio;
    }

    public void setPitchShiftRatio(double pitchShiftRatio) {
        this.pitchShiftRatio = pitchShiftRatio;
    }

    @Name("Block Size")
    @Description("Size of the Fourier transforms\n"
            + "Higher values result in better overal quality, but higher latency and slightly slower processing")
    @Transform(PowerOfTwoTransform.class)
    @Range(minValue=9, maxValue=13, defaultValue=11)
    @Order(2)
    public int getLogBlockSize() {
        return logBlockSize;
    }

    public void setLogBlockSize(int logBlockSize) {
        this.logBlockSize = logBlockSize;
    }

    @Name("Overlap")
    @Description("Overlapping factor. 2=50%, 4=75%, etc.\n"
            + "Higher values result in better overal quality, but slower processing (and slightly higher latency)")
    @Transform(PowerOfTwoTransform.class)
    @Range(minValue=1, maxValue=4, defaultValue=2)
    @Order(3)
    public int getLogOverlap() {
        return logOverlap;
    }

    public void setLogOverlap(int logOverlap) {
        this.logOverlap = logOverlap;
    }

    @Name("Zero Padding")
    @Description("Zero padding. 1=none\n"
            + "Higher values result in better frequency accuracy, but slower processing\n"
            + "Leave to minimum if overlap is 2")
    @Transform(PowerOfTwoTransform.class)
    @Range(minValue=0, maxValue=3, defaultValue=1)
    @Order(4)
    public int getLogZeroPad() {
        // Note: for an unknown reason, zeroPad > 1 does not work well when overlap == 2
        return logZeroPad;
    }

    public void setLogZeroPad(int logZeroPad) {
        this.logZeroPad = logZeroPad;
    }

    /**
     * Prepare for processing. Must be invoked once before one or more calls to {@link #process(float[])}.
     * Must be invoked after all parameters such as {@link #setPitchShiftRatio(double)}, {@link #setLogBlockSize(int)}, etc
     * have been set.
     */
    @Override
    public void startProcessing(IProcessingInfo unused) {
        blockSize = (1 << logBlockSize); // FFT size
        overlap = (1 << logOverlap); // overlap. 2 = 50%, 4 = 75%, etc
        hopSize = blockSize / overlap; // Size of the input and output audio blocks
        zeroPad = (1 << logZeroPad); // Zero padding (synthesis only). The 'm' of the paper
        nbInputBins = blockSize / 2 + 1;
        nbOutputBins = (blockSize * zeroPad) / 2 + 1;

        /*
         * Running index of the STFT frame being processed (in the frequency domain) since the beginning.
         * Because we need to accumulate (overlap - 1) input hops before the first hop actually gets
         * at the begining of the FFT'ed block, we have a latency of (overlap - 1) hops and hence start with a
         * corresponding negative value:
         */
        processHopIndex = -(overlap - 1);
        /*
         * Running index of the STFT frame being synthesized since the begining
         *
         * WARNING: this value of 'processHopIndex' assumes that the first 'hopSize' samples of the spectrum that is
         * back-FFT'ed will be included in the output, without any additional delay. This is the case
         * with this implementation.
         *
         * However, many implementations of the STFT will enqueue the last back-FFT'ed spectrum
         * samples and its first 'hopSize' samples will only be output at the next round. In such a case
         * there would be a "synthesis latency" of one hop, and you would initialize outputHopIndex
         * to 'processHopIndex - 1' instead of 'processHopIndex'.
         */
        outputHopIndex = processHopIndex;
        overflowWarned = false;

        inputBlock = new float[blockSize];
        windowedInputBlock = new float[blockSize];
        analysisWindow = new float[blockSize];
        Windows.fillHannWindow(analysisWindow);
        synthesisWindow = analysisWindow;
        forwFft = new BooFFT(blockSize / 2); // Argument is size in complex numbers (hence half our size in real numbers)
        if (zeroPad == 1)
            backFft = forwFft;
        else
            backFft = new BooFFT(blockSize * zeroPad / 2); // Zero padding is only used for synthesis
        int cycleLength = overlap * zeroPad;
        unityRoots = UnityRoots.getInstance().getRoots(cycleLength, cycleLength); // e^(ik2π/mO) for k = 0, 1, ..., mO - 1
        inputSpectrum = Cmplx.newArray(nbInputBins);
        outputSpectrum = Cmplx.newArray(nbOutputBins);
        outputBlock = new float[blockSize * zeroPad];
        overlapAddBuffer = new float[blockSize - hopSize];
    }

    /**
     * The size of the audio chunks that must be passed to the {@link #process(float[])} method
     */
    @Override
    public int getFixedChunkLength() {
        return hopSize;
    }

    /**
     * The processing latency, in samples
     */
    @Override
    public int getLatency(IoDirection ioDirection) {
        /*
         * We return 0 so that you can actually see the added latency in the resulting file...
         * After all, the Ocean algorithm is about low latency.
         *
         * If you want zero-latency processing, comment out the "return 0;" line and uncomment the
         * next "return" line. Latency will then be properly compensated.
         */
        return 0;

        // This is the expected latency:
//        return blockSize - hopSize;
    }

    /**
     * Process the next audio chunk.
     * <p>
     * The size of the given array must exactly match {@link #getFixedChunkLength()}.
     * If this is the last audio chunk, it must be padded with zeroes as needed.
     */
    @Override
    public void process(float[] data) {
        if (data.length != getFixedChunkLength())
            throw new IllegalArgumentException();

        { // Split into overlapped blocks
            // Shift previous block
            System.arraycopy(inputBlock, hopSize, inputBlock, 0, blockSize - hopSize);
            // Append new hop
            System.arraycopy(data, 0, inputBlock, blockSize - hopSize, hopSize);
        }
        // Apply analysis window
        for (int i = 0; i < blockSize; i++)
            windowedInputBlock[i] = inputBlock[i] * analysisWindow[i];
        // Forward FFT
        forwFft.forwR2C(windowedInputBlock, inputSpectrum);

        fixSpectrum(inputSpectrum);

        // Pitch Shift the spectrum
        processSpectrum(inputSpectrum, outputSpectrum);

        fixSpectrum(outputSpectrum);

        // Backward FFT
        backFft.backC2R(outputSpectrum, outputBlock);
        // Apply synthesis window
        for (int i = 0; i < blockSize; i++)
            outputBlock[i] *= synthesisWindow[i];
        /*
         * outputBlock[blockSize] to outputBlock[blockSize * zeroPad] should be zeroed here, in theory.
         * In practice this part of the array won't even be accessed.
         */

        // Overlap and add
        {
            // Mix last overlap-added history hop with first hop of new block, demodulating on the fly
            for (int i = 0; i < hopSize; i++)
                data[i] = (outputBlock[i] + overlapAddBuffer[i]) * getDemodulationWindow(i, outputHopIndex);
            // Shift overlap-added history
            System.arraycopy(overlapAddBuffer, hopSize, overlapAddBuffer, 0, blockSize - hopSize * 2);
            Arrays.fill(overlapAddBuffer, blockSize - hopSize * 2, blockSize - hopSize, 0.0f);
            // Mix remaining hops of new block into overlap-added history
            for (int i = 0; i < blockSize - hopSize; i++)
                overlapAddBuffer[i] += outputBlock[i + hopSize];
        }

        // Increment counters
        processHopIndex++;
        outputHopIndex++;
    }

    /**
     * Manually fix the spectrum to take account for different FFT implementations
     * @param spectrum the spectrum to fix in-place
     */
    private void fixSpectrum(Cmplx[] spectrum) {
        /*
         * The FFT of a real array is defined by half the FFT of the corresponding complex array.
         * However, not all FFT implementations use the same 'half'. If the FFT library used here
         * does not agreee with your own, you may want to uncomment the following loop.
         *
         * Another solution is to reverse the phase in equation 5 ("-i" becomes "i", and
         * "(cycleLength - phaseShift) % cycleLength" (in method processSpectrum) becomes "phaseShift")
         */
//        for (int i = 0; i < spectrum.length; i++) {
//            spectrum[i].im *= -1.0f;
//        }

        /*
         * This pitch shifting algorithm assumes that the FFT is taken over [0..N-1] sample arrays.
         * If your FFT implementation uses [-N/2..N/2-1] arrays instead, you may need to uncomment the following loop:
         */
//        for (int i = 0; i < spectrum.length; i += 2) {
//            spectrum[i].mul(-1.0f);
//        }
    }

    /**
     * Actual Ocean Pitch Shifting implementation
     * @param inputSpectrum input spectrum
     * @param outputSpectrum output spectrum, filled by this method
     */
    private void processSpectrum(Cmplx[] inputSpectrum, Cmplx[] outputSpectrum) {
        outputSpectrum[0].set(inputSpectrum[0]); // Copy DC
        // Clear output bins
        for (int i = 1; i < nbOutputBins; i++)
            outputSpectrum[i].clear();
        Cmplx work = new Cmplx();

        int cycleLength = overlap * zeroPad;
        int cycleIndex = (int) ((processHopIndex + cycleLength * 2) % cycleLength); // processHopIndex % cycleLength (Euclidian modulo, assuming processHopIndex >= -cycleLength*2)
        // Paper's notation for cycleIndex: p % mO (the modulo is not strictly necessary and not present in the paper, but it prevents overflows in practice)

        for (int srcBinIndex = 1; srcBinIndex < nbInputBins; srcBinIndex++) {
            int paddedSrcBinIndex = srcBinIndex * zeroPad;
            // Calculate destination bin index
            int dstBinIndex = (int) ((double) paddedSrcBinIndex * pitchShiftRatio + 0.5); // b := floor(mka + 0.5) (Equation 4)
            if (dstBinIndex > 0 && dstBinIndex < nbOutputBins) {
                // Copy source bin index
                work.set(inputSpectrum[srcBinIndex]);

                // Compute phase shift
                int cycleShift;
                // Here we compute '(paddedSrcBinIndex - dstBinIndex) % cycleLength' with Euclidian modulo
                // In paper's notation: (b-ma) % mO
                // The modulo is not strictly necessary and is absent from the paper, but it helps the next step by keeping 0 <= cycleShift < cycleLength
                if (dstBinIndex >= paddedSrcBinIndex)
                    cycleShift = (dstBinIndex - paddedSrcBinIndex) % cycleLength;
                else
                    cycleShift = cycleLength - (paddedSrcBinIndex - dstBinIndex) % cycleLength;

                int phaseShift = (cycleIndex * cycleShift) % cycleLength; // In paper's notation: (b-ma)p % mO
                // The modulo above is not strictly necessary and is absent from the paper, but it helps the next step by keeping 0 <= cycleShift < cycleLength
                if (phaseShift != 0) // Apply phase shift
                    // In paper's notation (equation 5, top of page 3): e^(-i2π( (b-ma)p % mO) / mO)
                    // The paper has an extra 'N' denominator. Seems to be an error ;-)
                    work.mul(unityRoots[(cycleLength - phaseShift) % cycleLength]);

                // Accumulate into output spectrum
                outputSpectrum[dstBinIndex].add(work);
            }
        }
    }

    /**
     * Get the demodulation window value, at a given index.
     * <p>
     * For given parameters, the demodulation window has a period of <tt>overlap * zeroPad</tt> and
     * could in theory be computed once and stored in an array. Here we compute it on the fly, one sample
     * at a time.
     * <p>
     * Please note that the demodulation curve is only accurate on average, in a probablistic way:
     * There is a different error on every sinusoid frequency, meaning that every single pure tone is still somehow
     * modulated. However, on signals with many sinusoid frequencies the errors tend to cancel each other.
     * This makes the Ocean algorithm good with rich harmonic content or noise, but quite poor for pure tones.
     * <p>
     * On real-world signals you might still hear a residual modulation, especially at low latencies (small blockSize),
     * high zeroPad, and on low frequencies.
     * @param index the index of demodulation window array to get, from 0 (inclusive) to hopSize (exclusive)
     * @param hopIndex the running index of the output hop since the beginning of the processing
     * @return the value of the demodulation window at the given index
     */
    private float getDemodulationWindow(int index, long hopIndex) {
        float result = 0.0f;

        // 'modified analysis window' * 'synthesis window', with overlap-add
        for (int k = 0; k < overlap; k++) {
            // Get the mixing offset of the 'hopIndex - k'-th output block:
            int offset = (k * hopSize) + index;
            /*
             * Get the pitch shifting ratio for the 'hopIndex - k'-th output block.
             *
             * The framework used (ch.tachyon.tunnel.plugin.IEffect) does not yet support changing parameters (such as the pitch shifting ratio)
             * on the fly, hence we always return the current value which is the same during the whole processing anyway.
             *
             * A better implementation would maintain a history of the 'overlap - 1' last values of pitchShiftRatio and use it instead.
             */
            double pitchShiftRatioForFrame = pitchShiftRatio;

            // Accumulate values for all overlapped output blocks
            result += getModifiedAnalysisWindow(offset, hopIndex - k, pitchShiftRatioForFrame) * synthesisWindow[offset];
        }

        // Invert the result
        final float threshold = 0.1f;
        /*
         * This threshold is quite low. You may notice that some combinations of parameters
         * (example pitch shift ratio 1.3, block size 512, overlap 2, zeroPad 4) sound pretty
         * bad although the warning is not issued. However, if you change the threshold from 0.1f
         * to 0.2f, you'll get the warning, meaning that the demodulation is quite high (which
         * explains the low quality).
         *
         * You may want to increase the threshold to get a warning quicker in case of potential
         * high demodulation.
         */
        if (result <= threshold) {
            if (!overflowWarned) {
                System.err.println("Cannot accurately demodulate. Please increase overlap!");
                overflowWarned = true;
            }
            return 1.0f / threshold;
        }
        return 1.0f / result;
    }

    /**
     * Get the modified analysis window (at a given index), for an arbitrary pitch shifting ratio.
     * <p>
     * The result is a linear interpolation between the modified analysis window of the two nearest
     * integer pitch shifting ratios.
     * <p>
     * For example, the transformed window at ratio r, T(t, r) is:
     * <ul>
     * <li>T(t, 1.5) = 0.5 * T(t, 1) + 0.5 * T(t, 2)
     * <li>T(t, 1.25) = 0.75 * T(t, 1) + 0.25 * T(t, 2)
     * <li>T(t, 0.7) = 0.3 * T(t, 0) + 0.7 * T(t, 1)
     * </ul>
     * <p>
     * When zero padding is used (<tt>zeroPad &gt; 1</tt>), we are transforming into a spectrum that is
     * 'zeroPad' times bigger. Hence it is like if we pitch shift by 'pitchShiftRatio * zeroPad'.
     * @param index index of the modified analysis window array to get
     * @param hopIndex the running index of the output hop since the beginning of the processing
     * @param pitchShiftRatio the pitch shifting ratio for the corresponding frame
     * @return the value of the modified analysis window at the given index
     */
    private float getModifiedAnalysisWindow(int index, long hopIndex, double pitchShiftRatio) {
        double paddedPitchShiftRatio = pitchShiftRatio * zeroPad;
        int floorPitchShiftRatio = (int) paddedPitchShiftRatio;
        int ceilPitchShiftRatio = floorPitchShiftRatio + 1;
        float ceilAmount = (float) paddedPitchShiftRatio - floorPitchShiftRatio;
        float floorAmount = 1.0f - ceilAmount;

        float floorPsrWindow = getModifiedAnalysisWindow(index, hopIndex, floorPitchShiftRatio);
        float ceilPsrWindow = getModifiedAnalysisWindow(index, hopIndex, ceilPitchShiftRatio);
        // Linear interpolation:
        return floorPsrWindow * floorAmount + ceilPsrWindow * ceilAmount;
    }

    /**
     * Get the modified analysis window (at a given index) for an integer pitch shifting ratio
     * <p>
     * Given a periodic version of the analysis window W(t) of size N, the modified window is (ignoring zero padding):
     * <ul>
     * <li>W(0*t+s*N) at pitch shift ratio 0
     * <li>W(1*t+s*N) at pitch shift ratio 1
     * <li>W(2*t+s*N) at pitch shift ratio 2
     * <li>W(k*t+s*N) at pitch shift ratio k
     * </ul>
     * The normalized shift 's' is given by '(cycleIndex * ((pitchShiftRatio - 1) % overlap)) / overlap' (Euclidian modulo).
     * It is between 0 and 1.
     * <p>
     * 'cycleIndex' is, for a given overlap, the current value of the periodic serie {0, 1, ..., overlap-1, 0, 1, ...}.
     * For example, with overlap==4, cycleIndex takes the values {0, 1, 2, 3, 0, 1, 2, 3, 0, ...}
     * <p>
     * The use of zero padding makes the whole thing a bit more complicated. Note that no zero padding means
     * <tt>zeroPad == 1</tt>.
     * @param index index of the modified analysis window array to get
     * @param hopIndex the running index of the output hop since the beginning of the processing
     * @param pitchShiftRatioZP pitch shifting ratio, pre-multiplied by the zero padding factor (zeroPad)
     * @return the value of the modified analysis window at the given index
     */
    private float getModifiedAnalysisWindow(int index, long hopIndex, int pitchShiftRatioZP) {
        int cycleLength = overlap * zeroPad;
        int cycleIndex = (int) ((hopIndex + cycleLength * 2) % cycleLength); // hopIndex % cycleLength (Euclidian modulo, assuming hopIndex >= -cycleLength*2)

        // Calculate 'pitchShiftRatio - zeroPad', modulo 'cycleLength', Euclidian modulo
        // With no zero padding (zeroPad == 1), this is 'pitchShiftRatio - 1', modulo 'overlap'
        int psrMinusPad = (pitchShiftRatioZP + (cycleLength - zeroPad)) % cycleLength;

        int shift = (int) (((long) blockSize * cycleIndex * psrMinusPad) / cycleLength); // s * N
        int offset = (index * pitchShiftRatioZP / zeroPad + shift) % blockSize; // (k*t+s*N) % N
        return analysisWindow[offset];
    }

    /**
     * Cleanup after you have finished processing an audio signal
     */
    @Override
    public void stopProcessing() {
        inputBlock = null;
        windowedInputBlock = null;
        analysisWindow = null;
        synthesisWindow = null;
        forwFft = null;
        backFft = null;
        inputSpectrum = null;
        outputSpectrum = null;
        unityRoots = null;
        outputBlock = null;
        overlapAddBuffer = null;
    }

}
