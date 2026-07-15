"""Central tunables for the AI DJ. Adjust these to taste rather than hunting through modules."""

from pathlib import Path

# --- Library / analysis --------------------------------------------------
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aiff", ".ogg"}
ANALYSIS_SAMPLE_RATE = 22_050
CACHE_FILENAME = ".dj_mixing_cache.json"

BPM_MATCH_TOLERANCE = 0.08  # fraction; candidate tracks within +/-8% BPM are considered mixable

# --- Crowd sensing ---------------------------------------------------------
# Energy levels the crowd sensor reports, low -> high excitement.
ENERGY_LOW = "low"
ENERGY_MEDIUM = "medium"
ENERGY_HIGH = "high"
ENERGY_PEAK = "peak"

# Thresholds on the smoothed "excitement score" (crowd mic energy minus expected
# playback bleed, roughly in normalized dB-ish units). Tune these to your mic/venue.
CROWD_THRESHOLD_MEDIUM = 0.15
CROWD_THRESHOLD_HIGH = 0.35
CROWD_THRESHOLD_PEAK = 0.60

CROWD_SHORT_WINDOW_SEC = 2.0     # fast-reacting energy window (cheers, drops)
CROWD_BASELINE_WINDOW_SEC = 45.0  # slow-moving room baseline (ambient chatter)
CROWD_PLAYBACK_BLEED_FACTOR = 0.6  # how much of the known playback level to subtract from the mic reading
SUSTAINED_LOW_SECONDS = 20.0     # how long the crowd must stay LOW before we force a change

# --- Mixing ------------------------------------------------------------
MIN_TRACK_SECONDS_BEFORE_TRANSITION = 30.0
END_OF_TRACK_LEAD_SECONDS = 20.0  # start looking for a transition this many seconds before a track ends
DEFAULT_CROSSFADE_BEATS = 16
MIN_CROSSFADE_SECONDS = 4.0
MAX_CROSSFADE_SECONDS = 20.0

DEFAULT_LIBRARY_PATH = Path("tracks")
