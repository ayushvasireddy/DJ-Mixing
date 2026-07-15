# DJ-Mixing

An AI DJ that mixes live with no board and nobody touching a fader. Drop a
folder of tracks in, plug the computer's audio output into speakers/an amp,
and it plays a continuously beatmatched, harmonically-mixed set on its own --
reacting to the crowd through a microphone, or to short typed commands if you
want to nudge it.

## How it works

1. **Analysis** (`dj_mixing/track.py`, `library.py`) -- every track in your
   library folder gets its BPM, musical key (as a Camelot code), and an
   energy score extracted with `librosa`, cached to disk so it's only done
   once per file.
2. **Crowd sensing** (`crowd.py`) -- a microphone feeds a rolling estimate of
   how loud/excited the room is *relative to its own recent baseline*, with
   the known playback volume subtracted out so the music itself isn't
   mistaken for crowd noise. It classifies the room as `low` / `medium` /
   `high` / `peak`.
3. **Manual override** (`manual_input.py`) -- optional, secondary to the mic.
   Type `hype`, `chill`, `next`, or `hold` + Enter at any time to nudge the
   set without it being a full mixing board.
4. **Decision brain** (`brain.py`) -- combines crowd energy (primary) and any
   manual command (takes priority when given) into a target energy direction,
   then picks the next track from the library using BPM closeness, Camelot
   key compatibility, and energy direction.
5. **Mixing engine** (`mixer.py`) -- two virtual decks, time-stretches the
   incoming track to match the current BPM (real beatmatching, not just
   volume fades), and crossfades between them with an equal-power curve
   timed to a whole number of bars. Streams straight out through the
   system's normal audio output.

There's no physical mixer or controller anywhere in this -- the "board" is
just this software loop, running continuously and reading the room.

## Install

```bash
# System dependencies (Linux/Debian example -- macOS: `brew install portaudio ffmpeg`)
sudo apt-get install -y libportaudio2 ffmpeg

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Drop your tracks (mp3/wav/flac/m4a/aiff/ogg) into `tracks/` (or point
`--library` elsewhere), then:

```bash
# See available audio devices first (mic + output)
python -m dj_mixing.main --list-devices

python -m dj_mixing.main --library ./tracks \
  --input-device <mic index> --output-device <speaker/interface index>
```

While it's running, type any of these + Enter as an optional manual nudge:

| Command                | Effect                                   |
|------------------------|-------------------------------------------|
| `hype` / `up` / `more`  | Push toward a higher-energy next track    |
| `chill` / `down` / `cool` | Ease off toward a lower-energy track    |
| `next` / `skip`         | Force an immediate transition             |
| `hold` / `stay`         | Keep the current vibe                     |

No mic available, or don't want crowd sensing yet? Run with `--no-mic` and
drive it entirely with those commands.

## Testing

```bash
pytest
```

All tests run against synthetic audio and fake/injected audio streams --
no microphone or speakers required to develop or CI this.

## Current limitations / roadmap

- **Crowd/music separation is a simplification.** Subtracting an estimated
  playback "bleed" from the mic signal is not full acoustic echo
  cancellation, so a very loud PA close to the mic can still confuse the
  crowd read. Works best with the mic positioned toward the crowd rather
  than the speakers.
- **Beatmatching uses phase-vocoder time-stretching** (`librosa`), which is
  good but not identical to a hardware time-stretch unit -- large tempo
  jumps between tracks can sound slightly artifacted.
- **No live key-lock/EQ automation yet** -- transitions are BPM + key aware
  crossfades; there's no automatic bass-swap or filter sweep during the
  blend.
- **Track selection has no long-term set arc** -- it optimizes the next
  track greedily each transition rather than planning a whole night's
  energy curve.
