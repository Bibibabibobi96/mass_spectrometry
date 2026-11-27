"""Freeze selected small inputs; native payload families keep their own owner."""
from __future__ import annotations

from collections.abc import Sequence
import ast
from pathlib import Path
import os
import re
import shutil
import stat
from typing import Any

from msplatform.io.manifest_records import file_record, verify_record


def freeze_file(source: Path, destination: Path, *, retention_classifier: Any = None,
                retention_role: str | None = None, overwrite_existing: bool = False) -> dict[str, Any]:
    """Copy exact input bytes to a caller-selected, previously absent path.

    The caller creates the parent. Explicit overwrite is for the caller's owned
    staging destination; the default still refuses any existing destination.
    This is the existing small-input primitive;
    solver-native payloads use their dedicated owner mechanisms.
    """
    if type(overwrite_existing) is not bool:
        raise ValueError("overwrite_existing requires an explicit boolean")
    if destination.exists() and not overwrite_existing:
        raise FileExistsError(destination)
    if overwrite_existing and not source.is_file():
        raise FileNotFoundError(source)
    before = file_record(source.resolve(), retention_role=retention_role, retention_classifier=retention_classifier)
    if overwrite_existing and destination.exists():
        destination.chmod(destination.stat().st_mode | stat.S_IWRITE)
    shutil.copyfile(source, destination)
    if overwrite_existing:
        shutil.copystat(source, destination)
    verify_record("frozen input", {**before, "path": str(destination)},
                  retention_classifier=retention_classifier)
    return {**before, "path": str(destination.resolve()), "source_path": str(source.resolve())}


def freeze_python_package(source_root: Path, code_root: Path, *,
                          relative_paths: Sequence[str]) -> dict[str, Any]:
    """Freeze an ordered explicit package using the existing verified-copy primitive.

    This is the sole aggregate formerly owned by RF's New-FrozenPythonPackage.
    It retains its schema1 inventory and uppercase hashes. Selection of scientific
    packages/resources belongs to the caller. Existing files may be overwritten
    only within this explicitly selected owned staging directory.
    Explicit package sources are required evidence, including at the existing
    large-file read boundary; this is not native-payload classification.
    """
    source_root = Path(os.path.abspath(source_root))
    code_root = Path(os.path.abspath(code_root))
    if isinstance(relative_paths, (str, bytes)) or not isinstance(relative_paths, Sequence):
        raise ValueError("Frozen Python dependency paths must be an explicit sequence")
    seen: set[str] = set()
    inventory = []
    source_role = lambda _path, **_options: 'required_evidence'
    for relative in relative_paths:
        if not isinstance(relative, str) or Path(relative).anchor or '..' in re.split(r'[/\\]', relative):
            raise ValueError(f"Frozen Python dependency path is not relative: {relative}")
        normalized = relative.replace('\\', '/')
        if normalized.casefold() in seen:
            raise ValueError(f"Frozen Python dependency path is duplicated: {relative}")
        seen.add(normalized.casefold())
        source = Path(os.path.abspath(source_root / normalized))
        if not source.is_relative_to(source_root) or source == source_root:
            raise ValueError(f"Frozen Python dependency escapes its source root: {relative}")
        destination = code_root / normalized
        # Preserve missing-source-before-destination changes and per-entry failure
        # ordering. This creates no second copy or persistent identity cache.
        if not source.is_file():
            raise FileNotFoundError(f"Run input is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        record = freeze_file(source, destination, overwrite_existing=True, retention_classifier=source_role)
        verify_record('frozen package source', {**record, 'path': str(source.resolve())},
                      retention_classifier=source_role)
        inventory.append(dict(relative_path=normalized, path=str(destination.absolute()),
                              sha256=record['sha256'].upper()))
    return dict(schema_version=1, code_root=str(code_root),
                package_roots=python_import_roots(code_root), files=inventory)


_PYTHON_EXCLUDED_PARTS = frozenset({
    "tests", "test_support", "testing_support", "history", "generated", "__pycache__",
    "assets", "artifacts", "vendor", "third_party", "third-party", ".git", ".venv",
})


def _python_source_relative(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a nonempty repository-relative POSIX path")
    path = Path(value)
    if path.is_absolute() or path.drive or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError(f"{label} must not be absolute or traverse its source root: {value}")
    if any(part in _PYTHON_EXCLUDED_PARTS for part in path.parts):
        raise ValueError(f"{label} names an excluded Python source location: {value}")
    return path


def _production_python(path: Path) -> bool:
    return (path.suffix == ".py" and not path.name.startswith("test_")
            and not path.name.endswith("_test.py")
            and not any(part in _PYTHON_EXCLUDED_PARTS for part in path.parts))


def enumerate_python_sources(source_root: Path, *, package_roots: Sequence[str] = (),
                             module_paths: Sequence[str] = (),
                             provider_root: str | None = None,
                             resource_suffixes: Sequence[str] = (),
                             require_python_source: bool = False) -> list[str]:
    """Expand declared Python delivery packages without importing or copying code.

    Paths are repository-relative POSIX names. Present parent initializers are
    included; implicit namespace parents need no synthetic files. Every source
    must stay inside source_root and an optional provider_root, including through
    junctions. Overlapping author selections are errors, not silently deduped.
    Test/history/generated/native-asset trees and bytecode never join a package.
    Named resource suffixes explicitly extend the package's small data closure.
    require_python_source additionally requires production Python inside every
    selected package, before parent initializers are supplemented.
    """
    if type(require_python_source) is not bool:
        raise ValueError("require_python_source requires an explicit boolean")
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Python source root must be a directory")
    for values in (package_roots, module_paths):
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise ValueError("Python package/module selections must be sequences of paths")
    if (isinstance(resource_suffixes, (str, bytes)) or not isinstance(resource_suffixes, Sequence)
            or any(not isinstance(value, str) or not value.startswith('.') or value == '.'
                   or '/' in value or '\\' in value for value in resource_suffixes)
            or len(set(resource_suffixes)) != len(resource_suffixes)):
        raise ValueError("Python resource suffixes must be distinct explicit file suffixes")
    provider = root
    if provider_root is not None:
        provider = (root / _python_source_relative(provider_root, "provider root")).resolve(strict=True)
        if not provider.is_dir() or not provider.is_relative_to(root):
            raise ValueError("Python provider root escapes its source root or is not a directory")

    def contained(path: Path) -> Path:
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(root) or not actual.is_relative_to(provider):
            raise ValueError(f"Python source escapes its declared provider: {path}")
        return actual

    packages = [root / _python_source_relative(value, "Python package") for value in package_roots]
    modules = [root / _python_source_relative(value, "Python module") for value in module_paths]
    selected_roots: list[Path] = []
    for path in packages:
        actual = contained(path)
        if not actual.is_dir():
            raise ValueError(f"Python package is not a directory: {path}")
        if any(actual == old or actual.is_relative_to(old) or old.is_relative_to(actual)
               for old in selected_roots):
            raise ValueError(f"Duplicate or overlapping Python packages: {path}")
        selected_roots.append(actual)
    explicit: set[Path] = set()
    for path in modules:
        actual = contained(path)
        if not actual.is_file() or not _production_python(path.relative_to(root)):
            raise ValueError(f"Python module is not a production .py source: {path}")
        if actual in explicit or any(actual.is_relative_to(old) for old in selected_roots):
            raise ValueError(f"Duplicate or overlapping Python module: {path}")
        explicit.add(actual)
    selected: dict[str, Path] = {}
    identities: dict[Path, str] = {}

    def include(path: Path) -> None:
        actual = contained(path)
        relative = path.relative_to(root).as_posix()
        if actual in identities and identities[actual] != relative:
            raise ValueError(f"Python source has duplicate physical representations: {path}")
        key = relative.casefold()
        if key in selected and selected[key] != path:
            raise ValueError(f"Python source names differ only by case: {path}")
        identities[actual] = relative
        selected[key] = path

    visited_directories: set[Path] = set()

    def visit(directory: Path) -> tuple[int, int]:
        actual_directory = contained(directory)
        if actual_directory in visited_directories:
            raise ValueError(f"Duplicate or cyclic Python package directory: {directory}")
        visited_directories.add(actual_directory)
        count = 0
        python_count = 0
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root)
            if any(part in _PYTHON_EXCLUDED_PARTS for part in relative.parts):
                continue
            actual = contained(path)
            if actual.is_dir():
                child_count, child_python_count = visit(path)
                count += child_count
                python_count += child_python_count
            elif actual.is_file() and (_production_python(relative)
                                       or any(path.name.endswith(suffix) for suffix in resource_suffixes)):
                include(path)
                count += 1
                python_count += int(_production_python(relative))
        return count, python_count

    for path in packages:
        count, python_count = visit(path)
        if not count or (require_python_source and not python_count):
            raise ValueError(f"Python package has no production sources: {path}")
    for path in modules:
        include(path)
    for path in tuple(selected.values()):
        parent = path.parent
        while parent != root:
            initializer = parent / "__init__.py"
            if initializer.exists():
                include(initializer)
            parent = parent.parent
    # A scientific module declares its own small package data in a literal;
    # inspect source, never import it, so frozen closure selection has no side effects.
    for path in tuple(selected.values()):
        if path.suffix != ".py":
            continue
        source = path.read_bytes()
        if b"FROZEN_PACKAGE_RESOURCES" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        declarations = [node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "FROZEN_PACKAGE_RESOURCES"
                                for target in node.targets)]
        if not declarations:
            continue
        if len(declarations) != 1 or len(declarations[0].targets) != 1:
            raise ValueError(f"one literal FROZEN_PACKAGE_RESOURCES declaration required: {path}")
        try:
            resources = ast.literal_eval(declarations[0].value)
        except (ValueError, TypeError, SyntaxError) as error:
            raise ValueError(f"frozen package resources must be a literal tuple: {path}") from error
        if (not isinstance(resources, tuple) or not resources or any(not isinstance(item, str) for item in resources)
                or len(set(resources)) != len(resources)):
            raise ValueError(f"frozen package resources must be a nonempty unique tuple: {path}")
        parent = path.parent
        package_root = None
        while parent != root and (parent / "__init__.py").is_file():
            package_root = parent
            parent = parent.parent
        if package_root is None:
            raise ValueError(f"frozen resource owner has no explicit Python package root: {path}")
        for resource in resources:
            relative = _python_source_relative(resource, "frozen package resource")
            candidate = package_root / relative
            if not candidate.is_file():
                raise ValueError(f"declared frozen package resource is missing: {candidate}")
            include(candidate)
    if not selected:
        raise ValueError("Python package/module selection is empty")
    return sorted(path.relative_to(root).as_posix() for path in selected.values())


def python_import_roots(source_root: Path) -> list[str]:
    """Return only this source tree's src and flat import roots, in that order.

    Historical flat snapshots keep their sole original root. A present src
    directory must be contained in this exact tree, including through junctions;
    installed packages and the author's current checkout are never substitutes.
    """
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Python source root must be a directory")
    source = root / 'src'
    if not source.exists():
        return [str(root)]
    actual = source.resolve(strict=True)
    if not actual.is_dir() or not actual.is_relative_to(root):
        raise ValueError("Python src import root escapes its source tree or is not a directory")
    return [str(actual), str(root)]


def resolve_python_module_sources(names: Sequence[str]) -> dict[str, Path]:
    """Locate explicit module sources without executing the target module.

    As with Python find_spec, resolving a dotted name may import its parent
    package. The requested target itself is not imported by this function.
    """
    import importlib.util

    if isinstance(names, (str, bytes)) or not isinstance(names, Sequence):
        raise ValueError("module names must be an explicit sequence")
    result = {}
    for name in names:
        if not isinstance(name, str) or not name or any(not part.isidentifier() for part in name.split(".")):
            raise ValueError("qualified Python module name required")
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin or Path(spec.origin).suffix.lower() != ".py":
            raise ValueError("Python source module is unavailable: " + name)
        path = Path(spec.origin).resolve(strict=True)
        if not path.is_file():
            raise ValueError("Python source module is unavailable: " + name)
        result[name] = path
    return result
