"""Running scoring code an LLM wrote, safely enough for this project.

The code must define `score(plan) -> float` and may use plain Python and `math` only. Before it
runs, its syntax tree is checked against an allow-list: no imports, no while loops, no classes,
no names or attributes starting with "_", no file, network or eval access. Builtins are limited,
and range() is capped, so a function can only read the plan and compute. The checks in
leg.advice run each function in a separate process with a time limit before it is ever approved.
"""
from __future__ import annotations

import ast
import copy
import math

ALLOWED_NODES = (
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AugAssign,
    ast.AnnAssign, ast.Expr, ast.If, ast.For, ast.Break, ast.Continue, ast.Pass, ast.comprehension,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.BoolOp, ast.BinOp, ast.UnaryOp,
    ast.Compare, ast.IfExp, ast.Call, ast.Name, ast.Load, ast.Store, ast.Constant, ast.Subscript,
    ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Attribute, ast.Lambda, ast.keyword,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is,
    ast.IsNot, ast.Starred,
)
# Read-only access plus changes to the function's own lists, sets and dicts (each call gets its own
# copy of the plan, so nothing leaks between functions). No str.format: its field syntax reaches attributes.
ALLOWED_ATTRS = ({"get", "items", "keys", "values", "count", "index", "lower", "upper", "strip",
                  "startswith", "endswith", "split", "join",
                  "append", "extend", "insert", "pop", "remove", "sort", "reverse",
                  "update", "setdefault", "copy", "add", "discard"}
                 | {n for n in dir(math) if not n.startswith("_")})
MAX_RANGE = 100_000


def _range(*a):
    r = range(*a)
    if len(r) > MAX_RANGE:
        raise ValueError(f"range larger than {MAX_RANGE}")
    return r


SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "enumerate": enumerate,
    "filter": filter, "float": float, "int": int, "isinstance": isinstance, "len": len, "list": list,
    "map": map, "max": max, "min": min, "range": _range, "reversed": reversed, "round": round,
    "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "True": True, "False": False, "None": None,
}


class UnsafeCode(ValueError):
    pass


def check_code(code: str) -> None:
    """Raise UnsafeCode if the code uses anything outside the allow-list or has no score()."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCode(f"syntax error: {e}") from e
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise UnsafeCode(f"not allowed: {type(node).__name__} (line {getattr(node, 'lineno', '?')})")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise UnsafeCode(f"not allowed: name {node.id!r}")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr not in ALLOWED_ATTRS:
                raise UnsafeCode(f"not allowed: attribute .{node.attr}")
    top = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not any(f.name == "score" and len(f.args.args) == 1 for f in top):
        raise UnsafeCode("must define score(plan)")
    if any(not isinstance(n, (ast.FunctionDef, ast.Assign, ast.Expr)) for n in tree.body):
        raise UnsafeCode("only functions and constants at the top level")


def compile_score(code: str):
    """Check, then return the score function."""
    check_code(code)
    env = {"__builtins__": SAFE_BUILTINS, "math": math}
    exec(compile(code, "<advice score>", "exec"), env)  # noqa: S102 - allow-listed above
    return env["score"]


def run_score(code: str, plan: dict) -> float:
    """Score one plan. The function gets its own copy, so it cannot change what others see."""
    v = compile_score(code)(copy.deepcopy(plan))
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isnan(v):
        raise ValueError(f"score() returned {v!r}, not a number")
    return float(v)
