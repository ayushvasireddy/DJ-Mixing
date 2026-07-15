import io
import time
from pathlib import Path

import pytest

from dj_mixing import webapp
from dj_mixing.manual_input import COMMAND_HYPE
from dj_mixing.track import Track


@pytest.fixture(autouse=True)
def reset_state():
    webapp.state.reset()
    yield
    webapp.state.reset()


@pytest.fixture
def client():
    webapp.app.config["TESTING"] = True
    return webapp.app.test_client()


def test_index_serves_the_control_panel(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"AI DJ" in resp.data


def test_devices_endpoint_splits_inputs_and_outputs(client, monkeypatch):
    fake_devices = [
        {"name": "Built-in Mic", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Built-in Speakers", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "USB Interface", "max_input_channels": 2, "max_output_channels": 2},
    ]
    import sounddevice

    monkeypatch.setattr(sounddevice, "query_devices", lambda: fake_devices)

    resp = client.get("/api/devices")
    data = resp.get_json()
    assert [d["name"] for d in data["inputs"]] == ["Built-in Mic", "USB Interface"]
    assert [d["name"] for d in data["outputs"]] == ["Built-in Speakers", "USB Interface"]


def test_library_endpoint_lists_only_supported_files(client, tmp_path):
    (tmp_path / "song.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "beat.wav").write_bytes(b"x")

    resp = client.get(f"/api/library?library={tmp_path}")
    data = resp.get_json()
    assert sorted(data["files"]) == ["beat.wav", "song.mp3"]


def test_upload_saves_supported_and_reports_skipped(client, tmp_path):
    data = {
        "library": str(tmp_path),
        "files": [
            (io.BytesIO(b"fake mp3 bytes"), "track1.mp3"),
            (io.BytesIO(b"not audio"), "readme.txt"),
        ],
    }
    resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
    body = resp.get_json()

    assert body["saved"] == ["track1.mp3"]
    assert body["skipped"] == ["readme.txt"]
    assert (tmp_path / "track1.mp3").exists()


def test_start_rejects_when_a_set_is_already_running(client):
    with webapp.state.lock:
        webapp.state.status = "running"

    resp = client.post("/api/start", json={"library": "tracks"})
    assert resp.status_code == 400
    assert "already running" in resp.get_json()["error"]


def test_start_spawns_worker_with_request_parameters(client, monkeypatch):
    calls = []

    def fake_worker(library_path, input_device, output_device, use_mic):
        calls.append((library_path, input_device, output_device, use_mic))
        with webapp.state.lock:
            webapp.state.status = "running"

    monkeypatch.setattr(webapp, "_start_worker", fake_worker)

    resp = client.post(
        "/api/start",
        json={"library": "mylib", "input_device": 1, "output_device": 2, "use_mic": True},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "starting"

    for _ in range(100):
        if calls:
            break
        time.sleep(0.01)

    assert calls == [("mylib", 1, 2, True)]


def test_stop_tears_down_engine_and_input_worker_and_resets_state(client):
    stopped = {"engine": False, "worker": False}

    class FakeEngine:
        def stop_output(self):
            stopped["engine"] = True

    class FakeWorker:
        def stop(self):
            stopped["worker"] = True

    with webapp.state.lock:
        webapp.state.status = "running"
        webapp.state.engine = FakeEngine()
        webapp.state.input_worker = FakeWorker()

    resp = client.post("/api/stop")
    assert resp.get_json()["status"] == "idle"
    assert stopped == {"engine": True, "worker": True}
    assert webapp.state.status == "idle"
    assert webapp.state.engine is None


def test_command_rejects_unknown_commands(client):
    resp = client.post("/api/command", json={"command": "moonwalk"})
    assert resp.status_code == 400


def test_command_requires_a_running_set(client):
    resp = client.post("/api/command", json={"command": COMMAND_HYPE})
    assert resp.status_code == 400
    assert "No set is running" in resp.get_json()["error"]


def test_command_pushes_to_the_manual_override(client):
    from dj_mixing.manual_input import ManualOverride

    manual = ManualOverride()
    with webapp.state.lock:
        webapp.state.manual = manual

    resp = client.post("/api/command", json={"command": COMMAND_HYPE})
    assert resp.status_code == 200
    assert manual.poll() == COMMAND_HYPE


def test_status_when_idle_omits_track_and_crowd_fields(client):
    resp = client.get("/api/status")
    data = resp.get_json()
    assert data["status"] == "idle"
    assert "current_track" not in data
    assert "crowd" not in data


def test_status_when_running_reports_track_and_crowd_details(client):
    from dj_mixing.crowd import CrowdSensor

    class FakeBrain:
        current_track = Track(
            path=Path("/music/now.mp3"),
            title="now",
            duration_sec=180.0,
            bpm=128.0,
            camelot="8B",
            key_name="test",
            energy=0.7,
        )
        queued_track = Track(
            path=Path("/music/next.mp3"),
            title="next",
            duration_sec=180.0,
            bpm=128.0,
            camelot="8B",
            key_name="test",
            energy=0.8,
        )

    class FakeEngine:
        def is_transitioning(self):
            return True

    crowd = CrowdSensor()
    crowd.calibrate(room_noise_rms=0.05)

    with webapp.state.lock:
        webapp.state.status = "running"
        webapp.state.brain = FakeBrain()
        webapp.state.engine = FakeEngine()
        webapp.state.crowd = crowd
        webapp.state.history = ["previous", "now"]

    resp = client.get("/api/status")
    data = resp.get_json()

    assert data["current_track"]["title"] == "now"
    assert data["queued_track"] == "next"
    assert data["transitioning"] is True
    assert data["crowd"]["level"] in ("low", "medium", "high", "peak")
    assert data["history"] == ["previous", "now"]
