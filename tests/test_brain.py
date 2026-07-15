from pathlib import Path

import numpy as np
import pytest

from dj_mixing import config, manual_input
from dj_mixing.brain import DJBrain
from dj_mixing.crowd import CrowdSensor
from dj_mixing.library import Library
from dj_mixing.mixer import AudioEngine
from dj_mixing.track import Track

SR = 1000  # tiny samplerate so synthetic "tracks" render/transition fast in tests


def make_track(name, bpm=120, camelot_code="8B", energy=0.5, seconds=2.0) -> Track:
    return Track(
        path=Path(f"/music/{name}.wav"),
        title=name,
        duration_sec=seconds,
        bpm=bpm,
        camelot=camelot_code,
        key_name="test",
        energy=energy,
    )


def make_loader(seconds_by_title):
    def loader(path):
        title = Path(path).stem
        seconds = seconds_by_title[title]
        n = int(seconds * SR)
        samples = np.full((n, 2), 0.2, dtype=np.float32)
        return samples, SR

    return loader


@pytest.fixture(autouse=True)
def fast_thresholds(monkeypatch):
    # Real-world durations (30s minimum, 4-20s crossfades) would make these
    # tests slow/unwieldy; scale them down without changing the logic under test.
    monkeypatch.setattr(config, "MIN_TRACK_SECONDS_BEFORE_TRANSITION", 0.0)
    monkeypatch.setattr(config, "MIN_CROSSFADE_SECONDS", 0.1)
    monkeypatch.setattr(config, "MAX_CROSSFADE_SECONDS", 0.5)


def test_tick_does_not_prepare_next_track_while_far_from_the_end():
    current = make_track("current", seconds=100.0)
    other = make_track("other", seconds=100.0)
    library = Library("/tmp/unused")
    library.tracks = [current, other]

    engine = AudioEngine(samplerate=SR, channels=2)
    brain = DJBrain(
        library, engine, CrowdSensor(), loader=make_loader({"current": 100.0, "other": 100.0})
    )
    brain.start(first_track=current)

    brain.tick()

    assert engine.decks["b"] is None
    assert brain.current_track.title == "current"


def test_tick_prepares_and_completes_transition_near_end_of_track():
    current = make_track("current", seconds=2.0)
    other = make_track("other", seconds=2.0)
    library = Library("/tmp/unused")
    library.tracks = [current, other]

    engine = AudioEngine(samplerate=SR, channels=2)
    brain = DJBrain(
        library, engine, CrowdSensor(), loader=make_loader({"current": 2.0, "other": 2.0})
    )
    brain.start(first_track=current)

    brain.tick()
    assert engine.decks["b"] is not None  # queued
    assert engine.is_transitioning()

    # Drive the engine through the whole crossfade.
    while engine.is_transitioning():
        engine.render(50)

    brain.tick()  # let the brain notice the transition finished
    assert brain.current_track.title == "other"
    assert Path("/music/other.wav") in brain.played


def test_manual_next_forces_transition_even_early_in_a_long_track():
    current = make_track("current", seconds=100.0)
    other = make_track("other", seconds=100.0)
    library = Library("/tmp/unused")
    library.tracks = [current, other]

    engine = AudioEngine(samplerate=SR, channels=2)
    manual = manual_input.ManualOverride()
    brain = DJBrain(
        library,
        engine,
        CrowdSensor(),
        manual=manual,
        loader=make_loader({"current": 100.0, "other": 100.0}),
    )
    brain.start(first_track=current)

    manual.push(manual_input.COMMAND_NEXT)
    brain.tick()

    assert engine.decks["b"] is not None
    assert engine.is_transitioning()


def test_manual_hype_selects_the_higher_energy_candidate():
    current = make_track("current", bpm=120, camelot_code="8B", energy=0.5, seconds=2.0)
    low = make_track("low", bpm=120, camelot_code="8B", energy=0.1, seconds=2.0)
    high = make_track("high", bpm=120, camelot_code="8B", energy=0.9, seconds=2.0)
    library = Library("/tmp/unused")
    library.tracks = [current, low, high]

    engine = AudioEngine(samplerate=SR, channels=2)
    manual = manual_input.ManualOverride()
    brain = DJBrain(
        library,
        engine,
        CrowdSensor(),
        manual=manual,
        loader=make_loader({"current": 2.0, "low": 2.0, "high": 2.0}),
    )
    brain.start(first_track=current)

    manual.push(manual_input.COMMAND_HYPE)
    brain.tick()

    assert brain._queued_track.title == "high"


def test_manual_chill_selects_the_lower_energy_candidate():
    current = make_track("current", bpm=120, camelot_code="8B", energy=0.5, seconds=2.0)
    low = make_track("low", bpm=120, camelot_code="8B", energy=0.1, seconds=2.0)
    high = make_track("high", bpm=120, camelot_code="8B", energy=0.9, seconds=2.0)
    library = Library("/tmp/unused")
    library.tracks = [current, low, high]

    engine = AudioEngine(samplerate=SR, channels=2)
    manual = manual_input.ManualOverride()
    brain = DJBrain(
        library,
        engine,
        CrowdSensor(),
        manual=manual,
        loader=make_loader({"current": 2.0, "low": 2.0, "high": 2.0}),
    )
    brain.start(first_track=current)

    manual.push(manual_input.COMMAND_CHILL)
    brain.tick()

    assert brain._queued_track.title == "low"


def test_desired_direction_is_up_after_crowd_sustains_low_energy(monkeypatch):
    monkeypatch.setattr(config, "SUSTAINED_LOW_SECONDS", 1.0)

    sensor = CrowdSensor(short_window_sec=0.2, baseline_window_sec=5.0)
    sensor.calibrate(room_noise_rms=0.05)
    for _ in range(10):
        sensor.update(mic_rms=0.05, playback_rms=0.0, dt=0.5)

    library = Library("/tmp/unused")
    library.tracks = [make_track("current")]
    brain = DJBrain(library, AudioEngine(samplerate=SR), sensor, loader=make_loader({"current": 2.0}))

    assert sensor.level == config.ENERGY_LOW
    assert sensor.seconds_sustained() >= config.SUSTAINED_LOW_SECONDS
    assert brain._desired_energy_direction() == "up"


def test_resolve_direction_prioritizes_manual_command_over_crowd():
    library = Library("/tmp/unused")
    library.tracks = [make_track("current")]
    brain = DJBrain(
        library, AudioEngine(samplerate=SR), CrowdSensor(), loader=make_loader({"current": 2.0})
    )

    assert brain._resolve_direction(manual_input.COMMAND_HOLD) == "hold"
    assert brain._resolve_direction(manual_input.COMMAND_CHILL) == "down"
    assert brain._resolve_direction(manual_input.COMMAND_HYPE) == "up"
