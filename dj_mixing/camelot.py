"""Camelot wheel key theory: pitch-class -> Camelot code, and harmonic compatibility scoring.

The Camelot wheel arranges all 24 major/minor keys around a clock so that
harmonically compatible keys sit next to each other. Major keys follow the
circle of fifths starting at C major = 8B; each minor key shares its
relative major's number with an "A" suffix (e.g. A minor = 8A).
"""

from __future__ import annotations

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Pitch class (0=C .. 11=B) -> Camelot number for the *major* key built on that root,
# derived by walking the circle of fifths starting at C=8.
_MAJOR_CAMELOT_NUMBER = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}


def camelot_code(pitch_class: int, is_minor: bool) -> str:
    """Return the Camelot code (e.g. "8B", "5A") for a detected key."""
    pitch_class = pitch_class % 12
    if is_minor:
        # A minor key's relative major sits 3 semitones up; it shares that major's number.
        relative_major_pc = (pitch_class + 3) % 12
        number = _MAJOR_CAMELOT_NUMBER[relative_major_pc]
        return f"{number}A"
    number = _MAJOR_CAMELOT_NUMBER[pitch_class]
    return f"{number}B"


def key_name(pitch_class: int, is_minor: bool) -> str:
    """Human-readable key name, e.g. "A Minor" or "C Major"."""
    root = PITCH_CLASSES[pitch_class % 12]
    return f"{root} {'Minor' if is_minor else 'Major'}"


def _parse(code: str) -> tuple[int, str]:
    code = code.strip().upper()
    number = int(code[:-1])
    letter = code[-1]
    if not (1 <= number <= 12) or letter not in ("A", "B"):
        raise ValueError(f"Invalid Camelot code: {code!r}")
    return number, letter


def compatibility(code_a: str, code_b: str) -> float:
    """Score how harmonically compatible two Camelot codes are, in [0, 1].

    1.0  = identical key
    0.85 = adjacent on the wheel (+-1, same letter) or relative major/minor (same number)
    0.5  = adjacent number, different letter (diagonal mix - riskier but usable)
    lower = increasingly dissonant
    """
    num_a, letter_a = _parse(code_a)
    num_b, letter_b = _parse(code_b)

    if num_a == num_b and letter_a == letter_b:
        return 1.0

    diff = min(abs(num_a - num_b), 12 - abs(num_a - num_b))

    if diff == 0:  # same number, different letter -> relative major/minor
        return 0.85
    if diff == 1 and letter_a == letter_b:  # adjacent, energy-change mix
        return 0.85
    if diff == 1:  # adjacent, diagonal
        return 0.5
    if diff == 2:
        return 0.3
    return max(0.0, 0.15 - 0.02 * diff)
