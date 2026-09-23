import random

import pytest

from delta.selection import Elite, EliteBand, ablation_label


def E(fit, fp=None, cid=None):
    return Elite(src=f"src-{fit}-{fp}", clone_id=cid or f"c-{fit}-{fp}", fitness=fit, fingerprint=fp)


def test_band_fills_to_k_regardless_of_fitness_order():
    b = EliteBand(3)
    assert b.consider(E(1.0, "a")) and b.consider(E(0.1, "b")) and b.consider(E(2.0, "c"))
    assert len(b) == 3
    assert b.best().fitness == 2.0


def test_full_band_admits_better_child_replacing_worst():
    b = EliteBand(2, [E(1.0, "a"), E(3.0, "b")])
    assert b.consider(E(2.0, "c")) is True
    assert sorted(e.fitness for e in b.elites) == [2.0, 3.0]


def test_full_band_rejects_child_worse_than_worst():
    b = EliteBand(2, [E(1.0, "a"), E(3.0, "b")])
    assert b.consider(E(0.5, "c")) is False
    assert sorted(e.fitness for e in b.elites) == [1.0, 3.0]


def test_tie_with_worst_is_adopted_and_replaces_the_oldest_of_the_tied():
    b = EliteBand(2, [E(1.0, "old"), E(1.0, "newer")])
    assert b.consider(E(1.0, "entrant")) is True
    assert [e.fingerprint for e in b.elites] == ["newer", "entrant"]  # "old" evicted


def test_semantic_duplicate_is_rejected_even_if_fitter():
    b = EliteBand(3, [E(1.0, "same")])
    assert b.consider(E(9.0, "same")) is False
    assert len(b) == 1 and b.best().fitness == 1.0


def test_missing_fingerprint_is_never_a_duplicate():
    b = EliteBand(3)
    assert b.consider(E(1.0, None)) and b.consider(E(1.0, None))
    assert len(b) == 2


def test_k1_is_single_winner_worse_rejected_equal_adopted_better_adopted():
    b = EliteBand(1, [E(1.0, "a")])
    assert b.consider(E(0.9, "b")) is False
    assert b.consider(E(1.0, "c")) is True   # tie adopted
    assert b.consider(E(1.5, "d")) is True
    assert len(b) == 1 and b.best().fitness == 1.5


def test_best_breaks_exact_ties_toward_most_recent():
    b = EliteBand(3, [E(2.0, "a"), E(2.0, "b")])
    assert b.best().fingerprint == "b"


def test_pick_parent_is_deterministic_for_a_given_rng_seed():
    b = EliteBand(3, [E(1.0, "a"), E(2.0, "b"), E(3.0, "c")])
    picks1 = [b.pick_parent(random.Random(f"0:{g}")).fingerprint for g in range(20)]
    picks2 = [b.pick_parent(random.Random(f"0:{g}")).fingerprint for g in range(20)]
    assert picks1 == picks2
    assert len(set(picks1)) > 1  # actually samples across the band, not just the best


def test_pick_parent_on_empty_band_is_none():
    assert EliteBand(3).pick_parent(random.Random(0)) is None


def test_round_trip_preserves_order():
    b = EliteBand(3, [E(3.0, "a"), E(1.0, "b"), E(2.0, "c")])
    b2 = EliteBand.from_dicts(3, b.to_dicts())
    assert [e.fingerprint for e in b2.elites] == ["a", "b", "c"]


def test_invalid_construction_raises():
    with pytest.raises(ValueError):
        EliteBand(0)
    with pytest.raises(ValueError):
        EliteBand(1, [E(1.0, "a"), E(2.0, "b")])


def test_ablation_label():
    assert ablation_label(1) == "single_winner_k1"
    assert ablation_label(3) == "elite_band_k3"
