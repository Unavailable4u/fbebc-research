# delta/control/channel.py
#
# Ported unchanged from the Phase1 implementation guide, §12. Nothing here
# is touched by Stage 1's scope cut -- it's small, pure Python, and has
# nothing to do with latency, gVisor, or the adversarial suite size.
#
# Theorem 6 (Soares, Fallenstein, Yudkowsky & Armstrong, *Corrigibility*):
# utility penalties alone don't stop a subagent from circumventing a
# constraint. Engineering translation: don't build the stop button out of
# anything the agent can reason about. No candidate code ever sees this
# object or any representation of its state.

import signal
import threading


class ControlChannel:
    """Host-side only. No representation of this state ever reaches T2 or T3."""

    def __init__(self):
        self._halt = threading.Event()
        self._pause = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self._halt.set())

    def halt(self):
        self._halt.set()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    @property
    def halting(self):
        return self._halt.is_set()

    def checkpoint(self):
        """Call between generations and between evaluations.

        Requirements this exists to satisfy (Phase1 §12):
          - Drain, don't kill: stop admitting new candidates, let in-flight
            containers finish or hit their own timeout, flush the ledger,
            verify the chain, write a final manifest attestation.
          - Do not expose budget state to candidates: no remaining-
            generations counter, no wall-clock deadline, reachable from
            inside a container.
          - Halt is not a fitness event: a candidate interrupted by halt is
            recorded as status="drained" and excluded from selection
            entirely -- never scored 0.
        """
        while self._pause.is_set() and not self._halt.is_set():
            self._halt.wait(0.2)
        if self._halt.is_set():
            raise SystemExit("halt requested")
