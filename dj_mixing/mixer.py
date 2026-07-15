"""The mixing engine: two virtual decks, an equal-power crossfader, and
tempo-synced playback straight out to the sound card (i.e. whatever speakers
or amp are plugged into the machine's audio output). This replaces the
physical mixing board -- all fader/EQ-style moves happen here in code,
driven by the DJ brain instead of a human's hands.
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np


def _ensure_stereo(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1:
        samples = samples[:, None]
    if samples.shape[1] == 1:
        samples = np.repeat(samples, 2, axis=1)
    return samples.astype(np.float32, copy=False)


def _resample(samples: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return samples
    import librosa

    return librosa.resample(samples.T, orig_sr=orig_sr, target_sr=target_sr, axis=-1).T.astype(
        np.float32
    )


def _time_stretch(samples: np.ndarray, rate: float) -> np.ndarray:
    """Stretch/compress audio in time without changing pitch (phase vocoder)."""
    if abs(rate - 1.0) < 1e-3:
        return samples
    import librosa

    return librosa.effects.time_stretch(samples.T, rate=rate).T.astype(np.float32)


def _rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block), dtype=np.float64)))


class Deck:
    def __init__(self, samples: np.ndarray, samplerate: int, bpm: float, title: str = ""):
        self.samples = samples
        self.samplerate = samplerate
        self.bpm = bpm
        self.title = title
        self.position = 0
        self.gain = 1.0

    @property
    def total_frames(self) -> int:
        return self.samples.shape[0]

    def remaining_seconds(self) -> float:
        return max(0.0, (self.total_frames - self.position) / self.samplerate)

    def read(self, n_frames: int) -> np.ndarray:
        start = min(self.position, self.total_frames)
        stop = min(start + n_frames, self.total_frames)
        chunk = self.samples[start:stop]
        if chunk.shape[0] < n_frames:
            pad = np.zeros((n_frames - chunk.shape[0], self.samples.shape[1]), dtype=np.float32)
            chunk = np.vstack([chunk, pad])
        self.position = stop
        return chunk * self.gain


class AudioEngine:
    """Owns two decks and streams the mixed result to an output device."""

    def __init__(self, samplerate: int = 44_100, channels: int = 2, blocksize: int = 1024):
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize

        self.decks: dict[str, Optional[Deck]] = {"a": None, "b": None}
        self.active_label = "a"
        self._transition: Optional[dict] = None
        self._last_output_rms = 0.0
        self._lock = threading.RLock()
        self._stream = None

    def load(
        self,
        label: str,
        samples: np.ndarray,
        samplerate_in: int,
        bpm: float,
        title: str = "",
        target_bpm: Optional[float] = None,
    ) -> None:
        """Load a track's raw samples onto deck `label` ("a" or "b"), resampling
        to the engine's rate and, if `target_bpm` is given, time-stretching so
        it's beatmatched to the currently playing track.
        """
        samples = _ensure_stereo(samples)
        samples = _resample(samples, samplerate_in, self.samplerate)

        effective_bpm = bpm
        if target_bpm and bpm:
            samples = _time_stretch(samples, rate=target_bpm / bpm)
            effective_bpm = target_bpm

        with self._lock:
            self.decks[label] = Deck(samples, self.samplerate, effective_bpm, title)

    def active_deck(self) -> Optional[Deck]:
        with self._lock:
            return self.decks[self.active_label]

    def other_label(self) -> str:
        return "b" if self.active_label == "a" else "a"

    def is_transitioning(self) -> bool:
        with self._lock:
            return self._transition is not None

    def start_transition(self, to_label: str, duration_seconds: float) -> None:
        with self._lock:
            if self.decks[to_label] is None:
                raise ValueError(f"No track loaded on deck {to_label!r}")
            if to_label == self.active_label:
                raise ValueError("Cannot transition a deck into itself")
            self._transition = {
                "from": self.active_label,
                "to": to_label,
                "total_frames": max(1, int(duration_seconds * self.samplerate)),
                "elapsed_frames": 0,
            }

    def current_playback_rms(self) -> float:
        with self._lock:
            return self._last_output_rms

    def render(self, n_frames: int) -> np.ndarray:
        """Produce the next `n_frames` of mixed audio. Pure function of engine
        state -- this is what both the real callback and tests call.
        """
        with self._lock:
            transition = self._transition

            if transition is None:
                active = self.decks[self.active_label]
                block = (
                    active.read(n_frames)
                    if active
                    else np.zeros((n_frames, self.channels), dtype=np.float32)
                )
                self._last_output_rms = _rms(block)
                return block

            from_deck = self.decks[transition["from"]]
            to_deck = self.decks[transition["to"]]

            elapsed = transition["elapsed_frames"]
            total = transition["total_frames"]
            frac = np.clip((elapsed + np.arange(n_frames)) / total, 0.0, 1.0)
            gain_out = np.cos(frac * np.pi / 2.0)[:, None].astype(np.float32)
            gain_in = np.sin(frac * np.pi / 2.0)[:, None].astype(np.float32)

            from_block = (
                from_deck.read(n_frames)
                if from_deck
                else np.zeros((n_frames, self.channels), dtype=np.float32)
            )
            to_block = (
                to_deck.read(n_frames)
                if to_deck
                else np.zeros((n_frames, self.channels), dtype=np.float32)
            )

            block = from_block * gain_out + to_block * gain_in
            transition["elapsed_frames"] += n_frames

            if transition["elapsed_frames"] >= total:
                self.decks[transition["from"]] = None
                self.active_label = transition["to"]
                self._transition = None

            self._last_output_rms = _rms(block)
            return block

    def _callback(self, outdata, frames, time_info, status) -> None:
        outdata[:] = self.render(frames)

    def start_output(self, device: Optional[int] = None, stream_factory=None) -> None:
        factory = stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.OutputStream

        self._stream = factory(
            device=device,
            channels=self.channels,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop_output(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
