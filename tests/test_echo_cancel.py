import numpy as np
import pytest

from dj_mixing.echo_cancel import EchoCanceller


def make_room_impulse_response(taps: int, rng: np.random.Generator) -> np.ndarray:
    """A short synthetic acoustic path: direct sound (delayed, attenuated)
    plus a couple of quieter early reflections -- stands in for "speaker to
    mic in a room" without needing real recordings."""
    ir = np.zeros(taps, dtype=np.float64)
    ir[20] = 0.8  # direct path
    ir[85] = 0.25  # first reflection
    ir[210] = 0.12  # second reflection
    ir += 0.001 * rng.standard_normal(taps)  # tiny bit of realism/noise
    return ir


def run_canceller(n_blocks: int, block_size: int, filter_taps: int, crowd_level: float, seed: int = 0, **kwargs):
    rng = np.random.default_rng(seed)
    canceller = EchoCanceller(block_size=block_size, filter_taps=filter_taps, **kwargs)

    room_ir = make_room_impulse_response(filter_taps, rng)

    total_samples = n_blocks * block_size
    reference = rng.standard_normal(total_samples) * 0.3
    echo = np.convolve(reference, room_ir)[:total_samples]
    crowd = rng.standard_normal(total_samples) * crowd_level
    mic = echo + crowd

    residuals = []
    for i in range(n_blocks):
        s = i * block_size
        e = s + block_size
        residual = canceller.process_block(mic[s:e], reference[s:e])
        residuals.append(residual)

    residual_full = np.concatenate(residuals)
    return residual_full, echo, crowd, mic


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def test_canceller_substantially_reduces_correlated_echo():
    block_size = 512
    filter_taps = 1024
    n_blocks = 600  # give it room to converge

    residual, echo, crowd, mic = run_canceller(
        n_blocks=n_blocks, block_size=block_size, filter_taps=filter_taps, crowd_level=0.02
    )

    # Only judge the back half, after the filter has had time to adapt.
    tail = slice(len(residual) // 2, None)
    mic_rms = rms(mic[tail])
    residual_rms = rms(residual[tail])

    # The echo dominates the raw mic signal (it's ~10-25x louder than the
    # crowd here); a working canceller should knock the residual down
    # substantially -- at least 4x quieter than the untouched mic.
    assert residual_rms < mic_rms / 4.0


def test_canceller_residual_approaches_true_crowd_floor():
    block_size = 512
    filter_taps = 1024
    n_blocks = 600

    residual, echo, crowd, mic = run_canceller(
        n_blocks=n_blocks, block_size=block_size, filter_taps=filter_taps, crowd_level=0.02
    )

    tail = slice(len(residual) // 2, None)
    crowd_rms = rms(crowd[tail])
    residual_rms = rms(residual[tail])

    # After convergence the residual should be in the same ballpark as the
    # crowd-only signal, not dominated by leftover echo. Generous tolerance
    # since this is an approximation, not perfect cancellation.
    assert residual_rms < crowd_rms * 2.5


def test_echo_return_loss_improves_over_time():
    block_size = 512
    filter_taps = 1024
    n_blocks = 600

    residual, echo, crowd, mic = run_canceller(
        n_blocks=n_blocks, block_size=block_size, filter_taps=filter_taps, crowd_level=0.02
    )

    early = slice(0, block_size * 10)
    late = slice(-block_size * 10, None)

    early_erl = rms(mic[early]) / max(rms(residual[early]), 1e-9)
    late_erl = rms(mic[late]) / max(rms(residual[late]), 1e-9)

    # Echo return loss (how much quieter the residual is vs the raw mic)
    # should grow substantially as the filter adapts.
    assert late_erl > early_erl * 2


def test_silence_reference_leaves_mic_unchanged():
    block_size = 256
    filter_taps = 256
    canceller = EchoCanceller(block_size=block_size, filter_taps=filter_taps)

    rng = np.random.default_rng(1)
    mic_block = rng.standard_normal(block_size) * 0.1
    ref_block = np.zeros(block_size)

    residual = canceller.process_block(mic_block, ref_block)
    assert np.allclose(residual, mic_block, atol=1e-6)


def test_process_block_rejects_wrong_length():
    canceller = EchoCanceller(block_size=128, filter_taps=128)
    with pytest.raises(ValueError):
        canceller.process_block(np.zeros(64), np.zeros(128))
    with pytest.raises(ValueError):
        canceller.process_block(np.zeros(128), np.zeros(64))


def test_reset_clears_learned_filter():
    block_size = 256
    filter_taps = 256
    rng = np.random.default_rng(2)
    canceller = EchoCanceller(block_size=block_size, filter_taps=filter_taps, mu=0.5)

    reference = rng.standard_normal(block_size) * 0.5
    mic = reference * 0.7  # trivially correlated so weights move off zero
    canceller.process_block(mic, reference)
    assert np.any(canceller._W != 0.0)

    canceller.reset()
    assert np.all(canceller._W == 0.0)
    assert np.all(canceller._ref_history == 0.0)
    assert np.all(canceller._power == 0.0)
    assert canceller._step_count == 0


def test_constructor_validates_arguments():
    with pytest.raises(ValueError):
        EchoCanceller(block_size=0, filter_taps=128)
    with pytest.raises(ValueError):
        EchoCanceller(block_size=128, filter_taps=0)
    with pytest.raises(ValueError):
        EchoCanceller(block_size=128, filter_taps=128, mu=0.0)
    with pytest.raises(ValueError):
        EchoCanceller(block_size=128, filter_taps=128, mu=1.5)
