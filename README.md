# DJ-Mixing

An AI DJ that mixes live with no board and nobody touching a fader. Drop a
folder of tracks in, plug the computer's audio output into speakers/an amp,
and it plays a continuously beatmatched, harmonically-mixed set on its own --
reacting to the crowd through a microphone, or to short typed commands if you
want to nudge it.

**New to this / no coding background?** See
[`GETTING_STARTED.md`](GETTING_STARTED.md) for a plain-language walkthrough
and fixes for common first-run snags.

## How it works

1. **Analysis** (`dj_mixing/track.py`, `library.py`) -- every track in your
   library folder gets its BPM, musical key (as a Camelot code), and an
   energy score extracted with `librosa`, cached to disk so it's only done
   once per file.
2. **Crowd sensing** (`crowd.py`, `echo_cancel.py`) -- a microphone feeds a
   rolling estimate of how loud/excited the room is *relative to its own
   recent baseline*. The mic also picks up the music itself, so an adaptive
   filter (`echo_cancel.EchoCanceller`) learns the actual speaker-to-mic
   acoustic path in real time and cancels its prediction out of the mic
   signal sample-by-sample, leaving a much cleaner crowd read than a simple
   volume-based guess. It classifies the room as `low` / `medium` / `high` /
   `peak`.
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

## Usage: browser control panel (easiest)

This is a local web app -- nothing leaves your machine, there's no account
and no internet dependency once packages are installed.

**macOS, no terminal needed after first setup:** double-click `run_app.command`
in Finder. The first run creates the Python environment and installs
everything (takes a few minutes); every run after that just starts the app.
Your default browser opens automatically to the control panel.

If Finder refuses to open it the first time ("unidentified developer"),
right-click `run_app.command` → **Open** → confirm **Open** in the dialog.
After that first override it'll double-click normally from then on.

**Manually, from a terminal (any OS):**
```bash
source .venv/bin/activate
python -m dj_mixing.webapp
```

In the page that opens:
1. Set (or leave) the library folder, then drag your audio files into the
   upload box (or click it to pick files) -- they get copied into that folder.
2. Pick your microphone and speaker/output device from the dropdowns (or
   uncheck "Use microphone" to run on manual control only).
3. Click **Start the set**. First run analyzes each track (BPM/key/energy),
   which takes a bit; after that it's cached and instant.
4. Watch the crowd energy meter and now-playing card, or use the **Hype /
   Chill / Skip / Hold** buttons to nudge it yourself.
5. **Stop the set** when you're done.

## Usage: command line

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

No mic available, or don't want crowd sensing yet? Run with `--no-mic` (CLI)
or uncheck "Use microphone" (web app) and drive it entirely with those
commands/buttons.

The mic is echo-cancelled against the mixer's own output by default (see
"How it works" above), which is what makes crowd sensing usable next to a
loud PA. If you want the old, cruder RMS-based bleed subtraction instead
(e.g. for comparison, or if the adaptive filter is misbehaving in an unusual
room), pass `--no-echo-cancel` (CLI) or uncheck "Adaptively cancel the PA
out of the mic signal" (web app).

## Testing

```bash
pytest
```

All tests run against synthetic audio and fake/injected audio streams --
no microphone or speakers required to develop or CI this.

## Current limitations / roadmap

- **Echo cancellation, not full acoustic echo cancellation.** By default,
  crowd sensing runs the mic through an adaptive filter
  (`echo_cancel.EchoCanceller`, block-frequency-domain NLMS) that learns the
  actual speaker-to-mic acoustic path and cancels it out sample-by-sample --
  a real step up from a fixed RMS "bleed" subtraction, and it works well
  with a loud PA close to the mic. It's still not a full telecom-grade AEC:
  it models a fixed-length acoustic path (~93ms of delay + early
  reflections by default, `AEC_FILTER_TAPS` in `config.py`), so an unusually
  large room/long throw can exceed that window and leak some uncancelled
  echo through, and it assumes the mic and output devices share a sample
  clock closely enough not to drift within a session. Works best with the
  mic positioned toward the crowd rather than the speakers. The old scalar
  bleed subtraction is still available as a `--no-echo-cancel` fallback.
- **Beatmatching uses phase-vocoder time-stretching** (`librosa`), which is
  good but not identical to a hardware time-stretch unit -- large tempo
  jumps between tracks can sound slightly artifacted.
- **No live key-lock/EQ automation yet** -- transitions are BPM + key aware
  crossfades; there's no automatic bass-swap or filter sweep during the
  blend.
- **Track selection has no long-term set arc** -- it optimizes the next
  track greedily each transition rather than planning a whole night's
  energy curve.
- **No Spotify (by design, not oversight).** Spotify's terms don't allow
  extracting playable audio from their app for outside processing, so real
  crossfading/beatmatching against Spotify audio isn't possible. Bring your
  own audio files instead -- that's what gives this full mixing control. A
  future option could use Spotify's API purely to *import a playlist's track
  list* or to remote-control Spotify playback (hard cuts only, no blending),
  but that's a different feature from what this does today.
- **Web app has no auth and binds to localhost only** -- it's meant to run on
  the same machine you're DJing from, not to be exposed on a network.
