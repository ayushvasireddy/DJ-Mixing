"""A local browser control panel for the AI DJ, for people who don't want to
live in a terminal. Run `python -m dj_mixing.webapp` (or double-click
run_app.command) and it opens http://127.0.0.1:5005 in your default browser.

Everything here is a thin HTTP wrapper around the same Library / AudioEngine /
CrowdSensor / DJBrain pieces the CLI (`main.py`) uses -- this just gives them
buttons and a status readout instead of flags and log lines.
"""

from __future__ import annotations

import logging
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from . import config, manual_input
from .brain import DJBrain
from .crowd import AudioInputWorker, CrowdSensor
from .library import Library
from .mixer import AudioEngine

logger = logging.getLogger("dj_mixing.webapp")

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_TRACKS_DIR = Path(config.DEFAULT_LIBRARY_PATH).resolve()
VALID_COMMANDS = {
    manual_input.COMMAND_HYPE,
    manual_input.COMMAND_CHILL,
    manual_input.COMMAND_NEXT,
    manual_input.COMMAND_HOLD,
}

app = Flask(__name__, static_folder=None)


class AppState:
    """All mutable state for the running set, guarded by one lock. There's only
    ever one set running at a time -- this app controls a single physical rig.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        self.status = "idle"  # idle | analyzing | running | error
        self.error_message: Optional[str] = None

        self.library: Optional[Library] = None
        self.engine: Optional[AudioEngine] = None
        self.crowd: Optional[CrowdSensor] = None
        self.manual: Optional[manual_input.ManualOverride] = None
        self.brain: Optional[DJBrain] = None
        self.input_worker: Optional[AudioInputWorker] = None

        self.stop_event = threading.Event()
        self.history: list[str] = []
        self.last_title: Optional[str] = None


state = AppState()


def _tick_loop() -> None:
    while not state.stop_event.is_set():
        with state.lock:
            brain = state.brain
        if brain is None:
            return
        try:
            brain.tick()
        except Exception:
            logger.exception("Playback loop crashed")
            with state.lock:
                state.status = "error"
                state.error_message = "Playback loop crashed -- check the server terminal for details."
            return

        with state.lock:
            if brain.current_track and brain.current_track.title != state.last_title:
                state.last_title = brain.current_track.title
                state.history.append(brain.current_track.title)

        time.sleep(0.5)


def _start_worker(library_path: str, input_device, output_device, use_mic: bool) -> None:
    try:
        with state.lock:
            state.status = "analyzing"
            state.error_message = None

        library = Library(library_path)
        tracks = library.scan()
        if not tracks:
            with state.lock:
                state.status = "error"
                state.error_message = f"No supported audio files found in {library_path}. Add some tracks first."
            return

        engine = AudioEngine(samplerate=44_100, channels=2)
        crowd = CrowdSensor()
        crowd.calibrate(room_noise_rms=0.02)
        manual = manual_input.ManualOverride()
        brain = DJBrain(library, engine, crowd, manual=manual)
        brain.start()

        engine.start_output(device=output_device)

        input_worker = None
        if use_mic:
            input_worker = AudioInputWorker(
                crowd, playback_rms_provider=engine.current_playback_rms, device=input_device
            )
            input_worker.start()

        with state.lock:
            state.library = library
            state.engine = engine
            state.crowd = crowd
            state.manual = manual
            state.brain = brain
            state.input_worker = input_worker
            state.status = "running"
            state.last_title = brain.current_track.title
            state.history = [brain.current_track.title]
            state.stop_event.clear()

        threading.Thread(target=_tick_loop, daemon=True).start()

    except Exception as exc:
        logger.exception("Failed to start the set")
        with state.lock:
            state.status = "error"
            state.error_message = str(exc)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/devices")
def api_devices():
    import sounddevice as sd

    try:
        devices = sd.query_devices()
    except Exception as exc:
        return jsonify({"error": f"Could not list audio devices: {exc}"}), 500

    inputs, outputs = [], []
    for i, d in enumerate(devices):
        entry = {"index": i, "name": d["name"]}
        if d["max_input_channels"] > 0:
            inputs.append(entry)
        if d["max_output_channels"] > 0:
            outputs.append(entry)
    return jsonify({"inputs": inputs, "outputs": outputs})


@app.route("/api/library")
def api_library():
    tracks_dir = Path(request.args.get("library") or str(DEFAULT_TRACKS_DIR))
    tracks_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p.name for p in tracks_dir.iterdir() if p.suffix.lower() in config.SUPPORTED_EXTENSIONS
    )
    return jsonify({"library": str(tracks_dir), "files": files})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    tracks_dir = Path(request.form.get("library") or str(DEFAULT_TRACKS_DIR))
    tracks_dir.mkdir(parents=True, exist_ok=True)

    saved, skipped = [], []
    for f in request.files.getlist("files"):
        filename = secure_filename(f.filename or "")
        if not filename or Path(filename).suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            skipped.append(f.filename)
            continue
        f.save(str(tracks_dir / filename))
        saved.append(filename)

    return jsonify({"saved": saved, "skipped": skipped})


@app.route("/api/start", methods=["POST"])
def api_start():
    with state.lock:
        if state.status in ("analyzing", "running"):
            return jsonify({"error": "A set is already running. Stop it first."}), 400
        state.reset()

    data = request.get_json(force=True, silent=True) or {}
    library_path = data.get("library") or str(DEFAULT_TRACKS_DIR)
    input_device = data.get("input_device")
    output_device = data.get("output_device")
    use_mic = bool(data.get("use_mic", True))

    threading.Thread(
        target=_start_worker,
        args=(library_path, input_device, output_device, use_mic),
        daemon=True,
    ).start()
    return jsonify({"status": "starting"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    with state.lock:
        state.stop_event.set()
        engine = state.engine
        input_worker = state.input_worker

    if engine is not None:
        engine.stop_output()
    if input_worker is not None:
        input_worker.stop()

    state.reset()
    return jsonify({"status": "idle"})


@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(force=True, silent=True) or {}
    command = data.get("command")
    if command not in VALID_COMMANDS:
        return jsonify({"error": f"Unknown command {command!r}"}), 400

    with state.lock:
        manual = state.manual
    if manual is None:
        return jsonify({"error": "No set is running"}), 400

    manual.push(command)
    return jsonify({"status": "ok"})


@app.route("/api/status")
def api_status():
    with state.lock:
        payload = {
            "status": state.status,
            "error": state.error_message,
            "history": list(state.history[-20:]),
        }
        brain = state.brain
        crowd = state.crowd
        engine = state.engine

        if brain is not None and brain.current_track is not None:
            t = brain.current_track
            payload["current_track"] = {
                "title": t.title,
                "bpm": t.bpm,
                "camelot": t.camelot,
                "energy": t.energy,
            }
            payload["queued_track"] = brain.queued_track.title if brain.queued_track else None
            payload["transitioning"] = engine.is_transitioning() if engine is not None else False

        if crowd is not None:
            level, excitement, sustained = crowd.snapshot()
            payload["crowd"] = {
                "level": level,
                "excitement": round(excitement, 3),
                "sustained_seconds": round(sustained, 1),
            }

    return jsonify(payload)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    port = 5005
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
