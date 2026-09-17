import pytest

from delta.admission.blocks import parse_blocks, immutable_regions, BlockError


SIMPLE = """\
import math

# EVOLVE-BLOCK-START: core
def f(x):
    return x + 1
# EVOLVE-BLOCK-END: core

def g():
    return 2
"""


def test_parse_single_block():
    blocks = parse_blocks(SIMPLE)
    assert len(blocks) == 1
    assert blocks[0].name == "core"


def test_immutable_regions_excludes_body_only():
    blocks = parse_blocks(SIMPLE)
    regions = immutable_regions(SIMPLE, blocks)
    joined = "\n".join(regions)
    assert "return x + 1" not in joined
    assert "def g():" in joined
    assert "EVOLVE-BLOCK-START: core" in joined
    assert "EVOLVE-BLOCK-END: core" in joined


def test_nested_blocks_rejected():
    src = """\
# EVOLVE-BLOCK-START: outer
# EVOLVE-BLOCK-START: inner
x = 1
# EVOLVE-BLOCK-END: inner
# EVOLVE-BLOCK-END: outer
"""
    with pytest.raises(BlockError, match="nested"):
        parse_blocks(src)


def test_unmatched_end_rejected():
    src = "x = 1\n# EVOLVE-BLOCK-END: core\n"
    with pytest.raises(BlockError, match="unmatched"):
        parse_blocks(src)


def test_unterminated_block_rejected():
    src = "# EVOLVE-BLOCK-START: core\nx = 1\n"
    with pytest.raises(BlockError, match="unterminated"):
        parse_blocks(src)


def test_no_block_rejected():
    with pytest.raises(BlockError, match="no EVOLVE-BLOCK"):
        parse_blocks("x = 1\n")


def test_marker_name_mismatch_rejected():
    src = """\
# EVOLVE-BLOCK-START: a
x = 1
# EVOLVE-BLOCK-END: b
"""
    with pytest.raises(BlockError, match="mismatch"):
        parse_blocks(src)


def test_duplicate_block_name_rejected():
    src = """\
# EVOLVE-BLOCK-START: dup
x = 1
# EVOLVE-BLOCK-END: dup
# EVOLVE-BLOCK-START: dup
y = 2
# EVOLVE-BLOCK-END: dup
"""
    with pytest.raises(BlockError, match="duplicate"):
        parse_blocks(src)


def test_multiple_named_blocks():
    src = """\
# EVOLVE-BLOCK-START: a
x = 1
# EVOLVE-BLOCK-END: a
mid = True
# EVOLVE-BLOCK-START: b
y = 2
# EVOLVE-BLOCK-END: b
"""
    blocks = parse_blocks(src)
    assert [b.name for b in blocks] == ["a", "b"]
