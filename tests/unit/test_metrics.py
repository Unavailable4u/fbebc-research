from delta.admission.metrics import (
    normalized_tree_edit_distance,
    semantic_fingerprint,
    edit_metrics,
)

A = "def f(x):\n    '''original docstring'''\n    return x + 1\n"
B = "def f(x):\n    '''original docstring'''\n    return x + 1\n"  # identical
C = "def f(x):\n    '''a completely different docstring, much longer'''\n    return x + 1\n"  # docstring reworded
D = "def f(x):\n    '''original docstring'''\n    return x * 2\n"  # semantic change


def test_identical_source_zero_distance():
    assert normalized_tree_edit_distance(A, B) == 0.0


def test_docstring_reword_is_zero_distance():
    # canonical_ast blanks an EXISTING docstring's text, so rewording it must
    # not register as a structural mutation. (Adding a docstring where none
    # existed before is a different case: that inserts a real Expr/Constant
    # node and correctly does register as structural change.)
    assert normalized_tree_edit_distance(A, C) == 0.0


def test_semantic_change_nonzero_distance():
    d = normalized_tree_edit_distance(A, D)
    assert d > 0.0


def test_fingerprint_stable_across_docstring_reword():
    assert semantic_fingerprint(A) == semantic_fingerprint(C)


def test_fingerprint_differs_on_semantic_change():
    assert semantic_fingerprint(A) != semantic_fingerprint(D)


def test_edit_metrics_shape():
    m = edit_metrics(A, D, A)
    for key in (
        "ast_distance_parent", "ast_distance_p0", "token_diff_parent",
        "nodes_added", "nodes_removed", "max_depth_delta", "semantic_fingerprint",
    ):
        assert key in m
    assert m["ast_distance_parent"] > 0.0
    assert m["ast_distance_p0"] > 0.0


def test_edit_metrics_zero_for_no_change():
    m = edit_metrics(A, A, A)
    assert m["ast_distance_parent"] == 0.0
    assert m["ast_distance_p0"] == 0.0
    assert m["token_diff_parent"] == 0
    assert m["nodes_added"] == 0
    assert m["nodes_removed"] == 0
