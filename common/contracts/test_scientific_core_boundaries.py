"""Check the installed platform's directed domains and strict scientific core."""
from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import sys
import tomllib
import unittest

from packaging.requirements import Requirement
from msplatform.components import PROVIDER_DEPENDENCIES, validate_provider_dependencies


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src/msplatform"
SCIENTIFIC_DOMAINS = {"analysis", "assembly", "contracts", "io", "ion_release"}
PROVIDER_DOMAINS = {"rf_multipole", "orthogonal_accelerator", "single_reflection_oa_tof",
                    "apertured_tube_electron_impact_ion_source", "transverse_helical_filament_wehnelt_electron_gun"}
COMPONENT_INFRASTRUCTURE = {"model", "catalog"}
DOMAIN_IMPORTS = {
    **{name: SCIENTIFIC_DOMAINS for name in SCIENTIFIC_DOMAINS},
    "assembly": SCIENTIFIC_DOMAINS | {"components"},
    "components": SCIENTIFIC_DOMAINS | {"components"},
    "backends": SCIENTIFIC_DOMAINS | {"components", "backends", "execution"},
    "execution": SCIENTIFIC_DOMAINS | {"execution"},
    "examples": SCIENTIFIC_DOMAINS | {"examples"},
    "exporters": SCIENTIFIC_DOMAINS | {"components", "exporters", "execution"},
    "applications": SCIENTIFIC_DOMAINS | {"applications", "execution"},
    "api": SCIENTIFIC_DOMAINS | {"api", "components", "backends", "execution", "examples", "exporters", "applications"},
}
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


def _namespace_error(module: str) -> str | None:
    parts = module.split(".")
    if parts == ["msplatform"]:
        return None
    if len(parts) < 2 or parts[0] != "msplatform" or parts[1] not in DOMAIN_IMPORTS:
        return f"undeclared installed domain: {module}"
    if (parts[1] == "components" and len(parts) > 2
            and parts[2] not in PROVIDER_DOMAINS | COMPONENT_INFRASTRUCTURE):
        return f"undeclared component provider or infrastructure module: {module}"
    if parts[1] == "backends" and len(parts) > 2 and parts[2] != "simion":
        return f"undeclared installed backend: {module}"
    if parts[1] == "exporters" and len(parts) > 2 and parts[2] not in {"step", "execution"}:
        return f"undeclared installed exporter: {module}"
    if parts[1] == "applications" and len(parts) > 2 and parts[2] not in {
            "solidworks", "solidworks_worker", "model_execution", "simion", "simion_model_execution"}:
        return f"undeclared installed application: {module}"
    return None


def _target_error(target: str, dependencies: set[str], source_domain: str) -> str | None:
    parts = target.split(".")
    if parts[0] == "msplatform":
        if error := _namespace_error(target):
            return error
        if (source_domain == "assembly" and len(parts) > 2 and parts[:2] == ["msplatform", "components"]
                and parts[2] not in COMPONENT_INFRASTRUCTURE):
            return f"assembly imports provider-specific physics instead of neutral component data: {target}"
        if len(parts) > 1 and parts[1] not in DOMAIN_IMPORTS.get(source_domain, set()):
            return f"{source_domain} imports a reverse dependency: {target}"
        return None
    if parts[0] in {"common", "projects", "integrations"}:
        return f"scientific core imports a repository owner: {target}"
    if parts[0] in {"cadquery", "OCP"} and source_domain != "exporters":
        return f"{source_domain} imports optional CAD kernel: {target}"
    if parts[0] in {"win32com", "pythoncom", "pywintypes"} and source_domain != "applications":
        return f"{source_domain} imports optional application machinery: {target}"
    if (parts[0] in HOST_MODULES and source_domain != "execution"
            and not (source_domain == "applications" and parts[0] == "subprocess")):
        return f"{source_domain} imports host/process machinery: {target}"
    if parts[0] not in sys.stdlib_module_names | set(sys.builtin_module_names) | dependencies:
        return f"scientific core imports an undeclared dependency: {target}"
    return None


def _import_errors(tree: ast.AST, package: str, dependencies: set[str],
                   source_domain: str) -> tuple[list[str], dict[str, str], set[str]]:
    errors, aliases, imported = [], {}, set()
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
        imported.update(targets)
        errors.extend(f"{node.lineno}: {error}" for target in targets
                      if (error := _target_error(target, dependencies, source_domain)))
    return errors, aliases, imported


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
    source_domain = module.split(".")[1] if "." in module else "namespace"
    errors, aliases, _ = _import_errors(tree, package, dependencies, source_domain)
    if error := _namespace_error(module):
        errors.append(error)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = _qualified_name(node.value, aliases)
            if name:
                aliases[node.targets[0].id] = name
        name = _qualified_name(node, aliases)
        if (source_domain != "execution" and (name in ENVIRONMENT_PROBES or name.startswith("platform."))
                and not (source_domain == "applications" and name == "os.environ")):
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
                if error := _target_error(target, dependencies, source_domain):
                    errors.append(f"{node.lineno}: {error}")
    return sorted(set(errors))


def component_dependency_errors(sources: dict[str, str], declarations: dict[str, tuple[str, ...]]) -> list[str]:
    """Check both the declared DAG and actual cross-provider Python imports."""
    try:
        validate_provider_dependencies(declarations)
    except ValueError as error:
        return [str(error)]
    errors = []
    for module, source in sources.items():
        parts = module.split(".")
        if len(parts) < 3 or parts[2] not in declarations:
            errors.append(f"undeclared component source: {module}")
            continue
        provider = parts[2]
        package = module.rpartition(".")[0]
        tree = ast.parse(source)
        _, aliases, targets = _import_errors(tree, package, set(), "components")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _qualified_name(node.func, aliases) in {
                    "__import__", "importlib.__import__", "importlib.import_module"}:
                try:
                    targets.add(_dynamic_import_target(node, package))
                except ValueError as error:
                    errors.append(f"{module}: {error}")
        for target in targets:
            path = target.split(".")
            if len(path) > 2 and path[:2] == ["msplatform", "components"] and path[2] != provider:
                if path[2] not in declarations[provider]:
                    errors.append(f"{module}: undeclared provider dependency {provider} -> {path[2]}")
    return sorted(set(errors))


class ScientificCoreBoundaryTests(unittest.TestCase):
    def test_component_imports_follow_the_declared_acyclic_provider_graph(self):
        sources = {".".join(path.relative_to(CORE_ROOT.parent).with_suffix("").parts):
                   path.read_text(encoding="utf-8")
                   for provider in PROVIDER_DOMAINS
                   for path in (CORE_ROOT / "components" / provider).rglob("*.py")
                   }
        self.assertEqual(component_dependency_errors(sources, dict(PROVIDER_DEPENDENCIES)), [])

    def test_neutral_data_models_do_not_import_providers_backends_or_execution(self):
        forbidden = ("msplatform.components.rf_multipole", "msplatform.components.orthogonal_accelerator",
                     "msplatform.components.single_reflection_oa_tof", "msplatform.backends", "msplatform.execution")
        for relative in ("components/model.py", "assembly/model.py"):
            with self.subTest(path=relative):
                module = "msplatform." + relative.removesuffix(".py").replace("/", ".")
                source = (CORE_ROOT / relative).read_text(encoding="utf-8")
                _, _, targets = _import_errors(ast.parse(source), module, set(), module.split(".")[1])
                self.assertFalse([target for target in targets if target.startswith(forbidden)])

    def test_declarative_cycles_and_undeclared_python_provider_edges_are_rejected(self):
        for graph in ({"rf": ("oa",), "oa": ("rf",)}, {"rf": ("missing",)}, {"rf": ("rf",)}):
            with self.subTest(graph=graph):
                self.assertTrue(component_dependency_errors({}, graph))
        for source in (
                "from msplatform.components.single_reflection_oa_tof import layout",
                "import msplatform.components.single_reflection_oa_tof.layout",
                "import importlib; importlib.import_module('msplatform.components.single_reflection_oa_tof')"):
            for module in ("msplatform.components.rf_multipole.design", "msplatform.components.rf_multipole.__init__"):
                with self.subTest(source=source, module=module):
                    self.assertTrue(component_dependency_errors({module: source}, dict(PROVIDER_DEPENDENCIES)))

    def test_current_scientific_implementations_have_no_repository_or_host_dependencies(self):
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        dependencies = {Requirement(value).name.replace("-", "_") for value in project["dependencies"]}
        paths = sorted(CORE_ROOT.rglob("*.py"))
        self.assertTrue(paths, "scientific implementations must actually exist")
        errors = []
        for path in paths:
            parts = path.relative_to(CORE_ROOT.parent).with_suffix("").parts
            module = ".".join(parts[:-1] if path.name == "__init__.py" else parts)
            selected_dependencies = set(dependencies)
            if len(parts) > 1 and parts[1] == "exporters":
                cad_step = project.get("optional-dependencies", {}).get("cad-step", [])
                selected_dependencies.update(Requirement(value).name.replace("-", "_") for value in cad_step)
                if any(Requirement(value).name == "cadquery-ocp" for value in cad_step):
                    selected_dependencies.add("OCP")
            if len(parts) > 1 and parts[1] == "applications":
                cad = project.get("optional-dependencies", {}).get("cad", [])
                if any(Requirement(value).name == "pywin32" for value in cad):
                    selected_dependencies.update({"win32com", "pythoncom", "pywintypes"})
            errors.extend(f"{path.relative_to(REPO_ROOT)}:{error}" for error in core_boundary_errors(
                path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py",
                dependencies=selected_dependencies))
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

    def test_installed_outer_domains_follow_explicit_directions(self):
        allowed = (
            ("msplatform.api", "from msplatform.components.rf_multipole import design"),
            ("msplatform.api", "from msplatform.examples import load_example"),
            ("msplatform.backends.simion.geometry", "from msplatform.execution import recovery"),
            ("msplatform.components.single_reflection_oa_tof.design",
             "from msplatform.components.orthogonal_accelerator import sectioned_geometry"),
            ("msplatform.execution.process", "import subprocess; import os; os.environ.get('PATH')"),
            ("msplatform.api", "from msplatform.exporters import step"),
            ("msplatform.exporters.step", "from msplatform.components.rf_multipole import geometry_members"),
            ("msplatform.applications.solidworks", "from msplatform.execution import owner"),
            ("msplatform.exporters.step", "import cadquery; from OCP.Precision import Precision"),
            ("msplatform.applications.solidworks", "import pythoncom"),
            ("msplatform.applications.model_execution", "from msplatform.execution import owner"),
            ("msplatform.applications.simion", "from msplatform.execution import run_session"),
            ("msplatform.applications.simion_model_execution", "from msplatform.execution import run_session"),
            ("msplatform.applications.solidworks_worker", "import subprocess; import os; child = os.environ.copy()"),
        )
        for module, source in allowed:
            with self.subTest(module=module, source=source):
                self.assertEqual(core_boundary_errors(source, module, dependencies={"cadquery", "OCP", "pythoncom"}), [])
        rejected = (
            ("msplatform.contracts.clock", "from msplatform.execution import recovery"),
            ("msplatform.assembly.layout", "from msplatform.components.rf_multipole import design"),
            ("msplatform.components.rf_multipole.design", "from msplatform.backends import simion"),
            ("msplatform.execution.process", "from msplatform.components import rf_multipole"),
            ("msplatform.execution.process", "from msplatform import api"),
            ("msplatform.api", "import subprocess"),
            ("msplatform.backends.simion.geometry", "import subprocess"),
            ("msplatform.execution.process", "import common.host_resource_scheduler"),
            ("msplatform.examples", "from msplatform import api"),
            ("msplatform.unreviewed.entry", "import math"),
            ("msplatform.api", "from msplatform.components import unreviewed"),
            ("msplatform.api", "from msplatform.backends import unreviewed"),
            ("msplatform.contracts.clock", "import importlib; importlib.import_module('msplatform.execution')"),
            ("msplatform.execution.process", "import runpy; runpy.run_path(author_script)"),
            ("msplatform.analysis.example", "from msplatform.exporters import step"),
            ("msplatform.components.rf_multipole.design", "import cadquery"),
            ("msplatform.contracts.clock", "import pythoncom"),
            ("msplatform.exporters.step", "from msplatform import applications"),
            ("msplatform.exporters.unreviewed", "import math"),
            ("msplatform.applications.unreviewed", "import subprocess"),
            ("msplatform.applications.solidworks_worker", "import ctypes"),
            ("msplatform.applications.simion", "from msplatform.backends.simion import model"),
            ("msplatform.applications.solidworks_worker", "import multiprocessing"),
            ("msplatform.applications.solidworks_worker", "import sys; sys.path.append(author_checkout)"),
        )
        for module, source in rejected:
            with self.subTest(module=module, source=source):
                self.assertTrue(core_boundary_errors(source, module, dependencies={"cadquery", "OCP", "pythoncom"}))


if __name__ == "__main__":
    unittest.main()
