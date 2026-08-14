"""Verify artifact v2 structure; hash large formal assets only when requested."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    from common.contracts.artifact_retention import validate_retention
except ModuleNotFoundError:
    from artifact_retention import validate_retention

try:
    from common.contracts.artifact_naming import (
        validate_archive_id,
        validate_formal_asset_name,
        validate_run_id,
        validate_task_id,
    )
except ModuleNotFoundError:
    from artifact_naming import (
        validate_archive_id,
        validate_formal_asset_name,
        validate_run_id,
        validate_task_id,
    )

try:
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from file_identity import file_sha256

try:
    from common.contracts.artifact_identity_archive import (
        legacy_artifact_location,
        validate_identity_archive_manifest,
        validate_plan,
        validate_pruning_journal,
        verify_pruned_inventory,
    )
except ModuleNotFoundError:
    from artifact_identity_archive import (
        legacy_artifact_location,
        validate_identity_archive_manifest,
        validate_plan,
        validate_pruning_journal,
        verify_pruned_inventory,
    )


ALLOWED_PROJECT_ENTRIES = {
    "00_README.txt",
    "formal",
    "runs",
    "archive",
    "scratch",
    "cache",
}
ALLOWED_ARTIFACT_ROOT_ENTRIES = {"projects"}
REQUIRED_RUN_FILES = {"run_config.json", "summary.json", "run_manifest.json"}
LEGACY_POLICY = {
    "migration_kind": "administrative_rename_only",
    "artifact_access": "read_only",
    "new_runs_allowed": False,
    "verification_identity": "recorded_project_id",
    "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
}
INTEGRATION_CACHE_ROLES = {
    "simion_single_flight_frontend": {"simion_single_flight_frontend_pa_cache"},
    "simion_accelerator_overlay": {"simion_accelerator_overlay_pa_cache"},
    "simion_oatof_downstream_pa": {
        "simion_oatof_flight_tube_pa_cache",
        "simion_oatof_reflectron_pa_cache",
    },
}
INTEGRATION_CACHE_ROOT_BY_ROLE = {
    role: root
    for root, roles in INTEGRATION_CACHE_ROLES.items()
    for role in roles
}
CACHE_SHA256 = re.compile(r"[A-Fa-f0-9]{64}")


def verify_record(root: Path, record: dict, verify_hashes: bool) -> Path:
    relative = Path(record["path"])
    if relative.is_absolute():
        raise AssertionError(f"manifest path must be relative: {relative}")
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise AssertionError(f"manifest file is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise AssertionError(f"manifest byte count differs: {path}")
    if verify_hashes and file_sha256(path) != record["sha256"]:
        raise AssertionError(f"manifest SHA-256 differs: {path}")
    return path


def verify_integration_cache_entry(
    entry: Path,
    *,
    expected_role: str,
    expected_key: str,
    expected_project_id: str,
    verify_hashes: bool = True,
) -> dict:
    """Verify one reusable integration PA cache entry and its full inventory."""

    if CACHE_SHA256.fullmatch(expected_key) is None:
        raise AssertionError("cache key is not a SHA-256 identity")
    manifest_path = entry / "cache_manifest.json"
    if not manifest_path.is_file():
        raise AssertionError(f"{entry}: reusable cache manifest is missing")
    if any(not item.is_file() for item in entry.iterdir()):
        raise AssertionError(f"{entry}: reusable cache contains a non-file entry")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    identity = manifest.get("identity", {})
    key_input = manifest.get("cache_key_input")
    solver = identity.get("solver", {}) if isinstance(identity, dict) else {}
    critical_options = (
        identity.get("critical_options", {}) if isinstance(identity, dict) else {}
    )
    if (
        manifest.get("schema_version") != 2
        or manifest.get("role") != expected_role
        or manifest.get("cache_key") != expected_key
        or identity.get("schema_version") != 2
        or identity.get("role") != expected_role
        or identity.get("project_id") != expected_project_id
        or solver.get("name") != "SIMION"
        or not isinstance(solver.get("product_version"), str)
        or not solver.get("product_version")
        or CACHE_SHA256.fullmatch(str(solver.get("executable_sha256", ""))) is None
        or not isinstance(critical_options, dict)
        or not critical_options
        or not isinstance(key_input, str)
    ):
        raise AssertionError(f"{entry}: reusable cache identity differs")
    try:
        key_input_identity = json.loads(key_input)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{entry}: cache key input is invalid JSON") from exc
    derived_key = hashlib.sha256(key_input.encode("utf-8")).hexdigest()
    if derived_key != expected_key or key_input_identity != identity:
        raise AssertionError(f"{entry}: cache key does not bind its identity")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise AssertionError(f"{entry}: reusable cache inventory is incomplete")
    expected = {"cache_manifest.json"}
    for record in records:
        name = record.get("name") if isinstance(record, dict) else None
        if not isinstance(name, str) or Path(name).name != name:
            raise AssertionError(f"{entry}: invalid cache filename")
        if name in expected:
            raise AssertionError(f"{entry}: duplicate cache filename")
        expected.add(name)
        verify_record(entry, {**record, "path": name}, verify_hashes)
    actual = {item.name for item in entry.iterdir() if item.is_file()}
    if actual != expected:
        raise AssertionError(f"{entry}: reusable cache inventory differs")
    payload = actual - {"cache_manifest.json"}
    required_by_role = {
        "simion_single_flight_frontend_pa_cache": {
            "frontend.gem", "frontend.pa#", "frontend.pa0"
        },
        "simion_accelerator_overlay_pa_cache": {
            "accelerator_overlay.gem",
            "accelerator_overlay.pa#",
            "basis_build.json",
            *(f"accelerator_overlay.pa{electrode}" for electrode in range(20)),
        },
        "simion_oatof_flight_tube_pa_cache": {
            "flight_tube_ground.pa#", "flight_tube_ground.pa0"
        },
        "simion_oatof_reflectron_pa_cache": {
            "reflectron.pa#", "reflectron.pa0", "reflectron.pa1"
        },
    }
    required = required_by_role.get(expected_role)
    if required is None or not required.issubset(payload):
        raise AssertionError(f"{entry}: reusable cache PA family is incomplete")
    return manifest


def _verify_integration_content_caches(
    project: Path, cache: Path, verify_hashes: bool
) -> None:
    """Verify registered integration PA entries, including visible legacy entries."""

    for cache_name, required_name in (
        ("simion_accelerator_overlay", "accelerator_overlay.pa0"),
        ("simion_oatof_downstream_pa", None),
        ("simion_single_flight_frontend", "frontend.pa0"),
    ):
        content_root = cache / cache_name
        if not content_root.exists():
            continue
        for entry in content_root.iterdir():
            if not entry.is_dir() or re.fullmatch(r"[a-f0-9]{64}", entry.name) is None:
                raise AssertionError(f"{entry}: invalid content-addressed cache entry")
            files = {item.name for item in entry.iterdir() if item.is_file()}
            manifest_path = entry / "cache_manifest.json"
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                if manifest_path.is_file()
                else None
            )
            if isinstance(manifest, dict) and manifest.get("schema_version") == 2:
                role = str(manifest.get("role", ""))
                if role not in INTEGRATION_CACHE_ROLES[cache_name]:
                    raise AssertionError(f"{entry}: cache role is not registered")
                verify_integration_cache_entry(
                    entry,
                    expected_role=role,
                    expected_key=entry.name,
                    expected_project_id=project.name,
                    verify_hashes=verify_hashes,
                )
                continue
            # Schema-v1/no-manifest entries predate the reusable-cache contract.
            # They remain layout-visible until separately removed, but runtime
            # lookup must treat them as misses.
            if required_name is not None and required_name not in files:
                raise AssertionError(f"{entry}: required cached PA is missing")
            if cache_name == "simion_oatof_downstream_pa":
                pa0_files = [name for name in files if name.endswith(".pa0")]
                stems = {name[:-4] for name in pa0_files}
                if len(stems) != 1:
                    raise AssertionError(f"{entry}: downstream PA identity is ambiguous")
                stem = next(iter(stems))
                if not any(name.startswith(stem + ".pa") for name in files):
                    raise AssertionError(f"{entry}: downstream PA family is incomplete")
            elif cache_name == "simion_accelerator_overlay":
                required = {
                    "accelerator_overlay.gem",
                    "basis_build.json",
                    "cache_manifest.json",
                    *(f"accelerator_overlay.pa{electrode}" for electrode in range(20)),
                }
                if not required.issubset(files):
                    raise AssertionError(f"{entry}: accelerator overlay PA family is incomplete")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                basis = json.loads(
                    (entry / "basis_build.json").read_text(encoding="utf-8-sig")
                )
                if (
                    manifest.get("schema_version") != 1
                    or manifest.get("role") != "simion_accelerator_overlay_pa_cache"
                    or manifest.get("cache_key") != entry.name
                    or manifest.get("basis_count") != 20
                    or basis.get("schema_version") != 1
                    or basis.get("role") != "simion_accelerator_overlay_basis_build"
                    or basis.get("status") != "pass"
                    or basis.get("basis_array_count") != 20
                ):
                    raise AssertionError(f"{entry}: accelerator overlay cache identity differs")


def verify_cache(project: Path, verify_hashes: bool = False) -> None:
    """Validate the narrowly registered, disposable project cache layout."""

    cache = project / "cache"
    if not cache.exists():
        return
    allowed = {
        "simion_accelerator_overlay",
        "simion_pa_basis",
        "simion_oatof_downstream_pa",
        "simion_single_flight_frontend",
    }
    unexpected = {entry.name for entry in cache.iterdir()} - allowed
    if unexpected:
        raise AssertionError(f"{project.name}: unexpected cache entries: {sorted(unexpected)}")
    basis_root = cache / "simion_pa_basis"
    for basis in (
        item for item in basis_root.iterdir() if item.is_dir()
    ) if basis_root.exists() else ():
        if re.fullmatch(r"[A-F0-9]{64}", basis.name) is None:
            raise AssertionError(f"{basis}: invalid PA-basis fingerprint directory")
        manifest_path = basis / "manifest.json"
        if not manifest_path.is_file():
            raise AssertionError(f"{basis}: cache manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        identity = manifest.get("identity", {})
        if (
            manifest.get("schema_version") != 1
            or manifest.get("role") != "multipole_simion_pa_basis_cache"
            or manifest.get("fingerprint_sha256") != basis.name
            or identity.get("project_id") != project.name
        ):
            raise AssertionError(f"{basis}: cache manifest identity differs")
        records = manifest.get("files")
        if not isinstance(records, list) or len(records) < 3:
            raise AssertionError(f"{basis}: cache file inventory is incomplete")
        expected = {"manifest.json"}
        for record in records:
            name = record.get("name")
            if not isinstance(name, str) or Path(name).name != name:
                raise AssertionError(f"{basis}: invalid cache filename")
            expected.add(name)
            verify_record(basis, {**record, "path": name}, verify_hashes)
        actual = {item.name for item in basis.iterdir() if item.is_file()}
        if actual != expected:
            raise AssertionError(f"{basis}: cache inventory differs")
    _verify_integration_content_caches(project, cache, verify_hashes)


def legacy_identity(repository_root: Path, project_id: str) -> dict | None:
    """Resolve one retired artifact identity without requiring its old source tree."""

    matches: list[tuple[str, dict]] = []
    active_ids: set[str] = set()
    for descriptor_path in sorted(
        (repository_root / "projects").glob("*/config/project.json")
    ):
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
        current_id = descriptor.get("project_id")
        if current_id != descriptor_path.parents[1].name:
            raise AssertionError(f"project descriptor identity differs: {descriptor_path}")
        active_ids.add(current_id)
        matches.extend(
            (current_id, mapping)
            for mapping in descriptor.get("legacy_identities", [])
            if mapping.get("project_id") == project_id
        )
    if len(matches) > 1:
        raise AssertionError(f"{project_id}: duplicate legacy identity mappings")
    if not matches:
        return None
    if project_id in active_ids:
        raise AssertionError(f"{project_id}: legacy identity is still an active project")
    current_id, mapping = matches[0]
    expected = LEGACY_POLICY
    for field, value in expected.items():
        if mapping.get(field) != value:
            raise AssertionError(f"{project_id}: invalid legacy identity field {field}")
    try:
        legacy_artifact_location(mapping, current_id)
    except ValueError as exc:
        raise AssertionError(f"{project_id}: invalid legacy artifact location") from exc
    return mapping


def verify_retired_validation_record(record: dict, project_id: str) -> None:
    """Validate immutable provenance whose retired repository path no longer exists."""

    try:
        relative = Path(record["path"])
        bytes_count = int(record["bytes"])
        sha256 = str(record["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError(
            f"{project_id}: invalid retired validation contract record"
        ) from exc
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 4
        or relative.parts[:3] != ("projects", project_id, "config")
        or relative.suffix.lower() != ".json"
    ):
        raise AssertionError(
            f"{project_id}: retired validation contract path differs"
        )
    if bytes_count <= 0 or re.fullmatch(r"[0-9A-Fa-f]{64}", sha256) is None:
        raise AssertionError(
            f"{project_id}: retired validation contract identity differs"
        )


def verify_formal(project: Path, verify_hashes: bool = False, repository_root: Path | None = None) -> None:
    formal = project / "formal"
    if formal.exists():
        retired_identity = (
            legacy_identity(repository_root, project.name)
            if repository_root is not None
            else None
        )
        asset_manifest_path = formal / "asset_manifest.json"
        if not asset_manifest_path.is_file():
            raise AssertionError(f"{project.name}: formal/asset_manifest.json is missing")
        manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("schema_version") != 1 or manifest.get("role") != "formal_asset_manifest":
            raise AssertionError(f"{project.name}: invalid formal asset manifest identity")
        if manifest.get("project") != project.name:
            raise AssertionError(f"{project.name}: formal asset manifest project differs")
        source = manifest.get("source_run", {})
        source_id = source.get("run_id")
        validate_run_id(source_id)
        if source.get("path") != f"runs/{source_id}":
            raise AssertionError(f"{project.name}: formal source run path differs")
        for role in ("run_config", "summary", "run_manifest"):
            verify_record(project, source[role], verify_hashes)
        assets = manifest.get("assets", {})
        if not assets:
            raise AssertionError(f"{project.name}: formal asset manifest has no assets")
        for record in assets.values():
            verify_record(formal, record, verify_hashes)
        if repository_root is not None:
            if retired_identity is None:
                verify_record(
                    repository_root, manifest["validation_contract"], verify_hashes
                )
            else:
                verify_retired_validation_record(
                    manifest["validation_contract"], project.name
                )
        if retired_identity is None:
            for role in ("comsol_model", "solidworks_assembly"):
                if role in assets and "naming_exception" not in assets[role]:
                    validate_formal_asset_name(
                        Path(assets[role]["path"]).name, project.name
                    )


def verify_project(
    project: Path, verify_hashes: bool = False, repository_root: Path | None = None
) -> tuple[int, int]:
    unexpected = {entry.name for entry in project.iterdir()} - ALLOWED_PROJECT_ENTRIES
    if unexpected:
        raise AssertionError(f"{project.name}: unexpected top-level entries: {sorted(unexpected)}")
    if not (project / "00_README.txt").is_file():
        raise AssertionError(f"{project.name}: 00_README.txt is missing")
    verify_formal(project, verify_hashes, repository_root)
    verify_cache(project, verify_hashes)

    run_count = 0
    runs = project / "runs"
    if runs.exists():
        for run in (item for item in runs.iterdir() if item.is_dir()):
            validate_run_id(run.name)
            missing = REQUIRED_RUN_FILES - {item.name for item in run.iterdir() if item.is_file()}
            if missing:
                raise AssertionError(f"{run}: missing {sorted(missing)}")
            config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
            if config.get("run_id") != run.name or manifest.get("run_id") != run.name:
                raise AssertionError(f"{run}: folder, config, and manifest run_id differ")
            if manifest.get("schema_version") == 2:
                retention = validate_retention(config.get("artifact_retention"))
                if manifest.get("artifact_retention") != {
                    "policy_version": retention.policy_version,
                    "class": retention.class_id,
                    "reason": retention.reason,
                }:
                    raise AssertionError(f"{run}: retention identity differs")
            run_count += 1

    archive_count = 0
    archive_root = project / "archive"
    if archive_root.exists():
        for archive in (item for item in archive_root.iterdir() if item.is_dir()):
            validate_archive_id(archive.name)
            manifest_path = archive / "archive_manifest.json"
            if not manifest_path.is_file():
                raise AssertionError(f"{archive}: archive_manifest.json is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if manifest.get("archive_id") != archive.name:
                raise AssertionError(f"{archive}: folder and manifest archive_id differ")
            if manifest.get("role") == "artifact_identity_archive_manifest":
                migration_path = archive / "identity_migration_manifest.json"
                if not migration_path.is_file():
                    raise AssertionError(f"{archive}: identity migration manifest is missing")
                migration = json.loads(migration_path.read_text(encoding="utf-8-sig"))
                try:
                    validate_plan(migration)
                    validate_identity_archive_manifest(manifest, migration)
                except ValueError as exc:
                    raise AssertionError(f"{archive}: identity migration contract differs") from exc
                if (
                    migration.get("status") != "relocated_verified"
                    or migration.get("current_project_id") != project.name
                    or migration.get("destination_root")
                    != f"{project.name}/archive/{archive.name}/legacy-project-root"
                ):
                    raise AssertionError(f"{archive}: relocated identity differs")
                pruning_path = archive / "pruning_manifest.json"
                if pruning_path.exists():
                    pruning = json.loads(pruning_path.read_text(encoding="utf-8-sig"))
                    try:
                        validate_pruning_journal(pruning, migration)
                    except ValueError as exc:
                        raise AssertionError(f"{archive}: pruning journal differs") from exc
                    if pruning.get("state") != "complete":
                        raise AssertionError(f"{archive}: pruning journal is incomplete")
                    verify_pruned_inventory(
                        migration,
                        project.parent,
                        verify_hashes=verify_hashes,
                    )
                elif manifest.get("deletion_performed"):
                    raise AssertionError(f"{archive}: pruning journal is missing")
            archive_count += 1
    scratch = project / "scratch"
    if scratch.exists():
        for task in (item for item in scratch.iterdir() if item.is_dir()):
            validate_task_id(task.name)
    return run_count, archive_count


def verify_artifacts_root(projects: Path) -> None:
    """Reject unregistered files or sibling trees beside artifacts/projects."""
    if projects.name != "projects" or not projects.is_dir():
        raise AssertionError("artifact layout root must be the artifacts/projects directory")
    artifacts = projects.parent
    unexpected = {entry.name for entry in artifacts.iterdir()} - ALLOWED_ARTIFACT_ROOT_ENTRIES
    if unexpected:
        raise AssertionError(
            f"artifacts: unexpected top-level entries: {sorted(unexpected)}"
        )


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
    args = parser.parse_args()
    projects = args.root.resolve()
    verify_artifacts_root(projects)
    if args.cache_entry is not None:
        required = (
            args.expected_cache_role,
            args.expected_cache_key,
            args.expected_cache_project,
        )
        if any(value is None for value in required):
            parser.error("narrow cache verification requires role, key, and project")
        cache_root_name = INTEGRATION_CACHE_ROOT_BY_ROLE.get(
            args.expected_cache_role
        )
        if cache_root_name is None:
            parser.error("expected cache role is not registered")
        expected_entry = (
            projects
            / args.expected_cache_project
            / "cache"
            / cache_root_name
            / args.expected_cache_key
        ).resolve()
        entry = args.cache_entry.resolve()
        if entry != expected_entry:
            raise AssertionError("cache entry path differs from its registered role")
        verify_integration_cache_entry(
            entry,
            expected_role=args.expected_cache_role,
            expected_key=args.expected_cache_key,
            expected_project_id=args.expected_cache_project,
            verify_hashes=True,
        )
        print(
            "CACHE_ENTRY=PASS "
            f"ROLE={args.expected_cache_role} KEY={args.expected_cache_key}"
        )
        return
    repository_root = args.repository_root.resolve() if args.repository_root else None
    project_dirs = [project for project in projects.iterdir() if project.is_dir()]
    if args.project:
        selected = projects / args.project
        if not selected.is_dir():
            raise FileNotFoundError(f"artifact project is absent: {selected}")
        project_dirs = [selected]
    if args.formal_only:
        for project in project_dirs:
            verify_formal(project, args.verify_hashes, repository_root)
        print(f"FORMAL_ASSET_LAYOUT=PASS PROJECTS={len(project_dirs)} HASHES={args.verify_hashes}")
        return
    totals = [verify_project(project, args.verify_hashes, repository_root) for project in project_dirs]
    print(f"ARTIFACT_LAYOUT=PASS PROJECTS={len(totals)} RUNS={sum(x for x, _ in totals)} ARCHIVES={sum(y for _, y in totals)}")


if __name__ == "__main__":
    main()
