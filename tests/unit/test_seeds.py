import importlib.util
import random

from delta.admission.blocks import parse_blocks
from delta.admission.contracts import qualified_signatures
from delta.admission.tasks import TASKS
from delta.evaluation.scorer_binpacking import score_binpacking, make_fixed_instance_set
from delta.evaluation.scorer_circle_packing import score_packing


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_task_seeds_parse_and_match_registry():
    for task_name, spec in TASKS.items():
        src = spec.seed_path.read_text()
        blocks = parse_blocks(src)
        assert [b.name for b in blocks] == [spec.block_name], task_name
        sigs = qualified_signatures(src)
        assert spec.pinned_names <= set(sigs), (task_name, sigs.keys())


def test_binpacking_p0_produces_valid_solutions():
    mod = _load_module(TASKS["binpacking"].seed_path, "binpacking_p0")
    instances = make_fixed_instance_set(seed=0, n_instances=5)
    rng = random.Random(0)
    results = mod.candidate_solver(instances, rng)
    assert len(results) == len(instances)
    by_id = {inst["instance_id"]: inst for inst in instances}
    for r in results:
        inst = by_id[r["instance_id"]]
        scored = score_binpacking(inst, r["solution"])
        assert scored["valid"], scored
        assert scored["bins_used"] >= 1


def test_circle_packing_p0_produces_valid_packing():
    mod = _load_module(TASKS["circle_packing"].seed_path, "circle_packing_p0")
    n = 26
    circles = mod.candidate_packing(n)
    scored = score_packing(circles, n)
    assert scored["valid"], scored
    assert scored["fitness"] > 0.0


def test_circle_packing_p0_matches_grid_math():
    mod = _load_module(TASKS["circle_packing"].seed_path, "circle_packing_p0")
    n = 26
    circles = mod.candidate_packing(n)
    assert len(circles) == n
    # Generation-0 seed is a fixed-radius grid; every radius should be identical.
    radii = {round(r, 12) for _, _, r in circles}
    assert len(radii) == 1
