import io
import time

from dj_mixing import manual_input as mi


def test_parse_command_aliases():
    assert mi.parse_command("hype") == mi.COMMAND_HYPE
    assert mi.parse_command("MORE") == mi.COMMAND_HYPE
    assert mi.parse_command("chill") == mi.COMMAND_CHILL
    assert mi.parse_command("skip") == mi.COMMAND_NEXT
    assert mi.parse_command("stay") == mi.COMMAND_HOLD
    assert mi.parse_command("gibberish") is None


def test_poll_returns_none_when_no_commands_queued():
    override = mi.ManualOverride()
    assert override.poll() is None


def test_push_and_poll_roundtrip():
    override = mi.ManualOverride()
    override.push(mi.COMMAND_HYPE)
    assert override.poll() == mi.COMMAND_HYPE


def test_poll_returns_most_recent_and_drains_queue():
    override = mi.ManualOverride()
    override.push(mi.COMMAND_HYPE)
    override.push(mi.COMMAND_CHILL)
    assert override.poll() == mi.COMMAND_CHILL
    assert override.poll() is None


def test_background_thread_reads_lines_from_a_source():
    source = io.StringIO("hype\nnot-a-command\nnext\n")
    override = mi.ManualOverride(source=source)
    override.start()
    # Give the background thread a moment to drain the fake stdin.
    for _ in range(50):
        if override._queue.qsize() >= 2:
            break
        time.sleep(0.02)
    assert override.poll() == mi.COMMAND_NEXT
    override.stop()
