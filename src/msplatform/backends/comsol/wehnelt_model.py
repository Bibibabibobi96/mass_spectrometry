"""Wehnelt build-only request and public operation over its three native stages."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from msplatform.components.transverse_helical_filament_wehnelt_electron_gun.resolve_contract import (
    load_json as load_contract_json,
    resolve_contract,
)
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.context import ExecutionContext
from msplatform.io.manifest_records import verify_record
from msplatform.results.artifacts import OpenedArtifact
from .model_execution import UnsolvedModelSpec, build_unsolved_model

PROJECT_ID = "transverse_helical_filament_wehnelt_electron_gun"
BUILD_ONLY_MODE = "build_only_smoke"
COMPILED_INPUT_PATHS = {
    "baseline": "config/baseline.json",
    "numerical_modes": "config/numerical_modes.json",
    "resolved_contract": "config/resolved_model.json",
    "mode": "config/modes/build_only_smoke.json",
}

NATIVE_MODEL = UnsolvedModelSpec(run_label="wehnelt-model",
    matlab_resources=("build_wehnelt_model.m", "phase1_geometry_coil_transverse.m",
        "phase2_electrostatics_coil_transverse.m", "phase4_thermal_emission_coil_transverse.m",
        "load_wehnelt_contract.m", "apply_wehnelt_contract_parameters.m",
        "wehnelt_contract_parameter_bindings.m", "verify_wehnelt_contract_parameters.m",
        "verify_wehnelt_model.m", "comsolstartup.m"),
    build_function="build_wehnelt_model", verify_function="verify_wehnelt_model",
    model_relative_paths=("comsol/ElectronGun_CoilT.mph", "comsol/ElectronGun_CoilT_ES.mph",
        "comsol/transverse_helical_filament_wehnelt_electron_gun__model.mph"))


def build_wehnelt_model(baseline: Mapping[str, Any], modes: Mapping[str, Any], *, mode_id: str,
                        evidence_particle_count: int, context: ExecutionContext, artifact_store=None) -> OpenedArtifact:
    """Build the original three-stage chain and cold-reopen its unsolved CPT model.

    Particle count configures the saved inlet only. This operation performs no
    particle realization, field solution, current estimate or scientific qualification.
    """
    resolved = resolve_wehnelt_build_request(baseline, modes, mode_id=mode_id,
                                            evidence_particle_count=evidence_particle_count)
    return build_unsolved_model(resolved, baseline, modes, action_name="build_wehnelt_model",
                                spec=NATIVE_MODEL, context=context,
                                **({'artifact_store': artifact_store} if artifact_store is not None else {}))


def resolve_wehnelt_build_request(baseline: Mapping[str, Any], modes: Mapping[str, Any], *,
                                 mode_id: str, evidence_particle_count: int) -> dict:
    """Use the canonical resolver and the same build-only applicability for queries."""
    resolved = resolve_contract(copy.deepcopy(dict(baseline)), copy.deepcopy(dict(modes)),
                                mode_id, evidence_particle_count)
    if resolved["numerical"]["execution_mode"] != "build_only":
        raise ContractError("build_wehnelt_model currently implements only the selected build_only mode")
    return resolved


def load_compiled_wehnelt_inputs(path: Path) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Verify the registered input bundle and return its public-operation arguments."""
    document = load_contract_json(path)
    if (document.get("schema_version") != 1 or document.get("role") != "compiled_execution_inputs"
            or document.get("project_id") != PROJECT_ID):
        raise ValueError("Compiled Wehnelt input identity differs")
    records = document.get("files")
    if not isinstance(records, list):
        raise ValueError("Compiled Wehnelt input files must be an array")
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            raise ValueError("Compiled Wehnelt input record is invalid")
        name = record["name"]
        if name in by_name or name not in COMPILED_INPUT_PATHS:
            raise ValueError("Compiled Wehnelt input is missing, unknown or ambiguous: " + name)
        by_name[name] = record
    if set(by_name) != set(COMPILED_INPUT_PATHS):
        missing = sorted(set(COMPILED_INPUT_PATHS) - set(by_name))
        raise ValueError("Compiled Wehnelt input is missing: " + ", ".join(missing))
    root = Path(document["root"]).resolve(strict=True)
    documents = {}
    for name, relative in COMPILED_INPUT_PATHS.items():
        record = by_name[name]
        if record.get("relative_path") != relative:
            raise ValueError("Compiled Wehnelt input path differs: " + name)
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root):
            raise ValueError("Compiled Wehnelt input escapes its frozen root: " + name)
        verify_record(name, dict(path=str(target), exists=True,
                                 bytes=record["bytes"], sha256=record["sha256"]))
        documents[name] = load_contract_json(target)
    mode = documents["mode"]
    if (mode.get("mode") != BUILD_ONLY_MODE or mode.get("numerical_contract")
            != "../numerical_modes.json#/modes/" + BUILD_ONLY_MODE):
        raise ValueError("Compiled Wehnelt mode identity differs")
    evidence = documents["resolved_contract"].get("evidence", {})
    count = evidence.get("requested_particle_count") if isinstance(evidence, dict) else None
    if type(count) is not int:
        raise ValueError("Compiled Wehnelt resolved contract requires an explicit particle count")
    expected = resolve_wehnelt_build_request(
        documents["baseline"], documents["numerical_modes"],
        mode_id=BUILD_ONLY_MODE, evidence_particle_count=count,
    )
    if documents["resolved_contract"] != expected:
        raise ValueError("Frozen Wehnelt baseline, numerical mode, and resolved contract differ")
    return documents["baseline"], documents["numerical_modes"], count
