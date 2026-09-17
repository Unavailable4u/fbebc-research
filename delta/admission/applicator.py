# delta/admission/applicator.py
#
# Ported unchanged from the Phase 1 implementation guide, §7.2 — this is one
# of the pieces research-program-guide §1.1 names as carrying over as-is.
# Only change from the guide's listing: AdmissionError now imported from
# errors.py instead of being redefined locally (see errors.py docstring).
#
# The critical property, stated in the guide and preserved here: the
# applicator runs on the host, and it verifies its own output by re-deriving
# the immutable regions and comparing them byte-for-byte. It does not trust
# its own patching logic; it trusts the post-condition.

import ast
import re

from .blocks import parse_blocks, immutable_regions
from .errors import AdmissionError

DIFF = re.compile(
    r"<{7} SEARCH\n(?P<search>.*?)\n={7}\n(?P<replace>.*?)\n>{7} REPLACE",
    re.DOTALL,
)
MAX_DIFF_BYTES = 64_000
MAX_HUNKS = 8


def apply_bounded_diff(parent_src: str, diff_text: str) -> str:
    if len(diff_text.encode()) > MAX_DIFF_BYTES:
        raise AdmissionError("E_MALFORMED_DIFF", "diff exceeds byte cap")

    hunks = list(DIFF.finditer(diff_text))
    if not hunks:
        raise AdmissionError("E_MALFORMED_DIFF", "no SEARCH/REPLACE hunk found")
    if len(hunks) > MAX_HUNKS:
        raise AdmissionError("E_MALFORMED_DIFF", f"{len(hunks)} hunks > cap {MAX_HUNKS}")

    blocks = parse_blocks(parent_src)
    before_regions = immutable_regions(parent_src, blocks)
    lines = parent_src.splitlines(keepends=True)
    # Character offset of the start of each line, for span containment tests.
    offsets, acc = [], 0
    for ln in lines:
        offsets.append(acc)
        acc += len(ln)
    offsets.append(acc)

    src = parent_src
    for h in hunks:
        search, replace = h.group("search"), h.group("replace")
        if not search.strip():
            raise AdmissionError("E_MALFORMED_DIFF", "empty SEARCH block")

        # Re-derive spans each iteration; earlier hunks shift offsets.
        blocks_now = parse_blocks(src)
        lines_now = src.splitlines(keepends=True)
        off_now, a = [], 0
        for ln in lines_now:
            off_now.append(a)
            a += len(ln)
        off_now.append(a)

        hits = []
        for b in blocks_now:
            lo, hi = off_now[b.body.start], off_now[b.body.stop]
            region = src[lo:hi]
            start = region.find(search)
            while start != -1:
                hits.append((b.name, lo + start))
                nxt = region.find(search, start + 1)
                if nxt != -1:
                    hits.append((b.name, lo + nxt))  # ambiguity detected
                start = -1
        if len(hits) == 0:
            if search in src:
                raise AdmissionError(
                    "E_BOUNDARY_VIOLATION", "SEARCH matches only outside an EVOLVE-BLOCK"
                )
            raise AdmissionError("E_MALFORMED_DIFF", "SEARCH text not found")
        if len(hits) > 1:
            raise AdmissionError("E_AMBIGUOUS_MATCH", f"{len(hits)} matches; SEARCH must be unique")

        _, pos = hits[0]
        src = src[:pos] + replace + src[pos + len(search):]

    # -- Post-conditions. These, not the patch logic, are the guarantee. --
    try:
        blocks_after = parse_blocks(src)
    except Exception as e:
        raise AdmissionError("E_MARKER_FORGERY", str(e))

    if [b.name for b in blocks_after] != [b.name for b in blocks]:
        raise AdmissionError("E_MARKER_FORGERY", "block set or order changed")

    if immutable_regions(src, blocks_after) != before_regions:
        raise AdmissionError("E_BOUNDARY_VIOLATION", "immutable region byte mismatch")

    try:
        ast.parse(src)
    except SyntaxError as e:
        raise AdmissionError("E_SYNTAX", f"line {e.lineno}: {e.msg}")

    return src
