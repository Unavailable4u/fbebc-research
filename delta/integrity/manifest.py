# delta/integrity/manifest.py
#
# Ported unchanged from the Phase 1 implementation guide, §5.
# Stage 1 keeps the hash chain / manifest mechanism as-is (research-program-guide
# §1.1: "Keep the hash chain ... but drop the environment-fingerprint columns
# that only matter for timing claims"). Environment-fingerprint fields live in
# the ledger layer, not here, so this file is untouched by the Stage 1 scope cut.

import hashlib
import json
from pathlib import Path

WATCHED = ("*.py", "*.json", "*.sql", "*.toml", "*.txt", "Dockerfile", "*.seccomp.json")
SKIP_PARTS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}


def file_digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(roots: list[Path]) -> dict:
    entries: dict[str, str] = {}
    for root in roots:
        for pat in WATCHED:
            for p in sorted(root.rglob(pat)):
                if SKIP_PARTS & set(p.parts):
                    continue
                entries[str(p)] = file_digest(p)
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "fbebc.manifest.v1",
        "files": entries,
        "file_count": len(entries),
        "root_digest": hashlib.sha256(payload).hexdigest(),
    }


class IntegrityViolation(RuntimeError):
    pass


def verify(expected: dict, roots: list[Path]) -> dict:
    actual = build_manifest(roots)
    if actual["root_digest"] != expected["root_digest"]:
        added = set(actual["files"]) - set(expected["files"])
        removed = set(expected["files"]) - set(actual["files"])
        changed = {
            k
            for k in set(actual["files"]) & set(expected["files"])
            if actual["files"][k] != expected["files"][k]
        }
        raise IntegrityViolation(
            json.dumps(
                {"added": sorted(added), "removed": sorted(removed), "changed": sorted(changed)}
            )
        )
    return actual


def canonical_source(path: Path) -> str:
    """Formatting-stable read used to anchor P_0 (§4.3).

    Strips trailing whitespace per line and normalizes line endings.
    Deliberately does NOT reformat code (e.g. via a formatter), because
    reformatting would change the AST-distance baseline that every Gap-3
    drift metric in metrics.py is computed against.
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def p0_digest(path: Path) -> str:
    return hashlib.sha256(canonical_source(path).encode("utf-8")).hexdigest()
