"""Fresh dual-cone gas-assisted transport through the existing managed owner.

Independent stage publication and saved-field reuse remain separate P4 work.
"""

from __future__ import annotations

import copy
from datetime import datetime
from functools import partial
import json
from pathlib import Path
from uuid import uuid4

from msplatform.backends.simion.dual_cone_transport_execution import (
    execute_transport,
    plan_transport_operations,
)
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.results.gas_field import read_gas_field


def run_gas_assisted_transport(
    *,
    resolved_path,
    numerics_path,
    science_path,
    interface_path,
    gas_science_path,
    source_spec_path,
    gas_field_reference,
    collision_sds_dir,
    context,
    placement=None,
    source_to_device=None,
):
    """Explicit fresh build/Refine/Fly; never infer an input or reopen a cache."""
    from msplatform.backends.simion import native_completion

    request = dict(
        resolved_path=Path(resolved_path),
        numerics_path=Path(numerics_path),
        science_path=Path(science_path),
        interface_path=Path(interface_path),
        gas_science_path=Path(gas_science_path),
        source_spec_path=Path(source_spec_path),
        gas_field_reference=copy.deepcopy(gas_field_reference),
        collision_sds_dir=Path(collision_sds_dir),
    )
    values = {
        name: json.loads(request[name + "_path"].read_text(encoding="utf-8-sig"))
        for name in ("resolved", "numerics", "science", "source_spec")
    }
    graph = plan_transport_operations(**values, placement=placement, source_to_device=source_to_device)
    request.update({key: graph[key] for key in ("placement", "source_to_device") if key in graph})
    gas = read_gas_field(request["gas_field_reference"])
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ValueError("fresh dual-cone transport requires an explicit available SIMION executable")
    stage, policy = read_stage_policy(context, "dual_cone_transport")
    runtime = stage.get("runtime", {})
    if set(runtime) - {"simion_allow_asynchronous_io"} or (
        "simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool
    ):
        raise ValueError("SIMION transport runtime only accepts explicit boolean simion_allow_asynchronous_io")
    # No ordinary run silently inherits the resource budget of gas-flow or RF.
    # The caller supplies this exact action's explicit engineering policy.
    result = run_managed_stage(
        context,
        descriptor=dict(
            project="dual_cone_tandem_quadrupole_ion_interface",
            mode="gas_field_driven_simion_transport",
            software=["SIMION"],
        ),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__dualcone-" + uuid4().hex[:12],
        payload=dict(
            action="dual_cone_transport",
            request={name: str(value) if isinstance(value, Path) else value for name, value in request.items()},
            stage_policy=stage,
        ),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy],
        retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(
            execute_transport,
            request=request,
            limits=stage["limits"],
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"),
        ),
        action_record=file_record(Path(execute_transport.__code__.co_filename).resolve(), "required_evidence"),
        source_references=[{"manifest_record": gas.reference["manifest"]}],
        use_short_execution_path=True,
        completion_api=lambda: native_completion,
    )
    return open_artifact(
        {"manifest": result["manifest"], "product_id": "trajectory"}, expected_kind="trajectory_result"
    )
