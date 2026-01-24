#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Limits:
    max_file_loc: int
    max_func_loc: int
    max_cc: int


REPO_ROOT = Path(__file__).resolve().parents[1]

# Hard caps (should stay small forever).
STRICT_FILES: dict[str, Limits] = {
    "mcp_servers/browser/server/registry.py": Limits(max_file_loc=200, max_func_loc=200, max_cc=20),
    "mcp_servers/browser/session.py": Limits(max_file_loc=200, max_func_loc=200, max_cc=20),
}

# Known large compatibility/definition modules: allow, but prevent further blow-ups.
ALLOWLIST_FILES: dict[str, Limits] = {
    # Legacy monoliths: cap LOC, do not enforce per-fn metrics yet.
    "mcp_servers/browser/server/flow/handler.py": Limits(max_file_loc=3800, max_func_loc=100000, max_cc=100000),
    "mcp_servers/browser/server/handlers/unified.py": Limits(max_file_loc=3800, max_func_loc=100000, max_cc=100000),
    "mcp_servers/browser/session_manager.py": Limits(max_file_loc=2200, max_func_loc=100000, max_cc=100000),
    "mcp_servers/browser/server/definitions_unified.py": Limits(max_file_loc=2200, max_func_loc=100000, max_cc=100000),
    "mcp_servers/browser/server/definitions.py": Limits(max_file_loc=1400, max_func_loc=100000, max_cc=100000),
    # Flow-built handlers: pragmatic caps (still enforceable).
    "mcp_servers/browser/server/run/handler.py": Limits(max_file_loc=600, max_func_loc=500, max_cc=100),
}

# Defaults for everything else.
DEFAULT_LIMITS = Limits(max_file_loc=800, max_func_loc=300, max_cc=60)

SKIP_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "vendor", "dist", "build", "node_modules"}


def _iter_python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _limits_for(rel: str) -> Limits:
    if rel in STRICT_FILES:
        return STRICT_FILES[rel]
    if rel in ALLOWLIST_FILES:
        return ALLOWLIST_FILES[rel]
    return DEFAULT_LIMITS


class _CcVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.cc = 1

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self.cc += len(getattr(node, "handlers", []) or [])
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        # a and b and c => 2 decision points
        try:
            self.cc += max(0, len(node.values) - 1)
        except Exception:
            self.cc += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        self.cc += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:  # noqa: N802
        self.cc += 1
        self.cc += len(getattr(node, "ifs", []) or [])
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        # Each case is a branch.
        self.cc += len(getattr(node, "cases", []) or [])
        self.generic_visit(node)


def _cc_for(node: ast.AST) -> int:
    v = _CcVisitor()
    v.visit(node)
    return int(v.cc)


def _loc_for(node: ast.AST) -> int:
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if isinstance(lineno, int) and isinstance(end_lineno, int) and end_lineno >= lineno:
        return end_lineno - lineno + 1
    return 0


def main() -> int:
    errors: list[str] = []
    # Keep the gate focused on architecture-critical code paths (cheap + actionable).
    files: list[Path] = []
    files += _iter_python_files(REPO_ROOT / "mcp_servers" / "browser" / "server")
    files += [
        REPO_ROOT / "mcp_servers" / "browser" / "session.py",
        REPO_ROOT / "mcp_servers" / "browser" / "session_helpers.py",
        REPO_ROOT / "mcp_servers" / "browser" / "session_cdp.py",
        REPO_ROOT / "mcp_servers" / "browser" / "session_tier0.py",
        REPO_ROOT / "mcp_servers" / "browser" / "browser_session.py",
        REPO_ROOT / "mcp_servers" / "browser" / "session_manager.py",
        REPO_ROOT / "mcp_servers" / "browser" / "runbook.py",
    ]
    files += [REPO_ROOT / "scripts" / "structure_gate.py"]
    seen: set[Path] = set()
    unique_files: list[Path] = []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        unique_files.append(f)

    for path in unique_files:
        rel = str(path.relative_to(REPO_ROOT))
        limits = _limits_for(rel)

        try:
            loc = len(path.read_text(encoding="utf-8").splitlines())
        except Exception as e:  # noqa: BLE001
            errors.append(f"{rel}: failed to read ({e})")
            continue
        if loc > limits.max_file_loc:
            errors.append(f"{rel}: file too large (loc={loc}, max={limits.max_file_loc})")

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as e:
            errors.append(f"{rel}: syntax error ({e})")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn = f"{rel}:{getattr(node, 'lineno', '?')}"
            fn_loc = _loc_for(node)
            if fn_loc and fn_loc > limits.max_func_loc:
                errors.append(f"{fn}: function too large (loc={fn_loc}, max={limits.max_func_loc})")
            cc = _cc_for(node)
            if cc > limits.max_cc:
                errors.append(f"{fn}: cyclomatic too high (cc={cc}, max={limits.max_cc})")

    if errors:
        print("== structure gate errors ==", file=sys.stderr)
        for e in errors:
            print(f"- {e}", file=sys.stderr)
        print(f"\nFAIL: structure gate ({len(errors)} error(s)).", file=sys.stderr)
        return 2

    print("OK: structure gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
