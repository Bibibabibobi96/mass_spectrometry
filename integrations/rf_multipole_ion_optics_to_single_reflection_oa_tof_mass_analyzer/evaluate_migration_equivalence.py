"""Evaluate the frozen RF-to-oaTOF zero-physics-change migration claim."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.verify_run_manifest import verify_record


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
STAGE_MODES = {
    "pre_pulse_interface_transport": (
        "rf_to_oatof_pre_pulse_interface_transport_n100"
    ),
    "pulse_capture": "rf_to_oatof_pulse_capture_n100",
    "analyzer_transport": "rf_to_oatof_analyzer_transport_n100",
}
NEW_PROJECT_ID = "rf_quadrupole_ion_optics"
RESULT_SCHEMA = "migration_equivalence_result.schema.json"


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object, accepting the PowerShell 5.1 UTF-8 BOM."""

    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return value


def workspace_path(workspace_root: Path, value: str) -> Path:
    """Resolve one portable workspace-relative path without allowing escape."""

    relative = Path(value)
    if relative.is_absolute():
        raise ContractError(f"workspace path must be relative: {value}")
    root = workspace_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"workspace path escapes its root: {value}") from exc
    return candidate


def portable_path(path: Path, workspace_root: Path) -> str:
    """Return one workspace-relative POSIX path."""

    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path is outside the workspace: {path}") from exc


def verify_file_record(record: dict[str, Any], workspace_root: Path) -> Path:
    """Verify the exact path, byte count and SHA-256 of a frozen oracle file."""

    path = workspace_path(workspace_root, str(record["path"]))
    if not path.is_file():
        raise ContractError(f"frozen oracle file is missing: {record['path']}")
    if path.stat().st_size != int(record["bytes"]):
        raise ContractError(f"frozen oracle byte count changed: {record['path']}")
    if file_sha256(path) != record["sha256"]:
        raise ContractError(f"frozen oracle SHA-256 changed: {record['path']}")
    return path


def verify_manifest(
    path: Path,
    *,
    run_id: str,
    project_id: str,
    mode: str,
) -> dict[str, Any]:
    """Verify the identity and terminal success state of one stage run."""

    manifest = load_json(path)
    expected = {
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "project": project_id,
        "mode": mode,
        "status": "success",
    }
    changed = [
        name for name, value in expected.items() if manifest.get(name) != value
    ]
    if changed:
        raise ContractError(
            f"run manifest identity/status differs at {path}: {', '.join(changed)}"
        )
    return manifest


def verify_manifest_output(
    manifest: dict[str, Any],
    path: Path,
) -> None:
    """Require one current file to be hash-bound as a manifest output."""

    resolved = path.resolve()
    matches = [
        item
        for item in manifest.get("outputs", [])
        if isinstance(item, dict)
        and Path(str(item.get("path", ""))).resolve() == resolved
    ]
    if len(matches) != 1:
        raise ContractError(f"run manifest does not bind one output: {path}")
    try:
        verify_record("output", matches[0])
    except AssertionError as exc:
        raise ContractError(str(exc)) from exc


def verify_legacy_oracle(
    oracle: dict[str, Any],
    *,
    repo_root: Path,
    workspace_root: Path,
) -> None:
    """Verify the administrative rename mapping and all frozen oracle files."""

    if (
        oracle.get("schema_version") != 2
        or oracle.get("role") != "connection_profile_migration_oracles"
        or oracle.get("integration_id") != INTEGRATION_ID
    ):
        raise ContractError("migration oracle identity is invalid")
    legacy = oracle["legacy_identity"]
    descriptor_path = (repo_root / legacy["current_project_descriptor"]).resolve()
    descriptor = load_json(descriptor_path)
    if descriptor.get("project_id") != NEW_PROJECT_ID:
        raise ContractError("current RF project descriptor identity differs")
    mappings = [
        item
        for item in descriptor.get("legacy_identities", [])
        if item.get("mapping_id") == legacy["mapping_id"]
    ]
    if len(mappings) != 1:
        raise ContractError("legacy administrative mapping does not resolve uniquely")
    mapping = mappings[0]
    expected_mapping = {
        "project_id": legacy["legacy_project_id"],
        "artifact_root": legacy["artifact_root"],
        "artifact_access": "read_only",
        "new_runs_allowed": False,
    }
    if any(mapping.get(name) != value for name, value in expected_mapping.items()):
        raise ContractError("legacy administrative mapping differs from the oracle")

    source = oracle["source_identity"]
    source_manifest_path = verify_file_record(source["manifest"], workspace_root)
    verify_file_record(source["events"], workspace_root)
    verify_file_record(source["metadata"], workspace_root)
    verify_manifest(
        source_manifest_path,
        run_id=source["run_id"],
        project_id=source["project_id"],
        mode=load_json(source_manifest_path)["mode"],
    )
    for profile in oracle["profiles"]:
        phases = {item["phase"] for item in profile["legacy_runs"]}
        if phases != set(STAGE_MODES):
            raise ContractError(
                f"legacy profile does not contain exactly three phases: "
                f"{profile['connection_profile_id']}"
            )
        for stage in profile["legacy_runs"]:
            manifest_path = verify_file_record(stage["manifest"], workspace_root)
            verify_file_record(stage["summary"], workspace_root)
            for record in stage["results"].values():
                verify_file_record(record, workspace_root)
            verify_manifest(
                manifest_path,
                run_id=stage["run_id"],
                project_id=stage["project_id"],
                mode=stage["mode"],
            )


def csv_identity_set(path: Path, fields: list[str]) -> tuple[set[tuple[str, ...]], int]:
    """Read a CSV as an exact set of selected serialized identity tuples."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headings = set(reader.fieldnames or [])
        missing = [field for field in fields if field not in headings]
        if missing:
            raise ContractError(
                f"CSV identity fields are missing at {path}: {', '.join(missing)}"
            )
        rows = [tuple(row[field] for field in fields) for row in reader]
    identities = set(rows)
    if len(identities) != len(rows):
        raise ContractError(f"CSV identity tuples are not unique: {path}")
    return identities, len(rows)


def source_identity_from_run_config(run_config: dict[str, Any]) -> dict[str, str]:
    """Read the canonical source identity frozen by the integration publisher."""

    identity = run_config.get("source_particle_identity")
    if not isinstance(identity, dict):
        raise ContractError("integration run_config lacks source_particle_identity")
    required = (
        "run_id",
        "project_id",
        "manifest_sha256",
        "event_sha256",
        "metadata_sha256",
    )
    if any(not isinstance(identity.get(name), str) for name in required):
        raise ContractError("integration source_particle_identity is incomplete")
    return {name: identity[name] for name in required}


def stage_runs_from_config(
    run_config: dict[str, Any],
    *,
    workspace_root: Path,
) -> dict[str, tuple[dict[str, Any], Path]]:
    """Verify and return the three new stage runs frozen by the publisher."""

    raw_stages = run_config.get("stage_runs")
    if not isinstance(raw_stages, list) or len(raw_stages) != 3:
        raise ContractError("integration run_config must freeze exactly three stage runs")
    stages: dict[str, tuple[dict[str, Any], Path]] = {}
    for stage in raw_stages:
        if not isinstance(stage, dict):
            raise ContractError("integration stage run entry must be an object")
        phase = stage.get("phase")
        if phase not in STAGE_MODES or phase in stages:
            raise ContractError(f"integration stage phase is invalid: {phase!r}")
        run_path = workspace_path(workspace_root, str(stage["path"]))
        if run_path.name != stage["run_id"]:
            raise ContractError(f"integration stage path/run_id differs: {phase}")
        manifest_path = run_path / "run_manifest.json"
        if file_sha256(manifest_path) != stage["manifest_sha256"]:
            raise ContractError(f"integration stage manifest SHA-256 differs: {phase}")
        manifest = verify_manifest(
            manifest_path,
            run_id=stage["run_id"],
            project_id=NEW_PROJECT_ID,
            mode=STAGE_MODES[phase],
        )
        try:
            verify_record("run_config", manifest["run_config"])
        except (AssertionError, KeyError) as exc:
            raise ContractError(
                f"integration stage manifest does not bind run_config: {phase}"
            ) from exc
        if Path(manifest["run_config"]["path"]).resolve().parent != run_path:
            raise ContractError(f"integration stage run_config is nonlocal: {phase}")
        stages[phase] = (stage, run_path)
    return stages


def evaluate_profile(
    *,
    profile_id: str,
    run_path: Path,
    oracle_profile: dict[str, Any],
    preregistration: dict[str, Any],
    oracle_source_identity: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    """Evaluate one fully published integration run against one legacy profile."""

    run_config = load_json(run_path / "run_config.json")
    summary = load_json(run_path / "summary.json")
    manifest = load_json(run_path / "run_manifest.json")
    receipt = load_json(run_path / "execution_receipt.json")
    resolved = load_json(run_path / "resolved_connection.json")
    budget_path = run_path / "resolved_engineering_budget.json"
    budget = load_json(budget_path)
    composition_plan = run_path / "composition_plan.json"
    if not composition_plan.is_file():
        raise ContractError(f"integration composition plan is missing: {run_path}")
    expected_run_id = run_path.name
    verify_manifest(
        run_path / "run_manifest.json",
        run_id=expected_run_id,
        project_id=INTEGRATION_ID,
        mode="migration_equivalence_execution",
    )
    try:
        verify_record("run_config", manifest["run_config"])
    except (AssertionError, KeyError) as exc:
        raise ContractError(
            "integration manifest does not bind the current run_config"
        ) from exc
    if Path(manifest["run_config"]["path"]).resolve() != (
        run_path / "run_config.json"
    ).resolve():
        raise ContractError("integration manifest run_config is nonlocal")
    if (
        receipt.get("role") != "integration_migration_execution_receipt"
        or receipt.get("integration_run_id") != expected_run_id
        or receipt.get("connection_profile_id") != profile_id
        or receipt.get("execution_status")
        != "completed_not_equivalence_evaluated"
        or receipt.get("equivalence_status") != "BLOCKED"
    ):
        raise ContractError("integration execution receipt identity/state differs")
    if receipt.get("composition_plan_sha256") != file_sha256(composition_plan):
        raise ContractError("execution receipt composition-plan SHA-256 differs")
    if receipt.get("resolved_connection_sha256") != file_sha256(
        run_path / "resolved_connection.json"
    ):
        raise ContractError("execution receipt resolved-connection SHA-256 differs")
    if receipt.get("resolved_engineering_budget_sha256") != file_sha256(
        budget_path
    ):
        raise ContractError("execution receipt engineering-budget SHA-256 differs")
    if (
        resolved.get("selection", {}).get("connection_profile_id") != profile_id
        or run_config.get("connection_profile_id") != profile_id
        or summary.get("connection_profile_id") != profile_id
    ):
        raise ContractError("integration profile identity differs across its evidence")
    if (
        budget.get("role") != "integration_resolved_engineering_budget"
        or budget.get("integration_id") != INTEGRATION_ID
        or budget.get("connection_profile_id") != profile_id
        or budget.get("particle_count") != 100
        or budget.get("retention_class") != "compact"
    ):
        raise ContractError("integration resolved engineering-budget scope differs")

    expected_source = {
        "run_id": oracle_source_identity["run_id"],
        "project_id": oracle_source_identity["project_id"],
        "manifest_sha256": oracle_source_identity["manifest"]["sha256"],
        "event_sha256": oracle_source_identity["events"]["sha256"],
        "metadata_sha256": oracle_source_identity["metadata"]["sha256"],
    }
    if (
        budget.get("source_identity") != expected_source
        or budget.get("particle_count")
        != oracle_source_identity["particle_count"]
    ):
        raise ContractError(
            "resolved engineering budget and oracle source identities differ"
        )
    source_exact = source_identity_from_run_config(run_config) == expected_source
    stages = stage_runs_from_config(run_config, workspace_root=workspace_root)
    analyzer_run_path = stages["analyzer_transport"][1]
    analyzer_manifest = load_json(analyzer_run_path / "run_manifest.json")
    analyzer_summary_path = analyzer_run_path / "summary.json"
    verify_manifest_output(analyzer_manifest, analyzer_summary_path)
    analyzer_summary = load_json(analyzer_summary_path)
    actual_census = analyzer_summary.get("census")
    census_exact = isinstance(actual_census, dict) and all(
        actual_census.get(name) == expected
        for name, expected in oracle_profile["census"].items()
    )

    legacy_stages = {
        stage["phase"]: stage for stage in oracle_profile["legacy_runs"]
    }
    comparisons: list[dict[str, Any]] = []
    for requirement in preregistration["comparison_requirements"][
        "exact_particle_event_sets"
    ]:
        phase = requirement["phase"]
        legacy_record = legacy_stages[phase]["results"][
            requirement["legacy_result"]
        ]
        legacy_path = workspace_path(workspace_root, legacy_record["path"])
        new_path = stages[phase][1] / "results" / requirement["new_result"]
        if not new_path.is_file():
            raise ContractError(f"new migration result is missing: {new_path}")
        stage_manifest = load_json(stages[phase][1] / "run_manifest.json")
        verify_manifest_output(stage_manifest, new_path)
        legacy_set, legacy_rows = csv_identity_set(
            legacy_path, requirement["identity_fields"]
        )
        new_set, new_rows = csv_identity_set(
            new_path, requirement["identity_fields"]
        )
        passed = legacy_set == new_set
        comparisons.append(
            {
                "phase": phase,
                "legacy_result": requirement["legacy_result"],
                "status": "PASS" if passed else "FAIL",
                "rows": new_rows,
            }
        )
        if passed and legacy_rows != new_rows:
            raise ContractError("equal CSV identity sets have inconsistent row counts")

    passed = (
        source_exact
        and census_exact
        and all(item["status"] == "PASS" for item in comparisons)
    )
    return {
        "connection_profile_id": profile_id,
        "integration_run_id": expected_run_id,
        "status": "PASS" if passed else "FAIL",
        "source_identity_exact": source_exact,
        "census_exact": census_exact,
        "particle_event_sets": comparisons,
        "stage_runs": [
            {
                "phase": phase,
                "run_id": stage["run_id"],
                "manifest_sha256": stage["manifest_sha256"],
            }
            for phase, (stage, _) in sorted(stages.items())
        ],
    }


def evaluate_migration(
    *,
    repo_root: Path,
    workspace_root: Path,
    oracle_path: Path,
    preregistration_path: Path,
    profile_runs: dict[str, Path],
) -> dict[str, Any]:
    """Evaluate both preregistered profiles and return one schema-valid result."""

    oracle = load_json(oracle_path)
    preregistration = load_json(preregistration_path)
    validate_schema(
        preregistration, "migration_equivalence_preregistration.schema.json"
    )
    if preregistration["integration_id"] != INTEGRATION_ID:
        raise ContractError("migration preregistration integration identity differs")
    oracle_reference = preregistration["legacy_oracle"]
    expected_oracle = (repo_root / oracle_reference["path"]).resolve()
    if expected_oracle != oracle_path.resolve():
        raise ContractError("preregistration points to a different migration oracle")
    if file_sha256(oracle_path) != oracle_reference["sha256"]:
        raise ContractError("migration oracle SHA-256 differs from preregistration")
    verify_legacy_oracle(
        oracle, repo_root=repo_root, workspace_root=workspace_root
    )

    expected_profiles = {
        item["connection_profile_id"] for item in preregistration["profiles"]
    }
    if set(profile_runs) != expected_profiles:
        raise ContractError("exactly one new run is required for every profile")
    oracle_profiles = {
        item["connection_profile_id"]: item for item in oracle["profiles"]
    }
    if set(oracle_profiles) != expected_profiles:
        raise ContractError("oracle and preregistration profile sets differ")
    profiles = [
        evaluate_profile(
            profile_id=profile_id,
            run_path=profile_runs[profile_id].resolve(),
            oracle_profile=oracle_profiles[profile_id],
            preregistration=preregistration,
            oracle_source_identity=oracle["source_identity"],
            workspace_root=workspace_root,
        )
        for profile_id in sorted(expected_profiles)
    ]
    continuous = preregistration["comparison_requirements"]["continuous_state"]
    result = {
        "schema_version": 1,
        "role": "integration_migration_equivalence_result",
        "integration_id": INTEGRATION_ID,
        "status": (
            "PASS"
            if all(item["status"] == "PASS" for item in profiles)
            else "FAIL"
        ),
        "decision_scope": "zero_physics_change_functional_migration",
        "oracle": {
            "path": portable_path(oracle_path, workspace_root),
            "sha256": file_sha256(oracle_path),
        },
        "preregistration": {
            "path": portable_path(preregistration_path, workspace_root),
            "sha256": file_sha256(preregistration_path),
        },
        "profiles": profiles,
        "continuous_state": {
            "status": "NOT_EVALUATED",
            "reason": continuous["reason"],
            "blocks_functional_migration_equivalence": False,
        },
        "claim_limit": continuous["claim_limit"],
    }
    validate_schema(result, RESULT_SCHEMA)
    return result


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish one JSON result on the destination filesystem."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_profile_run(value: str) -> tuple[str, Path]:
    """Parse PROFILE=RUN_DIR."""

    profile_id, separator, run_dir = value.partition("=")
    if not separator or not profile_id or not run_dir:
        raise argparse.ArgumentTypeError("profile runs use PROFILE=RUN_DIR")
    return profile_id, Path(run_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument(
        "--profile-run",
        action="append",
        required=True,
        type=parse_profile_run,
        metavar="PROFILE=RUN_DIR",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    workspace_root = (
        args.workspace_root.resolve()
        if args.workspace_root
        else repo_root.parent.resolve()
    )
    integration_root = Path(__file__).resolve().parent
    oracle_path = (
        args.oracle.resolve()
        if args.oracle
        else integration_root / "config" / "migration_oracles.json"
    )
    preregistration_path = (
        args.preregistration.resolve()
        if args.preregistration
        else integration_root
        / "config"
        / "migration_equivalence_preregistration.json"
    )
    profile_runs = dict(args.profile_run)
    if len(profile_runs) != len(args.profile_run):
        raise SystemExit("duplicate --profile-run profile id")
    result = evaluate_migration(
        repo_root=repo_root,
        workspace_root=workspace_root,
        oracle_path=oracle_path,
        preregistration_path=preregistration_path,
        profile_runs=profile_runs,
    )
    write_json_atomic(args.output, result)
    print(
        f"MIGRATION_EQUIVALENCE={result['status']} "
        f"RESULT={args.output.resolve()}"
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
