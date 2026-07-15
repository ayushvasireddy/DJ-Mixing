"""CLI entrypoint: wires the library, crowd sensor, manual override, mixing
engine, and brain together and runs the autonomous set.

    python -m dj_mixing.main --library ./tracks
    python -m dj_mixing.main --list-devices
"""

from __future__ import annotations

import argparse
import logging
import time

from . import config
from .brain import DJBrain
from .crowd import AudioInputWorker, CrowdSensor
from .library import Library
from .manual_input import ManualOverride
from .mixer import AudioEngine

logger = logging.getLogger("dj_mixing")


def list_devices() -> None:
    import sounddevice as sd

    print(sd.query_devices())


def run(args: argparse.Namespace) -> None:
    library = Library(args.library)
    tracks = library.scan(force_reanalyze=args.reanalyze)
    if not tracks:
        raise SystemExit(
            f"No supported audio files found under {args.library!s}. "
            f"Supported: {sorted(config.SUPPORTED_EXTENSIONS)}"
        )
    logger.info("Loaded %d tracks", len(tracks))

    engine = AudioEngine(samplerate=args.samplerate, channels=2)
    crowd_sensor = CrowdSensor()
    manual = ManualOverride()
    brain = DJBrain(library, engine, crowd_sensor, manual=manual)

    brain.start()
    logger.info("Opening: %s (%.0f BPM, %s)", brain.current_track.title, brain.current_track.bpm, brain.current_track.camelot)

    engine.start_output(device=args.output_device)

    input_worker = AudioInputWorker(
        crowd_sensor,
        playback_rms_provider=engine.current_playback_rms,
        device=args.input_device,
    )
    if not args.no_mic:
        input_worker.start()
    else:
        logger.info("Mic input disabled (--no-mic); relying on manual overrides only.")

    manual.start()
    logger.info(
        "Running. Type commands (hype / chill / next / hold) + Enter as a manual override, Ctrl+C to stop."
    )

    try:
        last_title = brain.current_track.title
        while True:
            brain.tick()
            if brain.current_track and brain.current_track.title != last_title:
                last_title = brain.current_track.title
                level, excitement, _ = crowd_sensor.snapshot()
                logger.info(
                    "Now playing: %s (%.0f BPM, %s) | crowd=%s (%.2f)",
                    brain.current_track.title,
                    brain.current_track.bpm,
                    brain.current_track.camelot,
                    level,
                    excitement,
                )
            time.sleep(args.tick_interval)
    except KeyboardInterrupt:
        logger.info("Stopping.")
    finally:
        manual.stop()
        if not args.no_mic:
            input_worker.stop()
        engine.stop_output()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", default=str(config.DEFAULT_LIBRARY_PATH), help="Folder of audio files to mix from")
    parser.add_argument("--reanalyze", action="store_true", help="Ignore the analysis cache and re-analyze every track")
    parser.add_argument("--input-device", type=int, default=None, help="Mic device index (see --list-devices)")
    parser.add_argument("--output-device", type=int, default=None, help="Output device index (see --list-devices)")
    parser.add_argument("--no-mic", action="store_true", help="Disable mic-based crowd sensing; manual overrides only")
    parser.add_argument("--samplerate", type=int, default=44_100)
    parser.add_argument("--tick-interval", type=float, default=0.5, help="Seconds between brain decision ticks")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_devices:
        list_devices()
        return

    run(args)


if __name__ == "__main__":
    main()
