"""Manual override channel: an optional fallback for when someone wants to
nudge the AI DJ directly, without needing a mixing board. Just short text
commands (typed, or piped in from a simple keypad/foot-pedal script) -- the
crowd mic remains the primary signal.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional, TextIO

COMMAND_HYPE = "hype"     # push energy up now
COMMAND_CHILL = "chill"   # bring energy down
COMMAND_NEXT = "next"     # force a transition immediately
COMMAND_HOLD = "hold"     # stay on the current track / vibe

_ALIASES = {
    "hype": COMMAND_HYPE, "up": COMMAND_HYPE, "more": COMMAND_HYPE, "h": COMMAND_HYPE,
    "chill": COMMAND_CHILL, "down": COMMAND_CHILL, "cool": COMMAND_CHILL, "c": COMMAND_CHILL,
    "next": COMMAND_NEXT, "skip": COMMAND_NEXT, "n": COMMAND_NEXT,
    "hold": COMMAND_HOLD, "stay": COMMAND_HOLD,
}


def parse_command(line: str) -> Optional[str]:
    return _ALIASES.get(line.strip().lower())


class ManualOverride:
    """Reads commands from any line-based source (stdin by default) on a
    background thread and makes them available via a thread-safe queue.
    """

    def __init__(self, source: Optional[TextIO] = None):
        self._source = source
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        import sys

        source = self._source if self._source is not None else sys.stdin
        self._thread = threading.Thread(target=self._run, args=(source,), daemon=True)
        self._thread.start()

    def _run(self, source: TextIO) -> None:
        for line in iter(source.readline, ""):
            if self._stop.is_set():
                break
            command = parse_command(line)
            if command:
                self._queue.put(command)

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> Optional[str]:
        """Return the most recently queued command, discarding older ones, or None."""
        latest = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        return latest

    def push(self, command: str) -> None:
        """Inject a command programmatically (e.g. from a GUI button or test)."""
        self._queue.put(command)
