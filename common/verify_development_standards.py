"""Check machine-decidable repository development standards."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (REPO_ROOT / "common", REPO_ROOT / "projects")
EXCLUDED_PARTS = {"history", "legacy", ".venv", "__pycache__"}


def active_files(suffix: str) -> list[Path]:
    return sorted(
        path
        for root in SOURCE_ROOTS
        for path in root.rglob(f"*{suffix}")
        if not EXCLUDED_PARTS.intersection(path.relative_to(REPO_ROOT).parts)
    )


def location(path: Path, line: int) -> str:
    return f"{path.relative_to(REPO_ROOT).as_posix()}:{line}"


def keyword_names(call: ast.Call) -> set[str]:
    return {item.arg for item in call.keywords if item.arg is not None}


def is_subprocess_call(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "subprocess"
        and call.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
    )


def check_python() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    reviews: list[str] = []
    for path in active_files(".py"):
        source = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exception:
            errors.append(f"{location(path, exception.lineno or 1)} Python syntax error: {exception.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                errors.append(f"{location(path, node.lineno)} wildcard import")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defaults = [*node.args.defaults, *[item for item in node.args.kw_defaults if item is not None]]
                if any(isinstance(item, (ast.List, ast.Dict, ast.Set)) for item in defaults):
                    errors.append(f"{location(path, node.lineno)} mutable default argument in {node.name}")
                end_line = node.end_lineno or node.lineno
                if end_line - node.lineno + 1 > 100:
                    reviews.append(f"{location(path, node.lineno)} function {node.name} spans {end_line - node.lineno + 1} lines")
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "sys"
                    and node.func.value.attr == "path"
                    and node.func.attr in {"append", "insert", "extend"}
                ):
                    errors.append(f"{location(path, node.lineno)} mutates sys.path")
                if is_subprocess_call(node):
                    keywords = keyword_names(node)
                    shell = next((item.value for item in node.keywords if item.arg == "shell"), None)
                    if isinstance(shell, ast.Constant) and shell.value is True:
                        errors.append(f"{location(path, node.lineno)} subprocess uses shell=True")
                    missing = {"cwd", "timeout"} - keywords
                    if missing:
                        errors.append(
                            f"{location(path, node.lineno)} subprocess omits {', '.join(sorted(missing))}"
                        )
        if len(source.splitlines()) > 600:
            reviews.append(f"{location(path, 1)} module spans {len(source.splitlines())} lines")
    return errors, reviews


def check_powershell() -> list[str]:
    errors: list[str] = []
    for path in active_files(".ps1"):
        source = path.read_text(encoding="utf-8-sig")
        if not re.search(r"(?im)^\s*Set-StrictMode\s+-Version\s+Latest\b", source):
            errors.append(f"{location(path, 1)} PowerShell omits Set-StrictMode -Version Latest")
        if not re.search(r"(?i)\$ErrorActionPreference\s*=\s*['\"]Stop['\"]", source):
            errors.append(f"{location(path, 1)} PowerShell omits ErrorActionPreference=Stop")
    return errors


def check_matlab() -> list[str]:
    errors: list[str] = []
    forbidden = (
        (re.compile(r"\bmphstart\s*\("), "manages its own mphstart connection"),
        (re.compile(r"(?i)COMSOL64[\\/]Multiphysics[\\/]mli"), "hard-codes the COMSOL MLI path"),
    )
    for path in active_files(".m"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            for pattern, message in forbidden:
                if pattern.search(line):
                    errors.append(f"{location(path, line_number)} {message}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-review", action="store_true", help="list complexity review signals")
    arguments = parser.parse_args(argv)
    python_errors, reviews = check_python()
    errors = [*python_errors, *check_powershell(), *check_matlab()]
    for item in errors:
        print(f"DEVELOPMENT_STANDARD_ERROR={item}")
    if arguments.show_review:
        for item in reviews:
            print(f"DEVELOPMENT_STANDARD_REVIEW={item}")
    status = "PASS" if not errors else "FAIL"
    print(
        f"DEVELOPMENT_STANDARDS={status} ERRORS={len(errors)} REVIEW_SIGNALS={len(reviews)}"
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
