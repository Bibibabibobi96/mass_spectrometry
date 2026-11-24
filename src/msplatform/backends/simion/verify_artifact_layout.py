"""Compose SIMION PA-cache validation with generic artifact layout checks."""
from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

from msplatform.backends.simion.pa_family_cache import (
    PAFamilyCacheError,
    RECOVERY_DIRECTORY,
    load_pa_family_cache_transaction,
    validate_pa_family_cache_generation,
)
from msplatform.execution.immutable_pa_parity import MANIFEST_FILENAME, PARITY_FILENAME
from msplatform.execution.artifact_cache_contract import INTEGRATION_CACHE_ROOT_BY_ROLE
from msplatform.execution.verify_artifact_layout import (
    CACHE_SHA256,
    verify_artifacts_root as verify_generic_artifacts_root,
    verify_formal,
    verify_integration_cache_entry,
    verify_project,
    verify_verified_pulse_cache_entry,
)

PA_FAMILY_CACHE_NODE_SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
PA_FAMILY_CACHE_RUNTIME_DIRECTORIES = {".locks", ".staging"}


def _load_pa_family_cache_pointer(pointer_path: Path, cache_key: str) -> str:
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{pointer_path}: PA-family cache pointer is unreadable") from exc
    generation = pointer.get("generation_sha256") if isinstance(pointer, dict) else None
    if (
        not isinstance(pointer, dict)
        or set(pointer) != {"cache_key", "generation_sha256"}
        or not isinstance(pointer.get("cache_key"), str)
        or pointer["cache_key"].casefold() != cache_key.casefold()
        or not isinstance(generation, str)
        or PA_FAMILY_CACHE_NODE_SHA256.fullmatch(generation) is None
    ):
        raise AssertionError(f"{pointer_path}: PA-family cache pointer differs")
    return generation


def _verify_pa_family_recovery_tree(
    key_root: Path, generation_nodes: list[Path], selected: Path, *, verify_hashes: bool
) -> dict | None:
    recovery = key_root / RECOVERY_DIRECTORY
    try:
        recovery.lstat()
    except FileNotFoundError:
        return None

    def regular(path: Path, *, directory: bool) -> bool:
        info = path.lstat()
        kind = stat.S_ISDIR if directory else stat.S_ISREG
        return kind(info.st_mode) and not (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    if not regular(recovery, directory=True):
        raise PAFamilyCacheError("PA cache recovery must be a regular directory")
    generations = {path.name.casefold(): path for path in generation_nodes}
    recovery_nodes = list(recovery.iterdir())
    if not recovery_nodes:
        raise PAFamilyCacheError("PA cache recovery tree is empty")
    if len({path.name.casefold() for path in recovery_nodes}) != len(recovery_nodes):
        raise PAFamilyCacheError("duplicate case-insensitive PA cache recovery generation")
    selected_manifest = None
    for recovered in recovery_nodes:
        generation = generations.get(recovered.name.casefold())
        if (generation is None or not regular(recovered, directory=True)
                or not regular(generation, directory=True)):
            raise PAFamilyCacheError("PA cache recovery generation is unregistered or non-regular")
        groups = list(recovered.iterdir())
        for group in groups:
            if not regular(group, directory=True):
                raise PAFamilyCacheError("PA cache recovery group must be a regular directory")
            members = list(group.iterdir())
            if ({path.name for path in members} != {MANIFEST_FILENAME, PARITY_FILENAME}
                    or any(not regular(path, directory=False) for path in members)):
                raise PAFamilyCacheError("PA cache recovery bundle inventory differs")
        manifest = validate_pa_family_cache_generation(
            generation, verify_payload=verify_hashes and generation == selected
        )
        if (manifest["cache_key"].casefold() != key_root.name.casefold()
                or manifest["generation_sha256"].casefold() != recovered.name.casefold()):
            raise PAFamilyCacheError("PA cache recovery generation identity differs")
        expected = {group["bundle"] for group in manifest.get("redundancy", {}).get("groups", [])}
        if not expected or {group.name for group in groups} != expected:
            raise PAFamilyCacheError("PA cache recovery groups differ from the generation")
        if generation == selected:
            selected_manifest = manifest
    return selected_manifest


def verify_common_pa_family_cache(cache_root: Path, verify_hashes: bool = False) -> None:
    """Validate the registered SIMION PA-family cache layout and identity."""
    if not cache_root.exists():
        return
    if not cache_root.is_dir():
        raise AssertionError(f"{cache_root}: common PA-family cache is not a directory")
    key_names: set[str] = set()
    for node in cache_root.iterdir():
        if node.name == ".transactions":
            if not node.is_dir() or node.is_symlink():
                raise AssertionError(f"{node}: invalid PA-family transaction directory")
            for transaction in node.iterdir():
                if (not transaction.is_dir() or transaction.is_symlink()
                        or PA_FAMILY_CACHE_NODE_SHA256.fullmatch(transaction.name) is None):
                    raise AssertionError(f"{transaction}: invalid PA-family transaction node")
                try:
                    load_pa_family_cache_transaction(cache_root, transaction.name)
                except PAFamilyCacheError as exc:
                    raise AssertionError(f"{transaction}: invalid PA-family transaction") from exc
                for member in transaction.iterdir():
                    if member.name == "transaction.json":
                        continue
                    if (member.name not in {"payload", "build-scratch"} or member.is_symlink()
                            or not member.is_dir() or any(member.iterdir())):
                        raise AssertionError(f"{member}: unexpected PA-family transaction payload")
            continue
        if node.name in {".locks", ".build-locks"}:
            if not node.is_dir() or node.is_symlink():
                raise AssertionError(f"{node}: invalid PA-family lock directory")
            for lock in node.iterdir():
                if (not lock.is_file() or lock.is_symlink() or lock.suffix != ".lock"
                        or PA_FAMILY_CACHE_NODE_SHA256.fullmatch(lock.stem) is None):
                    raise AssertionError(f"{lock}: invalid PA-family lock file")
            continue
        if node.name in PA_FAMILY_CACHE_RUNTIME_DIRECTORIES:
            if not node.is_dir() or any(node.iterdir()):
                raise AssertionError(f"{node}: PA-family cache runtime directory is not empty")
            continue
        if not node.is_dir() or PA_FAMILY_CACHE_NODE_SHA256.fullmatch(node.name) is None:
            raise AssertionError(f"{node}: invalid common PA-family cache node")
        normalized_key = node.name.casefold()
        if normalized_key in key_names:
            raise AssertionError(f"{node}: duplicate case-insensitive PA-family cache key")
        key_names.add(normalized_key)
        expected_entries = {"current_generation.json", "generations"}
        actual_entries = {item.name for item in node.iterdir()}
        if not expected_entries <= actual_entries or actual_entries - expected_entries - {RECOVERY_DIRECTORY}:
            raise AssertionError(f"{node}: PA-family cache key layout differs")
        generations = node / "generations"
        if not generations.is_dir():
            raise AssertionError(f"{node}: PA-family cache generations are missing")
        generation_nodes = list(generations.iterdir())
        if not generation_nodes:
            raise AssertionError(f"{node}: PA-family cache generations are empty")
        seen_generations: set[str] = set()
        for generation_node in generation_nodes:
            if (not generation_node.is_dir()
                    or PA_FAMILY_CACHE_NODE_SHA256.fullmatch(generation_node.name) is None):
                raise AssertionError(f"{generation_node}: invalid PA-family cache generation node")
            normalized_generation = generation_node.name.casefold()
            if normalized_generation in seen_generations:
                raise AssertionError(f"{generation_node}: duplicate case-insensitive PA-family cache generation")
            seen_generations.add(normalized_generation)
        current_generation = _load_pa_family_cache_pointer(node / "current_generation.json", node.name)
        selected = generations / current_generation
        if not selected.is_dir():
            selected = next((item for item in generation_nodes
                             if item.name.casefold() == current_generation.casefold()), None)
        if selected is None or not selected.is_dir():
            raise AssertionError(f"{node}: PA-family cache current generation is missing")
        try:
            manifest = _verify_pa_family_recovery_tree(
                node, generation_nodes, selected, verify_hashes=verify_hashes
            )
            if manifest is None:
                manifest = validate_pa_family_cache_generation(selected, verify_payload=verify_hashes)
            if any((selected / record["name"]).is_symlink()
                   or (selected / record["name"]).stat().st_size != record["bytes"]
                   for record in manifest["files"]):
                raise PAFamilyCacheError("PA cache payload type or byte count differs")
        except PAFamilyCacheError as exc:
            raise AssertionError(f"{selected}: PA-family cache generation differs") from exc
        if (manifest["cache_key"].casefold() != node.name.casefold()
                or manifest["generation_sha256"].casefold() != current_generation.casefold()):
            raise AssertionError(f"{selected}: PA-family cache pointer differs from manifest")


def verify_artifacts_root(projects: Path, verify_hashes: bool = False) -> None:
    """Run generic artifact checks followed by the SIMION-owned cache check."""
    artifacts = projects.parent
    for owner in ("common", "platform"):
        simion = artifacts / owner / "simion"
        if simion.exists():
            if not simion.is_dir() or {item.name for item in simion.iterdir()} != {"pa_family_cache"}:
                raise AssertionError(f"artifacts/{owner}/simion: unexpected SIMION artifact entries")
            verify_common_pa_family_cache(simion / "pa_family_cache", verify_hashes=verify_hashes)
    verify_generic_artifacts_root(projects, verify_hashes=verify_hashes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--formal-only", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--cache-entry", type=Path)
    parser.add_argument("--expected-cache-role")
    parser.add_argument("--expected-cache-key")
    parser.add_argument("--expected-cache-project")
    parser.add_argument("--allow-noncurrent-generation", action="store_true")
    args = parser.parse_args()
    projects = args.root.resolve()
    if args.cache_entry is not None:
        if projects.name != "projects" or not projects.is_dir():
            raise AssertionError("artifact layout root must be the artifacts/projects directory")
        required = (args.expected_cache_role, args.expected_cache_key, args.expected_cache_project)
        if any(value is None for value in required):
            parser.error("narrow cache verification requires role, key, and project")
        cache_root_name = INTEGRATION_CACHE_ROOT_BY_ROLE.get(args.expected_cache_role)
        if cache_root_name is None:
            parser.error("expected cache role is not registered")
        expected_key_directory = (projects / args.expected_cache_project / "cache"
                                  / cache_root_name / args.expected_cache_key).resolve()
        entry = args.cache_entry.resolve()
        if cache_root_name == "verified_pulse":
            if entry != expected_key_directory:
                raise AssertionError("cache entry path differs from its registered role")
            verify_verified_pulse_cache_entry(entry, workspace_root=projects.parent.parent, verify_hashes=True)
        else:
            try:
                relative_entry = entry.relative_to(expected_key_directory / "generations")
            except ValueError as exc:
                raise AssertionError("cache entry path differs from its registered role") from exc
            if len(relative_entry.parts) != 1 or CACHE_SHA256.fullmatch(relative_entry.name) is None:
                raise AssertionError("cache entry path differs from its registered role")
            manifest = verify_integration_cache_entry(
                entry, expected_role=args.expected_cache_role, expected_key=args.expected_cache_key,
                expected_project_id=args.expected_cache_project, verify_hashes=True,
            )
            pointer = json.loads((expected_key_directory / "current_generation.json").read_text(encoding="utf-8-sig"))
            if (not args.allow_noncurrent_generation
                    and (pointer.get("generation_sha256") != manifest.get("generation_sha256")
                         or pointer.get("payload_sha256") != manifest.get("payload_sha256"))):
                raise AssertionError("cache generation pointer differs from frozen payload")
        print("CACHE_ENTRY=PASS "
              f"ROLE={args.expected_cache_role} KEY={args.expected_cache_key} HASHES=True")
        return
    verify_artifacts_root(projects, verify_hashes=args.verify_hashes)
    repository_root = args.repository_root.resolve() if args.repository_root else None
    project_dirs = [project for project in projects.iterdir() if project.is_dir()]
    for collection in ("components", "assemblies"):
        root = projects.parent / collection
        if root.is_dir():
            project_dirs.extend(project for project in root.iterdir() if project.is_dir())
    if args.project:
        matches = [project for project in project_dirs if project.name == args.project]
        if len(matches) != 1:
            raise FileNotFoundError(f"artifact owner must be unique and present: {args.project}")
        project_dirs = matches
    if args.formal_only:
        for project in project_dirs:
            verify_formal(project, args.verify_hashes, repository_root)
        print(f"FORMAL_ASSET_LAYOUT=PASS PROJECTS={len(project_dirs)} HASHES={args.verify_hashes}")
        return
    totals = [verify_project(project, args.verify_hashes, repository_root) for project in project_dirs]
    print(f"ARTIFACT_LAYOUT=PASS PROJECTS={len(totals)} RUNS={sum(x for x, _ in totals)} "
          f"ARCHIVES={sum(y for _, y in totals)} HASHES={args.verify_hashes}")


if __name__ == "__main__":
    main()
