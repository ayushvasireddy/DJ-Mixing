from pathlib import Path

from dj_mixing.library import Library
from dj_mixing.track import Track


def make_track(name, bpm, camelot, energy) -> Track:
    return Track(
        path=Path(f"/music/{name}.mp3"),
        title=name,
        duration_sec=180.0,
        bpm=bpm,
        camelot=camelot,
        key_name="test",
        energy=energy,
    )


def make_library(tracks) -> Library:
    lib = Library("/tmp/does-not-matter")
    lib.tracks = tracks
    return lib


def test_find_next_prefers_matching_bpm_and_key_when_pushing_energy_up():
    current = make_track("current", bpm=128, camelot="8B", energy=0.5)
    good_match = make_track("good", bpm=128, camelot="8B", energy=0.9)
    bad_bpm = make_track("bad_bpm", bpm=160, camelot="8B", energy=0.95)
    bad_key = make_track("bad_key", bpm=128, camelot="2A", energy=0.95)

    lib = make_library([good_match, bad_bpm, bad_key])
    result = lib.find_next(current, energy_direction="up", played=set())

    assert result.title == "good"


def test_find_next_prefers_lower_energy_when_direction_is_down():
    current = make_track("current", bpm=128, camelot="8B", energy=0.6)
    calmer = make_track("calmer", bpm=127, camelot="9B", energy=0.2)
    hyped = make_track("hyped", bpm=129, camelot="9B", energy=0.95)

    lib = make_library([calmer, hyped])
    result = lib.find_next(current, energy_direction="down", played=set())

    assert result.title == "calmer"


def test_find_next_avoids_replaying_recent_tracks_when_alternatives_exist():
    current = make_track("current", bpm=128, camelot="8B", energy=0.5)
    played_already = make_track("played", bpm=128, camelot="8B", energy=0.5)
    fresh = make_track("fresh", bpm=120, camelot="3A", energy=0.5)

    lib = make_library([played_already, fresh])
    result = lib.find_next(current, energy_direction="hold", played={played_already.path})

    assert result.title == "fresh"


def test_find_next_falls_back_to_replays_when_pool_exhausted():
    current = make_track("current", bpm=128, camelot="8B", energy=0.5)
    only_option = make_track("only", bpm=128, camelot="8B", energy=0.5)

    lib = make_library([only_option])
    result = lib.find_next(current, energy_direction="hold", played={only_option.path})

    assert result.title == "only"


def test_find_next_returns_none_when_library_has_no_other_tracks():
    current = make_track("current", bpm=128, camelot="8B", energy=0.5)
    lib = make_library([current])

    assert lib.find_next(current, "hold", set()) is None
