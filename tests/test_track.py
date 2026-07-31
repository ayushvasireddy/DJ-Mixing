import re

import numpy as np
import pytest
import soundfile as sf

from dj_mixing.track import analyze_track


@pytest.fixture
def synthetic_track(tmp_path):
    """A short click-track-like signal: a steady kick pulse at ~128 BPM plus a
    held tone so key/energy detection has something to grab onto. It won't be
    perfectly analyzed like real music, but exercises the full librosa pipeline.
    """
    sr = 22_050
    duration = 8.0
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)

    bpm = 128.0
    beat_period = 60.0 / bpm
    kick = np.zeros_like(t)
    for beat_time in np.arange(0, duration, beat_period):
        idx = int(beat_time * sr)
        decay_len = int(0.08 * sr)
        end = min(idx + decay_len, len(kick))
        n = end - idx
        if n > 0:
            kick[idx:end] += np.exp(-np.linspace(0, 20, n)) * np.sin(2 * np.pi * 60 * np.linspace(0, 0.08, n))

    tone = 0.15 * np.sin(2 * np.pi * 261.63 * t)  # C4, i.e. pitch class C
    signal = np.clip(kick + tone, -1.0, 1.0).astype(np.float32)

    path = tmp_path / "synthetic.wav"
    sf.write(str(path), signal, sr)
    return path


def test_analyze_track_returns_plausible_metadata(synthetic_track):
    track = analyze_track(synthetic_track)

    assert track.title == "synthetic"
    assert 6.0 < track.duration_sec < 10.0
    assert 60.0 <= track.bpm <= 180.0
    assert re.fullmatch(r"(1[0-2]|[1-9])[AB]", track.camelot)
    assert 0.0 <= track.energy <= 1.0
