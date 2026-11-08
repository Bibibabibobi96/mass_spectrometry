"""Public SIMION operations over complete domain objects."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from msplatform.execution import artifact_reader
from .compiler import CompiledSimionGeometry, compile_geometry as compile_simion_geometry
from .rf_compiler import compile_independent_multipoles

if TYPE_CHECKING:
    from msplatform.execution.artifact_reader import OpenedArtifact
    from msplatform.execution.context import ExecutionContext


def build_geometry(compiled: CompiledSimionGeometry, *, context: ExecutionContext) -> OpenedArtifact:
    """Materialize actual unsolved geometry through the one public execution owner.

    Engineering limits and retention are explicit in context.stage_policy_path.
    Native reopen/relocation qualifications remain separate recorded facts.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.geometry_execution import execute_geometry
    from msplatform.backends.simion.native_plans import plan_geometry_build
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.execution.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(compiled, CompiledSimionGeometry):
        raise ContractError("build_geometry requires compiled SIMION geometry")
    if compiled.frontend_geometry.get("role") == "simion_independent_rf_geometry":
        raise ContractError("independent RF native build remains in the project workflow; this SDK operation is pure compile only")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("build_geometry requires an explicit available SIMION executable")
    stage, authority = read_stage_policy(context, "build_geometry", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime
                and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION geometry runtime only accepts explicit boolean simion_allow_asynchronous_io")
    snapshot = CompiledSimionGeometry(**asdict(compiled))
    seed = file_record(structural_seed_path(4 + int(
        "entrance_refinement" in snapshot.frontend_geometry["numerical_domains"])), "required_evidence")
    # Only derive path-independent action names/relative file lengths here.
    # The owner alone creates the actual run and its existing ASCII projection.
    planning_root = context.execution_root / "geometry-plan"
    plan = plan_geometry_build(snapshot, run_directory=planning_root, seed_record=seed,
        native_path_resource=planning_root / "inputs/native_sources/native_run_path.lua")
    ids = tuple(row["operation_id"] for row in plan.operations)
    source = file_record(Path(execute_geometry.__code__.co_filename).resolve(), "required_evidence")
    result = run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="geometry_only", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__simion__geometry-" + uuid4().hex[:12],
        payload=dict(action="build_geometry", compiled_geometry=asdict(snapshot), stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority], retention=stage["artifact_retention"],
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_geometry, compiled=snapshot, seed_record=seed, limits=stage["limits"],
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=source,
        expected_relative_paths=[str(Path(path).relative_to(planning_root)) for path in plan.declared_outputs],
        use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "geometry"}, expected_kind="geometry_artifact")


def compile_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile native geometry specifications only; no source, writes, solve or Fly."""
    if not isinstance(assembly, Assembly):
        raise ContractError("SIMION geometry compilation requires an explicitly assembled design")
    plan = assembly.composition_plan
    selected = plan["scope"]["instance_ids"]
    if selected and all(plan["components"][name]["project_id"] == "rf_multipole_ion_optics" for name in selected):
        return compile_independent_multipoles(
            dict(composition_plan=plan, components_resolved=assembly.components_resolved),
            numerics=copy.deepcopy(dict(numerics)),
        )
    compiled = compile_simion_geometry(
        {"composition_plan": copy.deepcopy(dict(assembly.composition_plan)),
         "components_resolved": {name: copy.deepcopy(assembly.components_resolved[name]) for name in selected}},
        numerics=copy.deepcopy(dict(numerics)),
    )
    return replace(compiled, components_resolved=assembly.components_resolved)
