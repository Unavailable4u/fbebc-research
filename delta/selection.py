# delta/selection.py
#
# Selection rule for the Week 4 elite-band vs. single-winner ablation
# (research-program-guide §1.4). Both arms are ONE class with ONE
# hyperparameter, k:
#
#   k = 1  -> single-winner hill-climbing (the Stage 1 default; identical to
#             the adoption rule loop.py had before this module existed:
#             a child replaces the incumbent iff fitness >= incumbent's).
#   k > 1  -> "elite band": an archive of the top-k distinct candidates seen
#             so far (the seed P_0 included); each generation's parent is
#             sampled uniformly from the band.
#
# Making single-winner "the band with k=1" is deliberate: the ablation then
# differs in exactly one number, so any difference in outcomes cannot be
# blamed on an unrelated implementation difference between two code paths.
#
# PRE-REGISTERED RULE (frozen before any circle_packing run; see
# PREREGISTRATION.md). A child enters the band iff ALL of:
#   1. it is attested AND valid (checked by the caller -- unattested
#      candidates never reach this class, Phase1 §14 hard rule 1);
#   2. its semantic_fingerprint (canonical-AST hash, admission/metrics.py)
#      differs from every current member's -- a rewrite that is
#      semantically identical to an existing elite adds no diversity; a
#      missing fingerprint (None) is never treated as a duplicate;
#   3. the band has fewer than k members, OR its fitness >= the band's
#      worst member's fitness (ties ADOPTED, matching the single-winner
#      tie rule; drift between equal-fitness programs is free).
# When the band is full, the entrant replaces the worst member (ties: the
# oldest). Equivalently: the band is the top-k distinct valid candidates
# ever seen, with recency breaking exact fitness ties.
#
# Disclosed simplification vs. the Phase1 guide's elite-band concept: the
# band width is a FIXED integer k. The guide's band-width scheduling, G_t
# controller, and fairness bound are Phase 2/3 work (Phase1 guide §1) and
# are NOT part of Stage 1. Say so in Limitations.
#
# Determinism: no hidden randomness lives here. pick_parent() takes an
# explicit random.Random, and loop.py seeds it from (seed_base, generation)
# so an interrupted-and-resumed run reproduces an uninterrupted one exactly.
# Band ORDER is part of state (it feeds randrange indexing), so
# to_dicts()/from_dicts() preserve it.

import random
from dataclasses import asdict, dataclass


@dataclass
class Elite:
    src: str
    clone_id: str | None
    fitness: float
    fingerprint: str | None = None


class EliteBand:
    def __init__(self, k: int, elites: list[Elite] | None = None):
        if k < 1:
            raise ValueError(f"band size k must be >= 1, got {k}")
        elites = list(elites or [])
        if len(elites) > k:
            raise ValueError(f"{len(elites)} elites do not fit in a band of size {k}")
        self.k = k
        self._elites: list[Elite] = elites

    def __len__(self) -> int:
        return len(self._elites)

    @property
    def elites(self) -> list[Elite]:
        return list(self._elites)

    def best(self) -> Elite | None:
        """Highest fitness; among exact ties, the most recently added."""
        if not self._elites:
            return None
        return max(reversed(self._elites), key=lambda e: e.fitness)

    def pick_parent(self, rng: random.Random) -> Elite | None:
        """Uniform over current members; None if the band is empty (the
        caller then falls back to the task's P_0 seed)."""
        if not self._elites:
            return None
        return self._elites[rng.randrange(len(self._elites))]

    def consider(self, child: Elite) -> bool:
        """Apply the pre-registered entry rule. True iff child entered."""
        if child.fingerprint is not None and any(
            e.fingerprint == child.fingerprint for e in self._elites
        ):
            return False
        if len(self._elites) < self.k:
            self._elites.append(child)
            return True
        # min() returns the first minimal index in iteration order, and the
        # list is oldest-first, so exact ties resolve to the oldest member.
        worst_i = min(range(len(self._elites)), key=lambda i: self._elites[i].fitness)
        if child.fitness >= self._elites[worst_i].fitness:
            del self._elites[worst_i]
            self._elites.append(child)
            return True
        return False

    def to_dicts(self) -> list[dict]:
        return [asdict(e) for e in self._elites]

    @classmethod
    def from_dicts(cls, k: int, rows: list[dict]) -> "EliteBand":
        return cls(k, [Elite(**r) for r in rows])


def ablation_label(band_size: int) -> str:
    """The string written to the ledger's `ablation_config` column."""
    return "single_winner_k1" if band_size == 1 else f"elite_band_k{band_size}"
