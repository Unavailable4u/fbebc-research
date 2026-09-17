import threading
import time

import pytest

from delta.control.channel import ControlChannel


def test_checkpoint_passes_when_not_halted_or_paused():
    ch = ControlChannel()
    ch.checkpoint()  # should not raise


def test_halt_raises_systemexit_on_checkpoint():
    ch = ControlChannel()
    ch.halt()
    with pytest.raises(SystemExit):
        ch.checkpoint()


def test_pause_then_resume_unblocks_checkpoint():
    ch = ControlChannel()
    ch.pause()
    unblocked = threading.Event()

    def worker():
        ch.checkpoint()  # blocks here until resume()
        unblocked.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.1)
    assert not unblocked.is_set()

    ch.resume()
    t.join(timeout=2.0)
    assert unblocked.is_set()


def test_halt_wins_over_pause():
    """Corrigibility requirement: halt must not be blockable by a stuck pause."""
    ch = ControlChannel()
    ch.pause()
    ch.halt()
    with pytest.raises(SystemExit):
        ch.checkpoint()


def test_control_state_has_no_candidate_visible_surface():
    """No representation of halt/pause state should be exposed as anything
    a candidate could plausibly be handed (Phase1 §12: budget/deadline state
    must never be reachable from inside a container). This is a cheap
    structural smoke check, not a sandbox-level guarantee."""
    ch = ControlChannel()
    public_attrs = [a for a in dir(ch) if not a.startswith("_")]
    assert set(public_attrs) == {"halt", "pause", "resume", "halting", "checkpoint"}
