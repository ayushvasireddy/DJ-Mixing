"""Audio analysis: figure out a track's BPM, musical key, and energy so the brain
can pick harmonically/rhythmically compatible tracks without a human DJ reading liner notes.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np

from . import camelot
from .config import ANALYSIS_SAMPLE_RATE

# Krumhansl-Schmuckler key profiles (perceived stability of each pitch class
# within a major/minor tonal context). Standard values from music cognition research.
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


@dataclasses.dataclass
class Track:
    path: Path
    title: str
    duration_sec: float
    bpm: float
    camelot: str
    key_name: str
    energy: float  # normalized 0..1, higher = more intense/energetic

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["path"] = str(self.path)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        d = dict(d)
        d["path"] = Path(d["path"])
        return cls(**d)


def _estimate_key(chroma_mean: np.ndarray) -> tuple[int, bool]:
    """Correlate the mean chroma vector against all 24 rotated key profiles."""
    best_score = -np.inf
    best_pc = 0
    best_minor = False
    for pc in range(12):
        major_profile = np.roll(_MAJOR_PROFILE, pc)
        minor_profile = np.roll(_MINOR_PROFILE, pc)
        major_score = np.corrcoef(chroma_mean, major_profile)[0, 1]
        minor_score = np.corrcoef(chroma_mean, minor_profile)[0, 1]
        if major_score > best_score:
            best_score, best_pc, best_minor = major_score, pc, False
        if minor_score > best_score:
            best_score, best_pc, best_minor = minor_score, pc, True
    return best_pc, best_minor


def _normalize_bpm(tempo: float) -> float:
    """Correct common octave errors (half/double tempo) toward a typical DJ-friendly range."""
    tempo = float(tempo)
    while tempo > 0 and tempo < 70:
        tempo *= 2
    while tempo > 180:
        tempo /= 2
    return round(tempo, 1)


def analyze_track(path: Path | str, energy_reference: float = 0.22) -> Track:
    """Load and analyze an audio file, returning its Track metadata.

    `energy_reference` is the approximate RMS loudness that maps to "full energy"
    (1.0); tune it against your own library if tracks all cluster near one end.
    """
    import librosa  # imported lazily: heavy dependency, only needed for real analysis

    path = Path(path)
    y, sr = librosa.load(str(path), sr=ANALYSIS_SAMPLE_RATE, mono=True)
    duration_sec = float(librosa.get_duration(y=y, sr=sr))

    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = _normalize_bpm(np.atleast_1d(tempo)[0])

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    pitch_class, is_minor = _estimate_key(chroma.mean(axis=1))
    code = camelot.camelot_code(pitch_class, is_minor)
    name = camelot.key_name(pitch_class, is_minor)

    rms = librosa.feature.rms(y=y).mean()
    tempo_norm = np.clip((bpm - 70) / 110, 0.0, 1.0)
    loudness_norm = np.clip(rms / energy_reference, 0.0, 1.0)
    energy = float(np.clip(0.7 * loudness_norm + 0.3 * tempo_norm, 0.0, 1.0))

    return Track(
        path=path,
        title=path.stem,
        duration_sec=duration_sec,
        bpm=bpm,
        camelot=code,
        key_name=name,
        energy=round(energy, 3),
    )
