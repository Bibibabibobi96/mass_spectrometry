"""Compile platform-stable SHA bindings for the active multipole family chain."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.contracts.file_identity import repository_text_sha256


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PREFIXES = ("common/", "config/", "docs/", "integrations/", "projects/")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _render(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _is_repository_path(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REPOSITORY_PREFIXES)


def _reference_pairs(value: Any) -> Iterator[tuple[dict[str, Any], str, str]]:
    if isinstance(value, list):
        for item in value:
            yield from _reference_pairs(item)
        return
    if not isinstance(value, dict):
        return
    emitted: set[tuple[str, str]] = set()

    def emit(path_key: str, hash_key: str) -> Iterator[tuple[dict[str, Any], str, str]]:
        pair = (path_key, hash_key)
        if pair not in emitted and _is_repository_path(value.get(path_key)) and hash_key in value:
            emitted.add(pair)
            yield value, path_key, hash_key

    yield from emit("path", "sha256")
    yield from emit("source_contract", "source_sha256")
    yield from emit("source_repo_path", "sha256")
    yield from emit("adapter_entrypoint", "adapter_sha256")
    for key in tuple(value):
        if key.endswith("_path"):
            yield from emit(key, key.removesuffix("_path") + "_sha256")
    for item in value.values():
        yield from _reference_pairs(item)


def _target_paths(repo_root: Path) -> list[Path]:
    integration_root = repo_root / "integrations" / INTEGRATION_ROOT.name
    config_root = integration_root / "config"
    targets = {
        path.resolve()
        for path in config_root.glob("family_*.json")
        if '"sha256"' in path.read_text(encoding="utf-8-sig")
    }
    targets.add((config_root / "execution_adapter_profiles.json").resolve())
    profiles = _load(config_root / "connection_profiles.json")["profiles"]
    for profile in profiles:
        for side in ("upstream", "downstream"):
            targets.add((repo_root / profile[side]["port_contract"]).resolve())
    return sorted(targets)


def compile_publications(repo_root: Path) -> dict[Path, bytes]:
    """Return canonical publication bytes with every repository hash refreshed."""
    root = repo_root.resolve()
    targets = _target_paths(root)
    documents = {path: _load(path) for path in targets}
    target_set = set(targets)
    compiled: dict[Path, bytes] = {}
    visiting: set[Path] = set()

    def compile_one(path: Path) -> bytes:
        if path in compiled:
            return compiled[path]
        if path in visiting:
            raise ValueError(f"repository binding cycle includes {path}")
        visiting.add(path)
        document = copy.deepcopy(documents[path])
        for owner, path_key, hash_key in _reference_pairs(document):
            dependency = (root / owner[path_key]).resolve()
            dependency.relative_to(root)
            if not dependency.is_file():
                raise FileNotFoundError(f"repository binding source is missing: {owner[path_key]}")
            digest = (
                hashlib.sha256(compile_one(dependency)).hexdigest().upper()
                if dependency in target_set
                else repository_text_sha256(dependency)
            )
            owner[hash_key] = digest
        visiting.remove(path)
        compiled[path] = _render(document)
        return compiled[path]

    for target in targets:
        compile_one(target)
    return compiled


def publication_differences(repo_root: Path) -> list[Path]:
    """Return publications whose canonical bytes differ from compiled output."""
    differences = []
    for path, expected in compile_publications(repo_root).items():
        actual = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if actual != expected:
            differences.append(path)
    return differences


def write_publications(repo_root: Path) -> list[Path]:
    """Write every derived publication with UTF-8 and LF bytes."""
    compiled = compile_publications(repo_root)
    changed = []
    for path, expected in compiled.items():
        actual = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if actual != expected:
            path.write_bytes(expected)
            changed.append(path)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        stale = publication_differences(args.repo_root)
        if stale:
            rendered = ",".join(
                path.relative_to(args.repo_root.resolve()).as_posix() for path in stale
            )
            raise SystemExit(f"FAMILY_REPOSITORY_BINDINGS=STALE PATHS={rendered}")
        print("FAMILY_REPOSITORY_BINDINGS=PASS")
        return
    changed = write_publications(args.repo_root)
    print(f"FAMILY_REPOSITORY_BINDINGS=UPDATED FILES={len(changed)}")


if __name__ == "__main__":
    main()
