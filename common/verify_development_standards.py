"""Check machine-decidable repository development standards."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    REPO_ROOT / "common",
    REPO_ROOT / "projects",
    REPO_ROOT / "integrations",
)
EXCLUDED_PARTS = {"history", "legacy", ".venv", "__pycache__"}
MATLAB_BUILD_ONLY_MARKER = re.compile(
    r"(?im)^\s*%\s*REPOSITORY_CONTRACT:\s*MATLAB_BUILD_ONLY\s*$"
)
MATLAB_BUILD_ONLY_FORBIDDEN = (
    (re.compile(r"\.mesh\.create\s*\("), "creates a mesh"),
    (re.compile(r"\.physics\.create\s*\("), "creates physics"),
    (re.compile(r"\.study\.create\s*\("), "creates a study"),
    (re.compile(r"\.sol\.create\s*\("), "creates a solver"),
    (re.compile(r"\.runAll\s*(?:\(|;|$)"), "runs a solver sequence"),
    (re.compile(r"\bmphinterp\s*\("), "extracts a solved field"),
    (re.compile(r"\bmphparticle\s*\("), "extracts solved particles"),
    (re.compile(r"\bmphsave\s*\("), "saves an MPH"),
    (re.compile(r"\bmodel\.save\s*\("), "saves a model"),
)
LEGACY_POWERSHELL_COMMANDS = {"powershell", "powershell.exe"}


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


def check_legacy_powershell_launchers(path: Path, tree: ast.AST) -> list[str]:
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            command = node.elts[0]
            if (
                isinstance(command, ast.Constant)
                and isinstance(command.value, str)
                and command.value.casefold() in LEGACY_POWERSHELL_COMMANDS
            ):
                errors.append(
                    f"{location(path, node.lineno)} command argv launches legacy PowerShell"
                )
        elif isinstance(node, ast.Call) and is_subprocess_call(node) and node.args:
            command = node.args[0]
            if (
                isinstance(command, ast.Constant)
                and isinstance(command.value, str)
                and command.value.casefold() in LEGACY_POWERSHELL_COMMANDS
            ):
                errors.append(
                    f"{location(path, node.lineno)} subprocess launches legacy PowerShell"
                )
    return errors


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
        errors.extend(check_legacy_powershell_launchers(path, tree))
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
                    # Popen has no timeout argument.  Its callers must enforce
                    # timeout in their own observation/wait loop; requiring an
                    # impossible keyword here rejects the only correct API.
                    required = {"cwd"} if node.func.attr == "Popen" else {"cwd", "timeout"}
                    missing = required - keywords
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


def check_matlab_source(path: Path, source: str) -> list[str]:
    errors: list[str] = []
    forbidden = (
        (re.compile(r"\bmphstart\s*\("), "manages its own mphstart connection"),
        (re.compile(r"(?i)COMSOL64[\\/]Multiphysics[\\/]mli"), "hard-codes the COMSOL MLI path"),
    )
    lines = source.splitlines()
    for line_number, line in enumerate(lines, 1):
        for pattern, message in forbidden:
            if pattern.search(line):
                errors.append(f"{location(path, line_number)} {message}")
    if MATLAB_BUILD_ONLY_MARKER.search(source):
        for line_number, line in enumerate(lines, 1):
            code = line.split("%", 1)[0]
            for pattern, action in MATLAB_BUILD_ONLY_FORBIDDEN:
                if pattern.search(code):
                    errors.append(
                        f"{location(path, line_number)} MATLAB_BUILD_ONLY {action}"
                    )
    return errors


def check_matlab() -> list[str]:
    errors: list[str] = []
    for path in active_files(".m"):
        errors.extend(check_matlab_source(path, path.read_text(encoding="utf-8-sig")))
    return errors


def _python_module(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _import_target(module: str, path: Path, node: ast.ImportFrom) -> str:
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    if node.level:
        package = package[:len(package)-node.level+1]
        return ".".join([*package, *([node.module] if node.module else [])])
    return node.module or ""


def _consumer_references(modules: dict[str, tuple[Path, ast.Module]]):
    """Conservative symbol references, including callbacks and lazy imports."""
    definitions = {(module, node.name): node for module, (_, tree) in modules.items()
                   for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    references = {key: set() for key in definitions}
    imports = {module: set() for module in modules}
    uncertain = set()
    for module, (path, tree) in modules.items():
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases.setdefault(alias.asname or alias.name.split(".")[0], set()).add(
                        alias.name if alias.asname else alias.name.split(".")[0])
                    if alias.name in modules:
                        imports[module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = _import_target(module, path, node)
                if base in modules:
                    imports[module].add(base)
                for alias in node.names:
                    target = f"{base}.{alias.name}"
                    aliases.setdefault(alias.asname or alias.name, set()).add(target)
                    if target in modules:
                        imports[module].add(target)
                    elif (base, alias.name) in references:
                        references[base, alias.name].add(module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                uncertain.update(re.findall(r"\b_[A-Za-z]\w*\b", node.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                targets = aliases.get(node.id, set()) | {f"{module}.{node.id}"}
            elif isinstance(node, ast.Attribute):
                parts, current = [], node
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if not isinstance(current, ast.Name):
                    continue
                targets = {".".join([prefix, *reversed(parts)])
                           for prefix in aliases.get(current.id, {current.id})}
            else:
                continue
            for target in targets:
                owner, _, name = target.rpartition(".")
                if (owner, name) in references:
                    references[owner, name].add(module)
    return definitions, references, imports, uncertain


def _declared_python_roots(root: Path, modules: dict) -> set[str]:
    """Use declared profiles and literal -m commands, never guess dynamic paths."""
    roots, scripts = set(), set()
    for contract in (root / "projects").glob("*/config/execution_profiles.json"):
        project = contract.parent.parent
        document = json.loads(contract.read_text(encoding="utf-8-sig"))
        pending = [document]
        while pending:
            value = pending.pop()
            if isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, dict):
                pending.extend(value.values())
                entry = value.get("entrypoint")
                if not isinstance(entry, str):
                    continue
                path = (project / entry).resolve()
                if not path.is_relative_to(root):
                    continue
                if path.suffix == ".py" and path.is_file():
                    roots.add(_python_module(path, root))
                elif path.suffix == ".ps1" and path.is_file():
                    scripts.add(path)
    catalog = root / "common/gate_catalog.json"
    if catalog.is_file():
        for route in json.loads(catalog.read_text(encoding="utf-8-sig"))["routes"]:
            for key in ("command", "repository_integration_command"):
                command = route.get(key, {})
                if command.get("runner") == "powershell":
                    scripts.add((root / command["script"]).resolve())
                elif command.get("runner") == "python":
                    arguments = command.get("arguments", [])
                    if len(arguments) > 1 and arguments[0] == "-m":
                        if arguments[1] != "unittest":
                            roots.add(arguments[1])
                    elif arguments and arguments[0].endswith(".py"):
                        path = (root / arguments[0]).resolve()
                        if path.is_relative_to(root) and path.is_file():
                            roots.add(_python_module(path, root))
    for path in scripts:
        if not path.is_relative_to(root) or not path.is_file():
            continue
        # A literal module is a static edge only. Variable-built commands,
        # nested PS runners and external callbacks remain unresolved; absence
        # here never authorizes retirement.
        source = path.read_text(encoding="utf-8-sig")
        roots.update(re.findall(r"(?<!\w)-m\s+['\"]?([A-Za-z_]\w*(?:\.\w+)+)", source))
    return roots.intersection(modules)


def _reachable_modules(roots: set[str], imports: dict[str, set[str]]) -> set[str]:
    reached, pending = set(), list(roots)
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.extend(imports.get(module, set())-reached)
    return reached


def audit_consumers(root: Path = REPO_ROOT) -> list[dict[str, str | int]]:
    """Inventory Python top-level private functions; never prove runtime use.

    Reachability is deliberately at module level, over all import/reference
    branches. A reachable module reference is a candidate consumer, not proof
    that a function executes. Strings, CLI guards, decorators and reflection
    preserve uncertainty. No category permits automatic source deletion.
    """
    modules, external_names = {}, set()
    for directory in ("common", "projects", "integrations"):
        for path in sorted((root / directory).rglob("*")):
            if not path.is_file() or EXCLUDED_PARTS.intersection(path.relative_to(root).parts):
                continue
            if path.suffix not in {".py", ".ps1", ".lua", ".m", ".json"}:
                continue
            source = path.read_text(encoding="utf-8-sig")
            if path.suffix == ".py":
                try:
                    modules[_python_module(path, root)] = path, ast.parse(source)
                except SyntaxError:
                    continue  # The existing syntax check owns this failure.
            else:
                external_names.update(re.findall(r"\b_[A-Za-z]\w*\b", source))
    definitions, references, imports, uncertain = _consumer_references(modules)
    uncertain.update(external_names)
    formal = _reachable_modules(_declared_python_roots(root, modules), imports)
    tests = _reachable_modules({module for module, (path, _) in modules.items()
                                if path.name.startswith("test_") or path.name.endswith("_test.py")}, imports)
    cli = _reachable_modules({module for module, (_, tree) in modules.items()
                              if any(isinstance(node, ast.Constant) and node.value == "__main__"
                                     for node in ast.walk(tree))}, imports)
    dynamic = {module for module, (_, tree) in modules.items()
               if any(isinstance(node, ast.Name) and node.id in {"globals", "locals", "getattr", "eval", "exec"}
                      for node in ast.walk(tree))}
    records = []
    for (module, name), node in sorted(definitions.items()):
        if not name.startswith("_") or name.startswith("__"):
            continue
        uses = references[module, name]
        ambiguous = name in uncertain or bool(node.decorator_list) or module in dynamic
        if uses & formal:
            category, reason = "formal_reachable", "declared_entry_module_reference"
        elif ambiguous or uses & cli:
            category, reason = "cli_callback_uncertain", "cli_string_decorator_or_dynamic_reference"
        elif uses & tests:
            category, reason = "test_only_reachable", "known_module_references_reach_only_tests"
        elif uses:
            category, reason = "cli_callback_uncertain", "references_without_declared_root"
        else:
            category, reason = "private_no_calls", "no_static_reference_candidate_requires_manual_confirmation"
        records.append(dict(path=modules[module][0].relative_to(root).as_posix(), line=node.lineno,
                            symbol=name, category=category, reason=reason,
                            consumer_modules=",".join(sorted(uses))))
    return records


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
    consumers = audit_consumers()
    categories = ("formal_reachable", "test_only_reachable", "cli_callback_uncertain", "private_no_calls")
    if arguments.show_review:
        for item in consumers:
            print(f"DEVELOPMENT_CONSUMER_REVIEW={item}")
    print("CONSUMER_AUDIT=STATIC_MODULE_REFERENCES AUTOMATIC_RETIREMENT=False " + " ".join(
        f"{category.upper()}={sum(item['category'] == category for item in consumers)}" for category in categories))
    status = "PASS" if not errors else "FAIL"
    print(
        f"DEVELOPMENT_STANDARDS={status} ERRORS={len(errors)} REVIEW_SIGNALS={len(reviews)}"
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
