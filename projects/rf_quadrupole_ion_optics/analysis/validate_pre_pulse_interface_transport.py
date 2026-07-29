"""Validate the topology-free pre-pulse interface-transport contract."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_CONTRACT = (
    PROJECT_ROOT / "config" / "rf_to_oatof_pre_pulse_passive_connector.json"
)
TRANSFER_PHASES = PROJECT_ROOT / "config" / "rf_to_oatof_transfer_phases.json"
CONSUMER_IDS = {
    "pre_pulse_interface_transport",
    "pulse_capture",
    "analyzer_transport",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Return the validated numerical contract; topology stays external."""
    contract = _load(path)
    if (
        contract.get("schema_version") != 1
        or contract.get("role")
        != "rf_to_oatof_pre_pulse_interface_transport"
        or contract.get("phase") != "pre_pulse_interface_transport"
        or contract.get("topology_source") != "resolved_connection"
    ):
        raise ValueError("pre-pulse contract identity differs")
    if set(contract) != {
        "schema_version",
        "role",
        "status",
        "phase",
        "topology_source",
        "inputs",
        "field_runtime",
        "particle_runtime",
        "permissions",
    }:
        raise ValueError("pre-pulse contract contains undeclared authority")
    field = contract["field_runtime"]
    if (
        field.get("included_bases") != ["time_dependent_rf", "oatof_static"]
        or field.get("pulse_enabled") is not False
        or field.get("magnetic_field_enabled") is not False
        or field.get("collision_or_space_charge_enabled") is not False
    ):
        raise ValueError("pre-pulse zero-physics-change field basis differs")
    particle = contract["particle_runtime"]
    if (
        int(particle.get("source_particles", 0)) != 100
        or int(particle.get("rf_steps_per_period", 0)) != 80
        or particle.get("clock_epoch_id") != "instrument_clock_epoch.v1"
        or particle.get("dense_trajectories_saved") is not False
    ):
        raise ValueError("pre-pulse particle runtime differs")
    permissions = contract["permissions"]
    if (
        permissions.get("field_solve_allowed") is not True
        or permissions.get("particle_runtime_allowed") is not True
        or permissions.get("phase_pass_allowed") is not False
        or permissions.get("formal_promotion_allowed") is not False
    ):
        raise ValueError("pre-pulse qualification boundary differs")

    dependency_path = PROJECT_ROOT / contract["inputs"]["explicit_dependencies"]
    dependencies = _load(dependency_path)
    if (
        dependencies.get("schema_version") != 2
        or dependencies.get("role")
        != "rf_to_oatof_semantic_transfer_explicit_source_dependencies"
        or set(dependencies.get("consumer_ids", [])) != CONSUMER_IDS
    ):
        raise ValueError("semantic transfer dependency identity differs")
    records = dependencies.get("dependencies", [])
    for field_name in ("id", "source_repo_path", "frozen_filename", "run_input_name"):
        values = [record.get(field_name) for record in records]
        if not values or len(values) != len(set(values)):
            raise ValueError(f"dependency {field_name} identities are not unique")
    for record in records:
        consumers = record.get("consumers", [])
        if (
            not consumers
            or not set(consumers) <= CONSUMER_IDS
            or len(consumers) != len(set(consumers))
        ):
            raise ValueError(f"dependency consumers differ: {record.get('id')}")
        source = PurePosixPath(str(record["source_repo_path"]))
        frozen = PurePosixPath(str(record["frozen_filename"]))
        if (
            source.is_absolute()
            or ".." in source.parts
            or frozen != PurePosixPath("runtime_snapshot") / source
        ):
            raise ValueError(f"dependency path differs: {record.get('id')}")
        if (
            "pre_pulse_interface_transport" in consumers
            and not REPOSITORY_ROOT.joinpath(*source.parts).is_file()
        ):
            raise ValueError(f"pre-pulse dependency is missing: {record.get('id')}")

    phases = _load(TRANSFER_PHASES)
    phase_ids = [item.get("id") for item in phases.get("phases", [])]
    if (
        phases.get("role") != "rf_to_oatof_semantic_transfer_phases"
        or phases.get("topology_source") != "resolved_connection"
        or phase_ids
        != [
            "pre_pulse_interface_transport",
            "pulse_capture",
            "analyzer_transport",
        ]
    ):
        raise ValueError("semantic transfer phase plan differs")
    return contract


def main() -> None:
    validate_contract()
    print("PRE_PULSE_INTERFACE_TRANSPORT_CONTRACT=PASS PHASE_PASS_ALLOWED=false")


if __name__ == "__main__":
    main()
