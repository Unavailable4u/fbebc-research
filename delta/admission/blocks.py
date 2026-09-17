# delta/admission/blocks.py
#
# Ported unchanged from the Phase 1 implementation guide, §7.1.
# This is one of the pieces the research-program-guide's cut table (§1.1)
# explicitly carries over as-is: "the EVOLVE-BLOCK parser and bounded
# applicator ... carry over unchanged."

import re
from dataclasses import dataclass

START = re.compile(r"^[ \t]*#[ \t]*EVOLVE-BLOCK-START(?:[ \t]*:[ \t]*(?P<name>[A-Za-z0-9_]+))?[ \t]*$")
END = re.compile(r"^[ \t]*#[ \t]*EVOLVE-BLOCK-END(?:[ \t]*:[ \t]*(?P<name>[A-Za-z0-9_]+))?[ \t]*$")


@dataclass(frozen=True)
class Block:
    name: str
    start_marker: int  # line index of START marker
    end_marker: int  # line index of END marker
    body: slice  # exclusive of both markers


class BlockError(ValueError):
    pass


def parse_blocks(src: str) -> list[Block]:
    lines = src.splitlines()
    blocks, open_at, open_name, seen = [], None, None, set()
    for i, line in enumerate(lines):
        if (m := START.match(line)):
            if open_at is not None:
                raise BlockError(f"nested EVOLVE-BLOCK at line {i + 1}")
            open_at, open_name = i, m.group("name") or f"block_{len(blocks)}"
        elif (m := END.match(line)):
            if open_at is None:
                raise BlockError(f"unmatched EVOLVE-BLOCK-END at line {i + 1}")
            name = m.group("name")
            if name and name != open_name:
                raise BlockError(f"marker name mismatch: {open_name} vs {name}")
            if open_name in seen:
                raise BlockError(f"duplicate block name {open_name}")
            seen.add(open_name)
            blocks.append(Block(open_name, open_at, i, slice(open_at + 1, i)))
            open_at, open_name = None, None
    if open_at is not None:
        raise BlockError("unterminated EVOLVE-BLOCK")
    if not blocks:
        raise BlockError("no EVOLVE-BLOCK found")
    return blocks


def immutable_regions(src: str, blocks: list[Block]) -> list[str]:
    """Everything outside block bodies, including the markers themselves."""
    lines, out, cursor = src.splitlines(), [], 0
    for b in blocks:
        out.append("\n".join(lines[cursor:b.start_marker + 1]))
        cursor = b.end_marker
    out.append("\n".join(lines[cursor:]))
    return out
