# delta/admission/metrics.py
#
# Ported from the Phase 1 implementation guide, §7.4 ("Freeze this now.
# Phase 2's fairness bound is only defensible if the ruler predates the
# results.") Frozen before any real mutation data exists, per Stage 1
# discipline.
#
# ONE DOCUMENTED DEVIATION FROM THE GUIDE:
# The guide calls `_zhang_shasha_or_levenshtein(a, b)` and says "supply your
# implementation." True Zhang-Shasha tree edit distance is a nontrivial
# O(n^3)-ish algorithm; for Stage 1's time budget we supply Levenshtein
# distance over the linearized node-type sequence instead of true tree edit
# distance. This is a real, disclosed simplification (not a silent one):
# it measures a different, cheaper notion of "how different are these two
# canonical ASTs" that is monotonically related to true tree edit distance
# for small, mostly-linear diffs (the common case for LLM SEARCH/REPLACE
# mutations against a single EVOLVE-BLOCK) but can diverge for large
# subtree reorderings. State this plainly in the paper's Methods/Limitations
# section, per the research-program-guide's statistical-honesty rules. If
# Stage 2 or a resubmission needs the stronger guarantee, swap in a real
# Zhang-Shasha implementation behind the same `normalized_tree_edit_distance`
# signature — the frozen *interface* (§14) is what downstream phases import,
# not this implementation.

import ast
import hashlib
import tokenize
import io


def canonical_ast(src: str) -> ast.AST:
    """Formatting-invariant, semantics-preserving normalization."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        # Docstrings drift under LLM rewriting and are not semantic edits.
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body[0].value.value = ""
        for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            if hasattr(node, attr):
                setattr(node, attr, 0)
    return tree


def node_sequence(tree: ast.AST) -> list[str]:
    """Structure-bearing linearization: type + operator/constant kind, not identifiers."""
    seq = []
    for n in ast.walk(tree):
        tag = type(n).__name__
        if isinstance(n, ast.Constant):
            tag += f":{type(n.value).__name__}"
        elif isinstance(n, (ast.BinOp, ast.UnaryOp, ast.BoolOp)):
            tag += f":{type(n.op).__name__}"
        seq.append(tag)
    return seq


def _levenshtein(a: list[str], b: list[str]) -> int:
    """Iterative DP edit distance over sequences, O(len(a)*len(b)) time,
    O(min(len(a),len(b))) space. This stands in for Zhang-Shasha — see the
    module docstring for why, and the disclosure obligation that comes with it.
    """
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, start=1):
            cost = 0 if x == y else 1
            cur[j] = min(
                prev[j] + 1,  # deletion
                cur[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = cur
    return prev[-1]


def normalized_tree_edit_distance(a_src: str, b_src: str) -> float:
    """Levenshtein distance over linearized canonical-AST node sequences,
    normalized by max sequence length -> [0, 1]. See module docstring:
    this is Stage 1's disclosed stand-in for true Zhang-Shasha tree edit
    distance, frozen before any mutation data exists.
    """
    a, b = node_sequence(canonical_ast(a_src)), node_sequence(canonical_ast(b_src))
    d = _levenshtein(a, b)
    return d / max(len(a), len(b), 1)


def semantic_fingerprint(src: str) -> str:
    return hashlib.sha256("|".join(node_sequence(canonical_ast(src))).encode()).hexdigest()


def _token_sequence(src: str) -> list[str]:
    """Token-level (not AST-level) linearization, used for token_diff_parent."""
    toks = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                             tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
                             tokenize.ENDMARKER):
                continue
            toks.append(tok.string)
    except tokenize.TokenizeError:
        pass
    return toks


def _tree_depth(tree: ast.AST) -> int:
    def depth(node) -> int:
        children = list(ast.iter_child_nodes(node))
        if not children:
            return 1
        return 1 + max(depth(c) for c in children)

    return depth(tree)


def edit_metrics(parent_src: str, child_src: str, p0_src: str) -> dict:
    """Per the Phase 1 guide §7.4 / §14 frozen interface. Recorded for every
    admitted candidate, both vs. parent and vs. P_0."""
    parent_tree = canonical_ast(parent_src)
    child_tree = canonical_ast(child_src)

    parent_seq = node_sequence(parent_tree)
    child_seq = node_sequence(child_tree)

    ast_distance_parent = normalized_tree_edit_distance(parent_src, child_src)
    ast_distance_p0 = normalized_tree_edit_distance(p0_src, child_src)

    token_diff_parent = _levenshtein(_token_sequence(parent_src), _token_sequence(child_src))

    parent_counts: dict[str, int] = {}
    child_counts: dict[str, int] = {}
    for tag in parent_seq:
        parent_counts[tag] = parent_counts.get(tag, 0) + 1
    for tag in child_seq:
        child_counts[tag] = child_counts.get(tag, 0) + 1
    nodes_added = sum(max(0, child_counts.get(k, 0) - parent_counts.get(k, 0)) for k in child_counts)
    nodes_removed = sum(max(0, parent_counts.get(k, 0) - child_counts.get(k, 0)) for k in parent_counts)

    max_depth_delta = _tree_depth(child_tree) - _tree_depth(parent_tree)

    return {
        "ast_distance_parent": ast_distance_parent,
        "ast_distance_p0": ast_distance_p0,
        "token_diff_parent": token_diff_parent,
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "max_depth_delta": max_depth_delta,
        "semantic_fingerprint": semantic_fingerprint(child_src),
    }
