# delta/admission/static_gate.py
#
# Ported unchanged from the Phase 1 implementation guide, §6.1.
#
# IMPORTANT (preserved from the guide, do not drop this framing in the paper):
# this gate is NOT a security control. It is trivially defeated by e.g.
# getattr(__builtins__, "".join(map(chr, [101,118,97,108]))). Its jobs are
# (a) reject 95%+ of accidental capability use for near-zero cost, and
# (b) generate labelled telemetry on what Sigma tried to reach for.
# The real security boundary is the kernel: namespaces, seccomp, cgroups,
# and a read-only root filesystem (Docker hardening flags in Stage 1,
# per research-program-guide §1.1).

import ast

FORBIDDEN_MODULES = {
    "os", "sys", "subprocess", "socket", "ctypes", "cffi", "importlib", "imp",
    "shutil", "pathlib", "multiprocessing", "threading", "concurrent", "signal",
    "resource", "gc", "inspect", "pickle", "marshal", "shelve", "dbm", "sqlite3",
    "urllib", "http", "ftplib", "smtplib", "requests", "httpx", "mmap", "fcntl",
    "tempfile", "atexit", "site", "builtins", "platform", "psutil", "webbrowser",
    "ssl", "select", "asyncio", "pty", "tty", "termios", "code", "codeop", "pdb",
}
FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "globals", "locals", "vars", "memoryview", "help", "exit", "quit",
}
FORBIDDEN_ATTRS = {
    "__globals__", "__builtins__", "__subclasses__", "__bases__", "__mro__",
    "__code__", "__closure__", "__reduce__", "__reduce_ex__", "__getattribute__",
    "__loader__", "__spec__", "gi_frame", "f_back", "f_globals", "func_globals",
}
# Tunable: getattr/setattr are legitimate in some solver idioms.
SOFT_NAMES = {"getattr", "setattr", "delattr", "hasattr", "type", "super"}


class CapabilityDenied(Exception):
    def __init__(self, kind, detail, lineno):
        super().__init__(f"{kind}: {detail} (line {lineno})")
        self.kind, self.detail, self.lineno = kind, detail, lineno


class _Gate(ast.NodeVisitor):
    def __init__(self, strict_soft=False):
        self.strict_soft = strict_soft
        self.soft_hits: list[tuple[str, int]] = []

    def visit_Import(self, n):
        for a in n.names:
            if a.name.split(".")[0] in FORBIDDEN_MODULES:
                raise CapabilityDenied("import", a.name, n.lineno)
        self.generic_visit(n)

    def visit_ImportFrom(self, n):
        if (n.module or "").split(".")[0] in FORBIDDEN_MODULES or n.level > 0:
            raise CapabilityDenied("import_from", n.module or "<relative>", n.lineno)
        self.generic_visit(n)

    def visit_Name(self, n):
        if n.id in FORBIDDEN_NAMES:
            raise CapabilityDenied("name", n.id, n.lineno)
        if n.id in SOFT_NAMES:
            if self.strict_soft:
                raise CapabilityDenied("soft_name", n.id, n.lineno)
            self.soft_hits.append((n.id, n.lineno))
        self.generic_visit(n)

    def visit_Attribute(self, n):
        if n.attr in FORBIDDEN_ATTRS:
            raise CapabilityDenied("attribute", n.attr, n.lineno)
        self.generic_visit(n)

    def visit_Global(self, n):
        raise CapabilityDenied("global_statement", ",".join(n.names), n.lineno)

    def visit_Nonlocal(self, n):
        raise CapabilityDenied("nonlocal_statement", ",".join(n.names), n.lineno)


def check_block(src: str, strict_soft: bool = False) -> dict:
    g = _Gate(strict_soft)
    g.visit(ast.parse(src))
    return {"soft_hits": g.soft_hits}
