import pytest

from dj_mixing import config
from dj_mixing.crowd import CrowdSensor


def make_sensor():
    # Small windows so the tests converge in a handful of ticks instead of
    # waiting out the production-sized (multi-second/minute) time constants.
    return CrowdSensor(short_window_sec=0.5, baseline_window_sec=5.0, bleed_factor=0.6)


def test_calibrate_seeds_zero_excitement():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.05)
    assert sensor.excitement_score == 0.0


def test_quiet_steady_crowd_stays_low():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.05)
    for _ in range(20):
        sensor.update(mic_rms=0.05, playback_rms=0.0, dt=0.5)
    assert sensor.level == config.ENERGY_LOW


def test_sudden_crowd_noise_pushes_energy_up():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.05)
    # Crowd suddenly roars -- short-term average should shoot up faster than the
    # slow baseline, opening a gap that reads as high/peak excitement.
    for _ in range(6):
        sensor.update(mic_rms=0.9, playback_rms=0.0, dt=0.5)
    assert sensor.level in (config.ENERGY_HIGH, config.ENERGY_PEAK)


def test_playback_bleed_is_subtracted_so_loud_music_alone_isnt_mistaken_for_crowd():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.0)
    # Mic reading rises in lockstep with (bleed_factor * playback), i.e. it's
    # entirely the music, not the crowd -- should not register as excitement.
    playback = 1.0
    mic = sensor.bleed_factor * playback
    for _ in range(20):
        sensor.update(mic_rms=mic, playback_rms=playback, dt=0.5)
    assert sensor.level == config.ENERGY_LOW
    assert abs(sensor.excitement_score) < 1e-6


def test_sustained_seconds_resets_when_level_changes():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.05)
    for _ in range(10):
        sensor.update(mic_rms=0.05, playback_rms=0.0, dt=1.0)
    sustained_low = sensor.seconds_sustained()
    assert sustained_low > 0

    sensor.update(mic_rms=0.95, playback_rms=0.0, dt=1.0)
    assert sensor.seconds_sustained() < sustained_low


def test_snapshot_returns_level_score_and_sustained_seconds():
    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.05)
    sensor.update(mic_rms=0.05, playback_rms=0.0, dt=1.0)
    level, score, sustained = sensor.snapshot()
    assert level == sensor.level
    assert score == sensor.excitement_score
    assert sustained == sensor.seconds_sustained()


def test_audio_input_worker_falls_back_to_bleed_subtraction_without_reference():
    import numpy as np
    from dj_mixing.crowd import AudioInputWorker

    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.0)
    worker = AudioInputWorker(sensor, playback_rms_provider=lambda: 0.5, samplerate=1000, blocksize=4)
    worker._last_time = None

    indata = np.full((4, 1), 0.3, dtype=np.float32)
    worker._callback(indata, 4, None, None)

    # No echo canceller wired up -> should have gone through the legacy
    # mic_rms/playback_rms bleed-subtraction path, not update_from_residual.
    assert sensor.excitement_score == pytest.approx(0.3 - sensor.bleed_factor * 0.5, abs=1e-6)


def test_audio_input_worker_uses_echo_canceller_when_wired_up():
    import numpy as np
    from dj_mixing.crowd import AudioInputWorker
    from dj_mixing.echo_cancel import EchoCanceller

    sensor = make_sensor()
    block_size = 8
    canceller = EchoCanceller(block_size=block_size, filter_taps=16)

    # Reference provider always returns silence, so the canceller should
    # predict zero echo and the residual should just be the raw mic block.
    worker = AudioInputWorker(
        sensor,
        playback_rms_provider=lambda: 0.5,  # should be ignored on this path
        samplerate=1000,
        blocksize=block_size,
        reference_provider=lambda n: np.zeros(n),
        echo_canceller=canceller,
    )
    worker._last_time = None

    indata = np.full((block_size, 1), 0.2, dtype=np.float32)
    worker._callback(indata, block_size, None, None)

    # On the very first call both the short and baseline EMAs seed to the
    # same value, so excitement_score is 0 by design -- check the seeded
    # EMA itself, which is what the residual RMS (== the raw mic level,
    # since the reference was silence) got fed in as.
    assert sensor._short_ema == pytest.approx(0.2, abs=1e-6)


def test_audio_input_worker_ignores_mismatched_frame_count():
    import numpy as np
    from dj_mixing.crowd import AudioInputWorker
    from dj_mixing.echo_cancel import EchoCanceller

    sensor = make_sensor()
    sensor.calibrate(room_noise_rms=0.0)
    canceller = EchoCanceller(block_size=8, filter_taps=16)

    called = {"reference_provider": False}

    def reference_provider(n):
        called["reference_provider"] = True
        return np.zeros(n)

    worker = AudioInputWorker(
        sensor,
        playback_rms_provider=lambda: 0.0,
        samplerate=1000,
        blocksize=8,
        reference_provider=reference_provider,
        echo_canceller=canceller,
    )
    worker._last_time = None

    # Deliver a block whose length doesn't match the canceller's block_size
    # (e.g. a short final chunk on stream stop) -- should safely fall back
    # rather than crash the canceller.
    indata = np.full((4, 1), 0.1, dtype=np.float32)
    worker._callback(indata, 4, None, None)

    assert called["reference_provider"] is False
