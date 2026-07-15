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
