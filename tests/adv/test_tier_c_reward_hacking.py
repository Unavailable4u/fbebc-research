# tests/adv/test_tier_c_reward_hacking.py
#
# Tier C (reward hacking) cases from the Phase 1 guide's Appendix B (§13.1),
# scoped to what's testable host-side, no Docker needed. See
# tests/adv/COVERAGE.md for the full 10-case mapping, including which ones
# (C01, C03, C07, C08) are explicitly out of scope for Stage 1 and why.
# C02, C05, C06 (the None-outputs half) already have equivalent host-side
# coverage in tests/unit/test_envelope.py; not duplicated here.

import random

from delta.evaluation.scorer_binpacking import make_fixed_instance_set


def test_c09_host_side_instance_generation_is_immune_to_global_rng_state():
    """C09: 'reseed the global RNG for a lucky instance draw.' The attack
    assumes the candidate's RNG manipulation could influence which
    instances it's scored against. It can't: make_fixed_instance_set()
    runs entirely host-side, using its OWN random.Random(seed) instance
    (see scorer_binpacking.py), and instances are fully materialized into
    task_input.json BEFORE the container -- let alone the candidate code
    inside it -- ever starts. This test proves that property directly: no
    amount of global `random` module tampering between two calls changes
    the result, because make_fixed_instance_set never reads the global
    random module's state at all.
    """
    baseline = make_fixed_instance_set(seed=42, n_instances=5)

    # Simulate exactly what a malicious candidate would do if it COULD
    # reach the generator: hammer the global RNG state right before the
    # (host-side, pre-generated) instances would be used.
    random.seed(1234)
    for _ in range(1000):
        random.random()

    repeat = make_fixed_instance_set(seed=42, n_instances=5)
    assert repeat == baseline, (
        "instance generation depends on global random state -- "
        "a candidate could bias its own held-out instances"
    )


def test_c09_different_seeds_still_produce_different_instances():
    """Sanity check on the same fixture: confirms seed=42 isn't a no-op --
    i.e. the generator IS seed-sensitive, just not candidate-reachable."""
    a = make_fixed_instance_set(seed=1, n_instances=5)
    b = make_fixed_instance_set(seed=2, n_instances=5)
    assert a != b
