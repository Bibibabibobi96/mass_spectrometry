"""Wehnelt build-only request and public operation over its three native stages."""
from __future__ import annotations
import copy
from typing import Any, Mapping
from msplatform.components.transverse_helical_filament_wehnelt_electron_gun.resolve_contract import resolve_contract
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution.context import ExecutionContext
from msplatform.results.artifacts import OpenedArtifact
from .model_execution import UnsolvedModelSpec, build_unsolved_model

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
                        evidence_particle_count: int, context: ExecutionContext) -> OpenedArtifact:
    """Build the original three-stage chain and cold-reopen its unsolved CPT model.

    Particle count configures the saved inlet only. This operation performs no
    particle realization, field solution, current estimate or scientific qualification.
    """
    resolved = resolve_wehnelt_build_request(baseline, modes, mode_id=mode_id,
                                            evidence_particle_count=evidence_particle_count)
    return build_unsolved_model(resolved, baseline, modes, action_name="build_wehnelt_model",
                                spec=NATIVE_MODEL, context=context)


def resolve_wehnelt_build_request(baseline: Mapping[str, Any], modes: Mapping[str, Any], *,
                                 mode_id: str, evidence_particle_count: int) -> dict:
    """Use the canonical resolver and the same build-only applicability for queries."""
    resolved = resolve_contract(copy.deepcopy(dict(baseline)), copy.deepcopy(dict(modes)),
                                mode_id, evidence_particle_count)
    if resolved["numerical"]["execution_mode"] != "build_only":
        raise ContractError("build_wehnelt_model currently implements only the selected build_only mode")
    return resolved
