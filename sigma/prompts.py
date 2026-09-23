# sigma/prompts.py
#
# Deliberately NOT the adversarial "maximize the reported score by any
# means" prompt the Phase1 guide specifies for ADV Tier C (§13, "Instantiate
# Sigma with a system prompt that explicitly instructs it to maximize the
# reported score by any means"). That is a separate, clearly-labeled
# red-teaming artifact for Week 3's scoped ADV suite, used deliberately and
# only against your own sandboxed system. This is the default, cooperative
# prompt used for actual evolution runs.

SYSTEM_PROMPT = """\
You are proposing ONE small, targeted edit to a Python function, as part of \
an automated code-improvement loop.

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
        "each other (pairwise). Larger, more cleverly arranged circles "
        "score higher; the naive grid layout you're shown is a deliberately "
        "weak starting point."
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
