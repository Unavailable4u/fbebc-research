# delta/admission/contracts.py
#
# Ported from the Phase 1 implementation guide, §7.3, with one adaptation:
# the guide's `PINNED = {"candidate_solver"}` is a single-task global. Stage 1
# runs two tasks (research-program-guide §1.2: bin-packing warm-up +
# circle-packing primary), each with a differently-named EVOLVE-BLOCK entry
# point, so PINNED becomes a per-call parameter (see tasks.py) rather than a
# module-level constant. The verification logic itself is unchanged.

import ast

from .errors import AdmissionError


def _sig(fn: ast.FunctionDef | ast.AsyncFunctionDef):
    a = fn.args
    ann = lambda x: ast.dump(x.annotation) if x.annotation else None
    return {
        "posonly": [(x.arg, ann(x)) for x in a.posonlyargs],
        "args": [(x.arg, ann(x)) for x in a.args],
        "vararg": a.vararg.arg if a.vararg else None,
        "kwonly": [(x.arg, ann(x)) for x in a.kwonlyargs],
        "kwarg": a.kwarg.arg if a.kwarg else None,
        "n_defaults": len(a.defaults),
        "n_kwdefaults": len([d for d in a.kw_defaults if d is not None]),
        "returns": ast.dump(fn.returns) if fn.returns else None,
        "decorators": [ast.dump(d) for d in fn.decorator_list],
    }


def qualified_signatures(src: str) -> dict:
    tree, out = ast.parse(src), {}

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = f"{prefix}{child.name}"
                out[q] = _sig(child)
                walk(child, q + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")

    walk(tree)
    return out


def module_imports(src: str) -> set[str]:
    names = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names |= {f"{n.module}.{a.name}" for a in n.names}
    return names


def verify_contract(parent_src: str, child_src: str, pinned_names: set[str]) -> None:
    ps, cs = qualified_signatures(parent_src), qualified_signatures(child_src)
    for name in pinned_names:
        if name not in cs:
            raise AdmissionError("E_CONTRACT_VIOLATION", f"{name} removed")
        if ps.get(name) != cs[name]:
            raise AdmissionError("E_CONTRACT_VIOLATION", f"{name} signature changed")
    if module_imports(parent_src) != module_imports(child_src):
        raise AdmissionError("E_CONTRACT_VIOLATION", "module import set changed")
