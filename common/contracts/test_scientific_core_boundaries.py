"""Sustain the migrated scientific core's import and environment boundaries."""
from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import sys
import tomllib
import unittest

from packaging.requirements import Requirement


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src/msplatform"
SCIENTIFIC_DOMAINS = {"analysis", "assembly", "contracts", "io", "ion_release"}
HOST_MODULES = {"ctypes", "winreg", "subprocess", "multiprocessing"}
PATH_LOADERS = {"importlib.util.spec_from_file_location", "importlib.machinery.SourceFileLoader",
                "importlib.machinery.SourcelessFileLoader", "importlib.machinery.ExtensionFileLoader",
                "imp.load_source", "imp.load_module", "zipimport.zipimporter", "runpy.run_path", "runpy.run_module"}
ENVIRONMENT_PROBES = {"os.getenv", "os.environ", "os.name", "sys.path", "sys.platform",
                      "shutil.which", "importlib.util.find_spec"}


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _qualified_name(node.value, aliases) + "." + node.attr
    return ""


def _target_error(target: str, dependencies: set[str]) -> str | None:
    parts = target.split(".")
    if parts[0] == "msplatform":
        if len(parts) > 1 and parts[1] not in SCIENTIFIC_DOMAINS:
            return f"scientific core imports an execution/provider domain: {target}"
        return None
    if parts[0] in {"common", "projects", "integrations"}:
        return f"scientific core imports a repository owner: {target}"
    if parts[0] in HOST_MODULES:
        return f"scientific core imports host/process machinery: {target}"
    if parts[0] not in sys.stdlib_module_names | set(sys.builtin_module_names) | dependencies:
        return f"scientific core imports an undeclared dependency: {target}"
    return None


def _import_errors(tree: ast.AST, package: str, dependencies: set[str]) -> tuple[list[str], dict[str, str]]:
    errors, aliases = [], {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [item.name for item in node.names]
            aliases.update({item.asname or item.name.split(".")[0]: item.name if item.asname
                            else item.name.split(".")[0] for item in node.names})
        elif isinstance(node, ast.ImportFrom):
            try:
                base = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
            except ImportError:
                errors.append(f"{node.lineno}: relative import escapes the scientific namespace")
                continue
            targets = [base, *(f"{base}.{item.name}" for item in node.names)]
            aliases.update({item.asname or item.name: f"{base}.{item.name}" for item in node.names})
        else:
            continue
        errors.extend(f"{node.lineno}: {error}" for target in targets
                      if (error := _target_error(target, dependencies)))
    return errors, aliases


def _dynamic_import_target(node: ast.Call, package: str) -> str:
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        raise ValueError("unresolved dynamic import is not a supported scientific-core dependency")
    target = node.args[0].value
    if target.startswith("."):
        argument = node.args[1] if len(node.args) > 1 else next(
            (item.value for item in node.keywords if item.arg == "package"), None)
        if isinstance(argument, ast.Name) and argument.id == "__package__":
            base = package
        elif isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            base = argument.value
        else:
            raise ValueError("relative dynamic import requires a declared package")
        try:
            return resolve_name(target, base)
        except ImportError as error:
            raise ValueError("relative dynamic import escapes the scientific namespace") from error
    return target


def core_boundary_errors(source: str, module: str, *, is_package: bool = False,
                         dependencies: set[str]) -> list[str]:
    """Check explicit imports and loaders; dynamic runtime behavior is tested separately."""
    tree = ast.parse(source)
    package = module if is_package else module.rpartition(".")[0]
    errors, aliases = _import_errors(tree, package, dependencies)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = _qualified_name(node.value, aliases)
            if name:
                aliases[node.targets[0].id] = name
        name = _qualified_name(node, aliases)
        if name in ENVIRONMENT_PROBES or name.startswith("platform."):
            errors.append(f"{node.lineno}: scientific core probes host/search-path state: {name}")
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_name(node.func, aliases)
        if name in PATH_LOADERS or name in {"exec", "eval"}:
            errors.append(f"{node.lineno}: scientific core loads executable code outside declared imports: {name}")
        if name in {"__import__", "importlib.__import__", "importlib.import_module"}:
            try:
                target = _dynamic_import_target(node, package)
            except ValueError as error:
                errors.append(f"{node.lineno}: {error}")
            else:
                if error := _target_error(target, dependencies):
                    errors.append(f"{node.lineno}: {error}")
    return sorted(set(errors))


class ScientificCoreBoundaryTests(unittest.TestCase):
    def test_current_scientific_implementations_have_no_repository_or_host_dependencies(self):
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dependencies = {Requirement(value).name.replace("-", "_") for value in project["dependencies"]}
        paths = sorted(CORE_ROOT.rglob("*.py"))
        self.assertTrue(paths, "scientific implementations must actually exist")
        errors = []
        for path in paths:
            parts = path.relative_to(CORE_ROOT.parent).with_suffix("").parts
            module = ".".join(parts[:-1] if path.name == "__init__.py" else parts)
            errors.extend(f"{path.relative_to(REPO_ROOT)}:{error}" for error in core_boundary_errors(
                path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py",
                dependencies=dependencies))
        self.assertEqual(errors, [])

    def test_ordinary_relative_and_dynamic_reverse_dependencies_are_rejected(self):
        rejected = (
            "import common.ion_release.release", "from projects.example import source",
            "from integrations.runtime import owner", "from msplatform.runtime import owner",
            "from msplatform import runtime", "from .. import infrastructure",
            "from ... import common", "import undeclared_solver",
            "import importlib as lib; lib.import_module('common.contracts.file_identity')",
            "from importlib import import_module as load; load('projects.example')",
            "import importlib; load = importlib.import_module; load('integrations.runtime')",
            "__import__('common.ion_release.release')", "__import__(requested_module)",
            "import importlib; importlib.import_module('..runtime', __package__)",
            "import importlib; importlib.import_module('...common', __package__)",
            "try:\n import common.ion_release.release\nexcept ImportError:\n import numpy",
        )
        for source in rejected:
            with self.subTest(source=source):
                self.assertTrue(core_boundary_errors(source, "msplatform.analysis.example", dependencies={"numpy"}))

    def test_path_loaders_and_environment_fallbacks_are_rejected(self):
        rejected = (
            "from importlib.util import spec_from_file_location as load; load('x', file_path)",
            "import importlib.machinery as loaders; loaders.SourceFileLoader('x', file_path)",
            "import imp; imp.load_source('x', file_path)", "import zipimport; zipimport.zipimporter(file_path)",
            "import runpy; runpy.run_path(file_path)", "exec(source)",
            "import os; os.getenv('SIMION_HOME')", "from os import environ as env; root = env['HOME']",
            "import sys; sys.path.insert(0, checkout)", "import shutil; shutil.which('pwsh')",
            "import platform; platform.system()", "import subprocess", "import ctypes",
            "import sys; is_windows = sys.platform == 'win32'", "import os; is_windows = os.name == 'nt'",
            "from importlib.util import find_spec; find_spec('common')",
        )
        for source in rejected:
            with self.subTest(source=source):
                self.assertTrue(core_boundary_errors(source, "msplatform.analysis.example", dependencies=set()))

    def test_declared_third_party_and_canonical_relative_imports_are_allowed(self):
        source = """
from pathlib import Path
from ..contracts.particle_physics import AMU_KG
from . import helper
import numpy as np
from scipy import stats
import importlib as lib
lib.import_module('.helper', __package__)
"""
        self.assertEqual(core_boundary_errors(source, "msplatform.analysis.example", dependencies={"numpy", "scipy"}), [])


if __name__ == "__main__":
    unittest.main()
