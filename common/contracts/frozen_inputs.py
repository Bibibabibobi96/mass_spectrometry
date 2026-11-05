"""Freeze explicitly selected small inputs with their original byte identity."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

def freeze_file(source: Path, destination: Path, *, retention_classifier: Any = None) -> dict[str, Any]:
    """Copy a small input and return its destination record plus source_path.

    The caller selects paths and creates the destination parent. Existing
    destinations, missing sources and copies differing from the original raw
    bytes fail; solver-native payloads use their dedicated owner mechanisms.
    """
    # Lazy transport preserves source-enumeration bootstrap before core import.
    from msplatform.execution.inputs import freeze_file as installed_freeze_file
    return installed_freeze_file(source, destination, retention_classifier=retention_classifier)


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
                             resource_suffixes: Sequence[str] = ()) -> list[str]:
    """Expand declared Python delivery packages without importing or copying code.

    Paths are repository-relative POSIX names. Present parent initializers are
    included; implicit namespace parents need no synthetic files. Every source
    must stay inside source_root and an optional provider_root, including through
    junctions. Overlapping author selections are errors, not silently deduped.
    Test/history/generated/native-asset trees and bytecode never join a package.
    Named resource suffixes explicitly extend the package's small data closure.
    """
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

    def visit(directory: Path) -> int:
        actual_directory = contained(directory)
        if actual_directory in visited_directories:
            raise ValueError(f"Duplicate or cyclic Python package directory: {directory}")
        visited_directories.add(actual_directory)
        count = 0
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root)
            if any(part in _PYTHON_EXCLUDED_PARTS for part in relative.parts):
                continue
            actual = contained(path)
            if actual.is_dir():
                count += visit(path)
            elif actual.is_file() and (_production_python(relative)
                                       or any(path.name.endswith(suffix) for suffix in resource_suffixes)):
                include(path)
                count += 1
        return count

    for path in packages:
        if not visit(path):
            raise ValueError(f"Python package has no production sources: {path}")
    for path in modules:
        include(path)
    # Initializers are shared prerequisites, not overlapping author selections.
    for path in tuple(selected.values()):
        parent = path.parent
        while parent != root:
            initializer = parent / "__init__.py"
            if initializer.exists():
                include(initializer)
            parent = parent.parent
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
