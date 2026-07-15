"""Crowd sensing: turn a microphone feed into a live read on how much the crowd is
into it, so the brain can react without anyone touching a board.

Two pieces:
  - CrowdSensor: pure signal-processing logic (no hardware), fully unit-testable.
  - AudioInputWorker: thin adapter that pulls real mic blocks (via sounddevice)
    and feeds them into a CrowdSensor.

The mic obviously also picks up the music itself, not just the crowd. Since we
know how loud we're currently playing (the mixer reports its own output RMS),
we subtract an estimated "bleed" of that playback level from the raw mic
reading before treating the rest as crowd noise. This is a simplification --
a real installation would benefit from acoustic echo cancellation -- but it's
enough to separate "the crowd is roaring" from "the track just dropped."
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional

from . import config


class CrowdSensor:
    """Maintains a fast "short-term" and slow "baseline" energy estimate of crowd
    noise, and classifies the gap between them into a discrete energy level.
    """

    def __init__(
        self,
        short_window_sec: float = config.CROWD_SHORT_WINDOW_SEC,
        baseline_window_sec: float = config.CROWD_BASELINE_WINDOW_SEC,
        bleed_factor: float = config.CROWD_PLAYBACK_BLEED_FACTOR,
    ):
        self.short_window_sec = short_window_sec
        self.baseline_window_sec = baseline_window_sec
        self.bleed_factor = bleed_factor

        self._short_ema: Optional[float] = None
        self._baseline_ema: Optional[float] = None
        self._lock = threading.Lock()

        self.excitement_score = 0.0
        self.level = config.ENERGY_MEDIUM
        self._time_at_level = 0.0

    def calibrate(self, room_noise_rms: float) -> None:
        """Seed the baseline with an ambient room-noise reading (e.g. before the
        first track starts, when there's no playback to subtract).
        """
        with self._lock:
            self._short_ema = room_noise_rms
            self._baseline_ema = room_noise_rms
            self.excitement_score = 0.0
            self.level = config.ENERGY_MEDIUM
            self._time_at_level = 0.0

    def update(self, mic_rms: float, playback_rms: float, dt: float) -> str:
        """Feed in one block of mic RMS + the known playback RMS at that moment.
        Returns the resulting energy level.
        """
        if dt <= 0:
            return self.level

        crowd_component = max(0.0, mic_rms - self.bleed_factor * playback_rms)

        with self._lock:
            if self._short_ema is None:
                self._short_ema = crowd_component
                self._baseline_ema = crowd_component
            else:
                alpha_short = 1.0 - math.exp(-dt / self.short_window_sec)
                alpha_base = 1.0 - math.exp(-dt / self.baseline_window_sec)
                self._short_ema += alpha_short * (crowd_component - self._short_ema)
                self._baseline_ema += alpha_base * (crowd_component - self._baseline_ema)

            self.excitement_score = self._short_ema - self._baseline_ema
            new_level = self._classify(self.excitement_score)

            if new_level == self.level:
                self._time_at_level += dt
            else:
                self.level = new_level
                self._time_at_level = 0.0

            return self.level

    @staticmethod
    def _classify(excitement_score: float) -> str:
        if excitement_score >= config.CROWD_THRESHOLD_PEAK:
            return config.ENERGY_PEAK
        if excitement_score >= config.CROWD_THRESHOLD_HIGH:
            return config.ENERGY_HIGH
        if excitement_score >= config.CROWD_THRESHOLD_MEDIUM:
            return config.ENERGY_MEDIUM
        return config.ENERGY_LOW

    def seconds_sustained(self) -> float:
        with self._lock:
            return self._time_at_level

    def snapshot(self) -> tuple[str, float, float]:
        """Return (level, excitement_score, seconds sustained at this level)."""
        with self._lock:
            return self.level, self.excitement_score, self._time_at_level


class AudioInputWorker:
    """Streams microphone audio into a CrowdSensor in real time.

    `stream_factory` defaults to `sounddevice.InputStream` but can be swapped
    for a fake in tests so this class never needs real audio hardware to be
    exercised.
    """

    def __init__(
        self,
        sensor: CrowdSensor,
        playback_rms_provider: Callable[[], float],
        device: Optional[int] = None,
        samplerate: int = 44_100,
        blocksize: int = 2048,
        stream_factory=None,
    ):
        self.sensor = sensor
        self.playback_rms_provider = playback_rms_provider
        self.device = device
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._stream_factory = stream_factory
        self._stream = None
        self._last_time = None

    def _callback(self, indata, frames, time_info, status):
        import numpy as np

        now = time.monotonic()
        dt = (now - self._last_time) if self._last_time is not None else frames / self.samplerate
        self._last_time = now

        mic_rms = float(np.sqrt(np.mean(np.square(indata), dtype=np.float64)))
        self.sensor.update(mic_rms, self.playback_rms_provider(), dt)

    def start(self) -> None:
        factory = self._stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.InputStream

        self._last_time = None
        self._stream = factory(
            device=self.device,
            channels=1,
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
