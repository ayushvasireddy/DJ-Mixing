"""Adaptive acoustic echo cancellation.

The mic in the room picks up two things: the crowd, and the PA playing back
whatever the mixer just rendered (the "echo" -- sound leaving the speakers,
bouncing around the room, and re-entering the mic). `crowd.py` used to deal
with this by subtracting a fixed fraction of the known *playback RMS* from
the *mic RMS* -- a single scalar knob (`bleed_factor`) with no notion of
room acoustics, speaker distance, or delay. That's fine for a rough cut but
falls apart the moment the PA is loud and close to the mic, exactly the
case the README limitations note calls out.

This module replaces the scalar subtraction with an actual adaptive filter:
it learns the acoustic path from speaker to mic (gain, propagation delay,
early reflections) as a short FIR filter, predicts what the mic *should* be
hearing from the music alone, and subtracts that prediction sample-by-sample
instead of RMS-by-RMS. What's left over -- the residual -- is a much
cleaner read on "everything that isn't the track currently playing."

Algorithm: block-frequency-domain NLMS with the overlap-save constraint
(sometimes called FDAF -- frequency-domain adaptive filter). This is the
same family of algorithm real telecom/VoIP echo cancellers use, sized down
for a single mic instead of a phone network. It's implemented entirely with
FFTs so a multi-thousand-tap filter is cheap enough to run in real time in
Python/numpy, which a naive sample-by-sample NLMS loop would not be.

Reference: Shynk, J.J., "Frequency-domain and multirate adaptive
filtering," IEEE Signal Processing Magazine, 1992 (the constrained
overlap-save gradient update implemented in `_step` below).
"""

from __future__ import annotations

import numpy as np


class EchoCanceller:
    """Adaptively cancels a known reference signal (speaker output) out of a
    microphone signal, one block at a time.

    Parameters
    ----------
    block_size:
        Number of samples processed per call to `process_block`. Must stay
        fixed for the life of the instance (it's baked into the FFT size).
    filter_taps:
        Length, in samples, of the modeled acoustic path. This is the
        *whole* delay+reverb budget the canceller can absorb -- propagation
        delay from speaker to mic, digital I/O latency, and early room
        reflections all have to fit inside this window, or the echo outside
        it will leak through uncancelled. At 44.1kHz, 4096 taps is about
        93ms, comfortably more than a typical booth-to-mic path.
    mu:
        Adaptation step size, 0 < mu <= 1. Higher converges faster but is
        noisier/less stable; lower is slower but steadier. NLMS-style power
        normalization (below) means this doesn't need retuning per venue
        volume the way a plain LMS step size would.
    """

    def __init__(
        self,
        block_size: int,
        filter_taps: int = 4096,
        mu: float = 0.03,
        power_smoothing: float = 0.98,
        regularization: float = 0.2,
        eps: float = 1e-12,
    ):
        if block_size <= 0 or filter_taps <= 0:
            raise ValueError("block_size and filter_taps must be positive")
        if not (0.0 < mu <= 1.0):
            raise ValueError("mu must be in (0, 1]")

        self.block_size = block_size
        self.filter_taps = filter_taps
        self.mu = mu
        self.power_smoothing = power_smoothing
        self.regularization = regularization
        self.eps = eps

        # Overlap-save: FFT size must cover one full block plus the filter's
        # memory, so a linear (not circular) convolution can be extracted.
        self.fft_size = block_size + filter_taps
        self._n_bins = self.fft_size // 2 + 1

        self._ref_history = np.zeros(self.fft_size, dtype=np.float64)
        self._W = np.zeros(self._n_bins, dtype=np.complex128)  # filter, frequency domain
        self._power = np.zeros(self._n_bins, dtype=np.float64)
        self._step_count = 0

    def reset(self) -> None:
        """Forget everything learned so far (e.g. after a big room change)."""
        self._ref_history[:] = 0.0
        self._W[:] = 0.0
        self._power[:] = 0.0
        self._step_count = 0

    def process_block(self, mic_block: np.ndarray, ref_block: np.ndarray) -> np.ndarray:
        """Feed one block of mic samples and the time-aligned reference
        (speaker output) samples of the same length. Returns the residual
        signal for that block: the mic signal with the adaptively-modeled
        echo of the reference subtracted out. That residual is what
        `crowd.py` should treat as "crowd," in place of a raw mic reading.
        """
        mic_block = np.asarray(mic_block, dtype=np.float64).reshape(-1)
        ref_block = np.asarray(ref_block, dtype=np.float64).reshape(-1)
        if mic_block.shape[0] != self.block_size or ref_block.shape[0] != self.block_size:
            raise ValueError(
                f"process_block expects blocks of length {self.block_size}, "
                f"got mic={mic_block.shape[0]}, ref={ref_block.shape[0]}"
            )

        self._ref_history = np.concatenate([self._ref_history[self.block_size :], ref_block])
        X = np.fft.rfft(self._ref_history, n=self.fft_size)

        # Predict the echo: apply the current filter estimate to the
        # reference history, keep only the last `block_size` samples (the
        # part of the circular convolution that equals a true linear
        # convolution -- the overlap-save trick).
        y_hat_full = np.fft.irfft(X * self._W, n=self.fft_size)
        y_hat = y_hat_full[-self.block_size :]

        error = mic_block - y_hat
        self._step(X, error)
        return error.astype(np.float32)

    def _step(self, X: np.ndarray, error: np.ndarray) -> None:
        """Constrained (overlap-save) frequency-domain NLMS weight update."""
        # Recursive estimate of reference power per frequency bin, used to
        # normalize the step size (this is what makes it "NLMS" rather than
        # plain LMS -- loud passages don't blow up the adaptation). Bias-
        # corrected the same way Adam corrects its moment estimates: without
        # it, the very first few blocks divide by a power estimate that's
        # still mostly its zero initial value, producing a huge effective
        # step and knocking the filter into instability before it ever gets
        # a chance to converge.
        self._step_count += 1
        self._power = (
            self.power_smoothing * self._power
            + (1.0 - self.power_smoothing) * (np.abs(X) ** 2)
        )
        power_hat = self._power / (1.0 - self.power_smoothing**self._step_count)

        # A single block's |X(k)|^2 is a noisy (single-sample) estimate of
        # that bin's true power -- for a flat-ish spectrum like music or
        # white noise, individual bins will randomly land near zero on any
        # given block just from statistical variation, and dividing by one
        # of those blows the update up at exactly that bin. Flooring each
        # bin's normalizer at a fraction of the *average* power across all
        # bins keeps a temporarily-quiet bin from getting an outsized,
        # destabilizing step.
        floor = self.regularization * float(np.mean(power_hat)) + self.eps

        # Cross-correlate reference with error in the frequency domain, then
        # apply the "gradient constraint": only the first `filter_taps`
        # samples of that circular correlation correspond to a true linear
        # correlation, so zero out the rest before converting back to the
        # frequency domain for the update. Skipping this step is a common
        # shortcut that makes the filter noticeably less stable.
        e_padded = np.concatenate([np.zeros(self.filter_taps), error])
        E = np.fft.rfft(e_padded, n=self.fft_size)
        grad_time = np.fft.irfft(np.conj(X) * E, n=self.fft_size)
        grad_time[self.filter_taps :] = 0.0
        Grad = np.fft.rfft(grad_time, n=self.fft_size)

        self._W += self.mu * Grad / (power_hat + floor)

    def echo_return_loss_db(self, mic_block: np.ndarray, residual_block: np.ndarray) -> float:
        """How many dB of echo the canceller just removed for this block.
        Useful for logging/tuning, not required for the crowd-sensing path."""
        mic_power = float(np.mean(np.square(mic_block))) + self.eps
        residual_power = float(np.mean(np.square(residual_block))) + self.eps
        return 10.0 * np.log10(mic_power / residual_power)
