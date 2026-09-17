from pathlib import Path

import pytest

from delta.integrity.manifest import build_manifest, verify, IntegrityViolation, p0_digest


@pytest.fixture
def sample_tree(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("z = 3\n")
    return tmp_path


def test_build_manifest_skips_pycache(sample_tree):
    m = build_manifest([sample_tree])
    assert m["file_count"] == 2
    assert not any("__pycache__" in k for k in m["files"])


def test_verify_passes_when_unchanged(sample_tree):
    expected = build_manifest([sample_tree])
    actual = verify(expected, [sample_tree])
    assert actual["root_digest"] == expected["root_digest"]


def test_verify_detects_tamper(sample_tree):
    expected = build_manifest([sample_tree])
    (sample_tree / "a.py").write_text("x = 999  # tampered\n")
    with pytest.raises(IntegrityViolation) as exc:
        verify(expected, [sample_tree])
    assert "a.py" in str(exc.value)
    assert '"changed"' in str(exc.value)


def test_verify_detects_added_file(sample_tree):
    expected = build_manifest([sample_tree])
    (sample_tree / "new.py").write_text("w = 1\n")
    with pytest.raises(IntegrityViolation) as exc:
        verify(expected, [sample_tree])
    assert "new.py" in str(exc.value)


def test_verify_detects_removed_file(sample_tree):
    expected = build_manifest([sample_tree])
    (sample_tree / "a.py").unlink()
    with pytest.raises(IntegrityViolation) as exc:
        verify(expected, [sample_tree])
    assert "a.py" in str(exc.value)


def test_p0_digest_ignores_trailing_whitespace(tmp_path):
    f1 = tmp_path / "one.py"
    f2 = tmp_path / "two.py"
    f1.write_text("x = 1   \ny = 2\n")
    f2.write_text("x = 1\ny = 2\n")
    assert p0_digest(f1) == p0_digest(f2)
