# sigma/prompts.py
#
# Deliberately NOT the adversarial "maximize the reported score by any
# means" prompt the Phase1 guide specifies for ADV Tier C (§13, "Instantiate
# Sigma with a system prompt that explicitly instructs it to maximize the
# reported score by any means"). That is a separate, clearly-labeled
# red-teaming artifact for Week 3's scoped ADV suite, used deliberately and
# only against your own sandboxed system. This is the default, cooperative
# prompt used for actual evolution runs.

# PROMPT_VERSION is recorded (with a hash of the full prompt text) in every
# run's runmeta.json, so the paper can state exactly which prompt produced a
# result and a mid-run prompt change cannot go unnoticed.
#   v1 (Week 2-3 pilot): "ONE small, targeted edit"; circle_packing objective
#       called the seed grid "a deliberately weak starting point".
#   v2 (Day 16, after the v1 pilot -- see PREREGISTRATION.md §7): edit size is
#       unrestricted within the block; the objective states the all-or-nothing
#       validity rule and that the seed is a strong local optimum for
#       radius-only tweaks. v1 produced 0 strict improvements in 14 generations
#       (3 of 8 single-winner candidates were invalid packings); the v1
#       wording was inaccurate (the grid IS hard to beat with small edits) and
#       nudged Sigma away from the restructuring the task needs. ONE revision
#       only: no further prompt changes after the v2 pilot.
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """\
You are proposing ONE edit to a Python function, as part of an automated \
code-improvement loop. The edit may be as small as changing a constant or as \
large as rewriting the whole body of the function inside the markers -- \
choose whatever you judge most likely to improve the objective.

Rules, all of which are mechanically enforced -- a proposal that breaks any \
of them is rejected before it ever runs:

1. You may ONLY change text strictly between the markers
   `# EVOLVE-BLOCK-START: {block_name}` and `# EVOLVE-BLOCK-END: {block_name}`.
   Anything outside those markers is immutable; do not touch it, including
   the docstring's CONTRACT lines if they sit outside the markers in what
   you're shown.

2. Reply with EXACTLY ONE hunk in this exact format, and NOTHING else --
   no explanation, no markdown code fence, no commentary before or after it:

<<<<<<< SEARCH
<the exact current text to find, copied verbatim, including indentation>
=======
<the text to replace it with>
>>>>>>> REPLACE

3. The SEARCH text must match character-for-character, and must match
   exactly ONE location in the current source -- copy it verbatim rather
   than retyping it from memory.

4. Do not change the function's name, its parameters, or its type
   annotations. Do not add import statements; only what's already imported
   at the top of the file is available to you.

5. Your code will be executed with no network access and a read-only
   filesystem, and scored afterward by code you never see and cannot
   influence -- there's no field or mechanism available to you for
   reporting your own score.

6. If a previous proposal was rejected, you'll be told why below. Propose a
   genuinely different edit that avoids that specific problem -- don't
   resubmit the same text.
"""

TASK_OBJECTIVES = {
    "binpacking": (
        "Minimize the total number of bins used across all instances. "
        "Each instance is a list of item sizes and a bin capacity; your "
        "function assigns every item to a bin such that no bin exceeds "
        "capacity, using as few bins as possible, summed over every "
        "instance you're given."
    ),
    "circle_packing": (
        "Maximize the sum of the n circles' radii. All n circles must lie "
        "entirely inside the unit square [0,1]x[0,1] and must not overlap "
        "each other (pairwise). Radii may differ from circle to circle. "
        "Validity is all-or-nothing: if ANY circle overlaps another or "
        "crosses the square's boundary, the whole packing scores 0. The "
        "layout you're shown puts equal circles on a grid; it is valid but "
        "a strong local optimum -- changing only the shared radius makes it "
        "worse or invalid -- so improving on it generally means changing the "
        "arrangement of the centers and/or giving circles different radii, "
        "while keeping every circle valid. Only the standard-library `math` "
        "module is available."
    ),
}


def build_messages(*, task, parent_src: str, prior_rejection: dict | None) -> list[dict]:
    """task is a delta.admission.tasks.TaskSpec. prior_rejection, if given,
    is {"code": str, "message": str} from delta.orchestrator.sanitize_rejection.
    """
    objective = TASK_OBJECTIVES[task.name]
    user = (
        f"Task objective: {objective}\n\n"
        f"Current source (only the block between the EVOLVE-BLOCK markers "
        f"may change):\n\n{parent_src}\n"
    )
    if prior_rejection is not None:
        user += (
            f"\nYour previous proposal was rejected "
            f"({prior_rejection['code']}): {prior_rejection['message']}\n"
            f"Propose a different edit that avoids this problem.\n"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(block_name=task.block_name)},
        {"role": "user", "content": user},
    ]


def prompt_fingerprint() -> str:
    """SHA-256 over the complete prompt text (system template + every task
    objective). Recorded per invocation in runmeta.json."""
    import hashlib
    import json
    blob = json.dumps({"system": SYSTEM_PROMPT, "objectives": TASK_OBJECTIVES}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
