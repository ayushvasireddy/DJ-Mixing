"""The DJ brain: the piece that replaces the human standing at the board.

On every tick it looks at how the crowd is feeling (primary signal) and any
manual override (secondary, optional), decides whether it's time to move to
another track and in which energy direction, queues up a harmonically/rhythmically
compatible pick from the library, beatmatches it, and tells the mixing engine
when to crossfade. No board, no faders to touch -- just tell it "hype it up"
or let the mic figure it out.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from . import config, manual_input
from .crowd import CrowdSensor
from .library import Library
from .mixer import AudioEngine
from .track import Track

logger = logging.getLogger(__name__)


def default_loader(path: Path):
    """Read a track's raw samples off disk. Swappable for tests/fakes."""
    import soundfile as sf

    samples, samplerate = sf.read(str(path), dtype="float32", always_2d=True)
    return samples, samplerate


class DJBrain:
    def __init__(
        self,
        library: Library,
        engine: AudioEngine,
        crowd_sensor: CrowdSensor,
        manual: Optional[manual_input.ManualOverride] = None,
        loader: Callable = default_loader,
    ):
        self.library = library
        self.engine = engine
        self.crowd = crowd_sensor
        self.manual = manual
        self.loader = loader

        self.played: set[Path] = set()
        self._current_track: Optional[Track] = None
        self._queued_track: Optional[Track] = None
        self._queued_label: Optional[str] = None

    def start(self, first_track: Optional[Track] = None) -> None:
        track = first_track or self._pick_opener()
        if track is None:
            raise RuntimeError("Library has no tracks to start with")
        samples, sr = self.loader(track.path)
        self.engine.load("a", samples, sr, track.bpm, title=track.title)
        self.engine.active_label = "a"
        self._current_track = track
        self.played.add(track.path)

    def _pick_opener(self) -> Optional[Track]:
        if not self.library.tracks:
            return None
        # Open with something mid-energy so there's room to move the crowd either way.
        return min(self.library.tracks, key=lambda t: abs(t.energy - 0.5))

    def _desired_energy_direction(self) -> str:
        level, _excitement, sustained = self.crowd.snapshot()
        if level == config.ENERGY_PEAK:
            return "hold"
        if level == config.ENERGY_HIGH:
            return "up"
        if level == config.ENERGY_LOW and sustained >= config.SUSTAINED_LOW_SECONDS:
            return "up"
        if level == config.ENERGY_LOW:
            return "hold"
        return "hold"

    def _resolve_direction(self, manual_cmd: Optional[str]) -> str:
        if manual_cmd == manual_input.COMMAND_HYPE:
            return "up"
        if manual_cmd == manual_input.COMMAND_CHILL:
            return "down"
        if manual_cmd == manual_input.COMMAND_HOLD:
            return "hold"
        return self._desired_energy_direction()

    def _crossfade_duration(self, bpm: float) -> float:
        seconds_per_beat = 60.0 / max(bpm, 1.0)
        duration = config.DEFAULT_CROSSFADE_BEATS * seconds_per_beat
        return max(config.MIN_CROSSFADE_SECONDS, min(config.MAX_CROSSFADE_SECONDS, duration))

    def tick(self) -> None:
        """Advance the decision loop by one step. Call this every ~0.5-1s."""
        self._absorb_completed_transition()

        current_deck = self.engine.active_deck()
        if current_deck is None or self._current_track is None:
            return

        manual_cmd = self.manual.poll() if self.manual else None
        forced_next = manual_cmd == manual_input.COMMAND_NEXT

        next_label = self.engine.other_label()
        remaining = current_deck.remaining_seconds()
        elapsed = current_deck.position / current_deck.samplerate

        past_minimum = elapsed >= config.MIN_TRACK_SECONDS_BEFORE_TRANSITION
        near_end = remaining <= config.END_OF_TRACK_LEAD_SECONDS
        should_prepare = self.engine.decks[next_label] is None and (
            forced_next or (past_minimum and near_end)
        )

        if should_prepare:
            self._queue_next(manual_cmd, next_label)

        ready_to_transition = (
            not self.engine.is_transitioning()
            and self.engine.decks[next_label] is not None
            and (forced_next or (past_minimum and near_end))
        )
        if ready_to_transition:
            duration = self._crossfade_duration(self._current_track.bpm)
            logger.info(
                "Transitioning %s -> %s over %.1fs",
                self._current_track.title,
                self._queued_track.title if self._queued_track else "?",
                duration,
            )
            self.engine.start_transition(next_label, duration)

    def _queue_next(self, manual_cmd: Optional[str], next_label: str) -> None:
        direction = self._resolve_direction(manual_cmd)
        next_track = self.library.find_next(self._current_track, direction, self.played)
        if next_track is None:
            return
        samples, sr = self.loader(next_track.path)
        self.engine.load(
            next_label,
            samples,
            sr,
            next_track.bpm,
            title=next_track.title,
            target_bpm=self._current_track.bpm,
        )
        self._queued_track = next_track
        self._queued_label = next_label

    def _absorb_completed_transition(self) -> None:
        if (
            self._queued_track is not None
            and self.engine.active_label == self._queued_label
            and not self.engine.is_transitioning()
        ):
            self._current_track = self._queued_track
            self.played.add(self._current_track.path)
            self._queued_track = None
            self._queued_label = None

    @property
    def current_track(self) -> Optional[Track]:
        return self._current_track
