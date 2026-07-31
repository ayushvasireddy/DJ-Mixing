from dj_mixing import camelot


def test_c_major_is_8b():
    assert camelot.camelot_code(pitch_class=0, is_minor=False) == "8B"


def test_a_minor_is_8a():
    assert camelot.camelot_code(pitch_class=9, is_minor=True) == "8A"


def test_g_major_is_9b_one_step_around_circle_of_fifths():
    assert camelot.camelot_code(pitch_class=7, is_minor=False) == "9B"


def test_key_name_formatting():
    assert camelot.key_name(0, False) == "C Major"
    assert camelot.key_name(9, True) == "A Minor"


def test_identical_key_is_perfect_match():
    assert camelot.compatibility("8B", "8B") == 1.0


def test_relative_major_minor_is_highly_compatible():
    assert camelot.compatibility("8B", "8A") == 0.85


def test_adjacent_wheel_number_same_letter_is_highly_compatible():
    assert camelot.compatibility("8B", "9B") == 0.85
    assert camelot.compatibility("8B", "7B") == 0.85


def test_adjacent_diagonal_is_moderate():
    assert camelot.compatibility("8B", "9A") == 0.5


def test_far_apart_keys_score_low():
    assert camelot.compatibility("8B", "2B") < 0.3


def test_compatibility_is_symmetric():
    for a, b in [("8B", "9B"), ("3A", "7B"), ("12A", "1B")]:
        assert camelot.compatibility(a, b) == camelot.compatibility(b, a)
