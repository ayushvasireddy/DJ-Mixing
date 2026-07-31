"""Scans a folder of audio files, analyzes (and caches) them, and picks the next
track to mix in given the currently playing track and a desired energy direction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Optional

from . import camelot
from .config import BPM_MATCH_TOLERANCE, CACHE_FILENAME, SUPPORTED_EXTENSIONS
from .track import Track, analyze_track

logger = logging.getLogger(__name__)


class Library:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.cache_path = self.root / CACHE_FILENAME
        self.tracks: list[Track] = []

    def scan(self, force_reanalyze: bool = False) -> list[Track]:
        """Analyze every supported audio file under `root`, reusing cached results
        for files that haven't changed (matched by path + size + mtime).
        """
        self.root.mkdir(parents=True, exist_ok=True)
        cache = {} if force_reanalyze else self._load_cache()
        fresh_cache: dict[str, dict] = {}
        tracks: list[Track] = []

        for path in sorted(self._audio_files()):
            stat = path.stat()
            fingerprint = f"{stat.st_size}:{int(stat.st_mtime)}"
            cache_key = str(path)
            cached = cache.get(cache_key)

            if cached and cached.get("_fingerprint") == fingerprint:
                track = Track.from_dict(cached["track"])
            else:
                logger.info("Analyzing %s", path.name)
                track = analyze_track(path)

            fresh_cache[cache_key] = {"_fingerprint": fingerprint, "track": track.to_dict()}
            tracks.append(track)

        self._save_cache(fresh_cache)
        self.tracks = tracks
        return tracks

    def _audio_files(self) -> Iterable[Path]:
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        try:
            self.cache_path.write_text(json.dumps(cache, indent=2))
        except OSError:
            logger.warning("Could not write analysis cache to %s", self.cache_path)

    def find_next(
        self,
        current: Track,
        energy_direction: str = "hold",
        played: Optional[set] = None,
        weights: tuple[float, float, float] = (0.4, 0.35, 0.25),
    ) -> Optional[Track]:
        """Pick the best next track given the current one and a desired energy move.

        energy_direction: "up" (crowd flagging, push energy), "down" (crowd
        overwhelmed, cool it off), or "hold" (sustain current vibe).
        """
        played = played or set()
        bpm_weight, key_weight, energy_weight = weights

        candidates = [t for t in self.tracks if t.path != current.path]
        if not candidates:
            return None

        unplayed = [t for t in candidates if t.path not in played]
        pool = unplayed if unplayed else candidates  # if we've played everything, allow repeats

        def score(track: Track) -> float:
            bpm_diff = abs(track.bpm - current.bpm) / current.bpm
            bpm_score = max(0.0, 1.0 - bpm_diff / BPM_MATCH_TOLERANCE)

            key_score = camelot.compatibility(current.camelot, track.camelot)

            energy_delta = track.energy - current.energy
            if energy_direction == "up":
                energy_score = max(0.0, min(1.0, 0.5 + energy_delta))
            elif energy_direction == "down":
                energy_score = max(0.0, min(1.0, 0.5 - energy_delta))
            else:
                energy_score = max(0.0, 1.0 - abs(energy_delta))

            return bpm_weight * bpm_score + key_weight * key_score + energy_weight * energy_score

        return max(pool, key=score)
