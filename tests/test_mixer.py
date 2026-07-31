import numpy as np
import pytest

from dj_mixing.mixer import AudioEngine, _ensure_stereo


def test_ensure_stereo_duplicates_mono_channel():
    mono = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    stereo = _ensure_stereo(mono)
    assert stereo.shape == (3, 2)
    assert np.allclose(stereo[:, 0], stereo[:, 1])


def test_render_with_no_deck_loaded_returns_silence():
    engine = AudioEngine(samplerate=1000, channels=2)
    block = engine.render(16)
    assert block.shape == (16, 2)
    assert np.allclose(block, 0.0)


def test_render_plays_back_loaded_samples():
    engine = AudioEngine(samplerate=1000, channels=2)
    samples = np.full((100, 2), 0.5, dtype=np.float32)
    engine.load("a", samples, samplerate_in=1000, bpm=120, title="t1")

    block = engine.render(10)
    assert np.allclose(block, 0.5)
    assert engine.active_deck().position == 10


def test_render_pads_with_silence_past_end_of_track():
    engine = AudioEngine(samplerate=1000, channels=2)
    samples = np.full((5, 2), 1.0, dtype=np.float32)
    engine.load("a", samples, samplerate_in=1000, bpm=120, title="short")

    block = engine.render(10)
    assert np.allclose(block[:5], 1.0)
    assert np.allclose(block[5:], 0.0)


def test_start_transition_requires_target_deck_loaded():
    engine = AudioEngine(samplerate=1000, channels=2)
    engine.load("a", np.zeros((100, 2), dtype=np.float32), 1000, 120)
    with pytest.raises(ValueError):
        engine.start_transition("b", duration_seconds=1.0)


def test_start_transition_rejects_transitioning_into_self():
    engine = AudioEngine(samplerate=1000, channels=2)
    engine.load("a", np.zeros((100, 2), dtype=np.float32), 1000, 120)
    with pytest.raises(ValueError):
        engine.start_transition("a", duration_seconds=1.0)


def test_crossfade_moves_smoothly_from_deck_a_to_deck_b():
    engine = AudioEngine(samplerate=1000, channels=2)
    engine.load("a", np.full((10_000, 2), 1.0, dtype=np.float32), 1000, 120, title="A")
    engine.load("b", np.full((10_000, 2), -1.0, dtype=np.float32), 1000, 120, title="B")

    engine.start_transition("b", duration_seconds=1.0)  # 1000 frames at this samplerate
    assert engine.is_transitioning()

    first = engine.render(10)
    # Barely started: output should still be close to deck A's value.
    assert first[0, 0] > 0.9

    # Consume the rest of the crossfade.
    remaining = engine.render(990)
    last = remaining[-1]
    assert last[0] < -0.9

    assert not engine.is_transitioning()
    assert engine.active_label == "b"
    assert engine.decks["a"] is None


def test_current_playback_rms_reflects_last_rendered_block():
    engine = AudioEngine(samplerate=1000, channels=2)
    engine.load("a", np.full((100, 2), 0.5, dtype=np.float32), 1000, 120)
    engine.render(10)
    assert engine.current_playback_rms() == pytest.approx(0.5, abs=1e-6)


def test_load_resamples_when_source_rate_differs():
    engine = AudioEngine(samplerate=1000, channels=2)
    samples = np.full((500, 2), 0.3, dtype=np.float32)
    engine.load("a", samples, samplerate_in=2000, bpm=120, title="resampled")
    deck = engine.decks["a"]
    # Halving the sample rate should roughly halve the frame count.
    assert 200 <= deck.total_frames <= 300


def test_load_time_stretches_to_match_target_bpm():
    engine = AudioEngine(samplerate=8000, channels=2)
    t = np.linspace(0, 2.0, 16_000, endpoint=False)
    tone = np.sin(2 * np.pi * 220 * t).astype(np.float32)
    samples = np.stack([tone, tone], axis=1)

    engine.load("a", samples, samplerate_in=8000, bpm=100, title="stretched", target_bpm=200)
    deck = engine.decks["a"]

    assert deck.bpm == 200
    # Doubling the tempo should roughly halve the duration.
    assert deck.total_frames < samples.shape[0] * 0.7


def test_recent_output_mono_pads_with_zeros_before_anything_rendered():
    engine = AudioEngine(samplerate=1000, channels=2, reference_history_seconds=1.0)
    ref = engine.recent_output_mono(50)
    assert ref.shape == (50,)
    assert np.allclose(ref, 0.0)


def test_recent_output_mono_tracks_rendered_audio():
    engine = AudioEngine(samplerate=1000, channels=2, reference_history_seconds=1.0)
    samples = np.full((300, 2), 0.4, dtype=np.float32)
    engine.load("a", samples, samplerate_in=1000, bpm=120, title="t1")
    engine.render(100)

    ref = engine.recent_output_mono(100)
    assert ref.shape == (100,)
    assert np.allclose(ref, 0.4, atol=1e-6)


def test_recent_output_mono_returns_most_recent_samples_only():
    engine = AudioEngine(samplerate=1000, channels=2, reference_history_seconds=1.0)
    first = np.full((50, 2), 1.0, dtype=np.float32)
    second = np.full((50, 2), -1.0, dtype=np.float32)
    engine.load("a", first, samplerate_in=1000, bpm=120, title="first")
    engine.render(50)
    engine.load("a", second, samplerate_in=1000, bpm=120, title="second")
    # deck "a" is overwritten; render should now play the newly loaded track
    engine.render(50)

    ref = engine.recent_output_mono(50)
    assert np.allclose(ref, -1.0, atol=1e-6)
