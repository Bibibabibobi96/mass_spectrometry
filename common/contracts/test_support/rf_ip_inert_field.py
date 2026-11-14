"""Author-side inert RF-IP field fixture; never a native field qualification."""

import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch


def prepare_inert_field(root, model, compiled):
    """Publish the existing test field through the real owner and reader."""
    from common.contracts.test_simion_rf_prepared_model import (
        assets_at,
        clock_reference,
    )
    from common.contracts.test_simion_rf_fields import InertFieldSession, execute
    from msplatform.backends.simion import field_closure
    from msplatform.backends.simion.rf_field_execution import (
        _domain_labels,
        plan_rf_fields,
    )
    from msplatform.execution import owner, capacity_admission
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    from msplatform.execution.terminal_publication import publish_terminal_state
    from msplatform.io.manifest_records import file_record
    from msplatform.results.artifacts import open_artifact

    source_root = root / "producer"
    assets = assets_at(source_root, compiled)
    clock = clock_reference()
    records = dict(
        clock_authority=clock["contract"], instrument_epoch=clock["authority"]
    )
    model_path = source_root / "model.json"
    model_path.write_text(json.dumps(model.document), encoding="utf-8")
    records["compiled_model"] = file_record(model_path, "required_evidence")
    bindings = {}
    for name, row in assets.items():
        bindings[name] = {}
        for label, record in (
            ("raw_geometry", row["raw_record"]),
            ("fractional_surface", row["surface_records"][0]),
            ("surface_witnesses", row["witness_record"]),
        ):
            key = name + "_" + label
            records[key] = record
            bindings[name][label] = key
    manifest = dict(
        schema_version=2,
        role="simulation_run_manifest",
        run_id="inert-joint-model",
        project="software_fixture",
        mode="inert_joint_model",
        status="success",
        inputs={},
        outputs=list(records.values()),
        products=dict(
            model=dict(
                schema_version=1,
                kind="prepared_model",
                status="complete",
                data=records,
                metadata=dict(
                    backend="simion",
                    drive_configured=True,
                    geometry_materialized=True,
                    field_status="not_solved",
                    source_status="not_requested",
                    native_assets=bindings,
                ),
            )
        ),
    )
    publish_terminal_state(source_root, {"status": "success"}, manifest)
    source = field_closure.load_field_model(
        dict(
            manifest=file_record(source_root / "run_manifest.json"), product_id="model"
        )
    )
    graph = plan_rf_fields(model, numerics={"refine_policy": "vendor_default"})
    fields = InertFieldSession(root / "inert_fields", source_root, graph)
    fields.labels = {
        "parent": _domain_labels(
            model.document["geometry"]["frontend_geometry"], "parent"
        )
    }
    with patch(
        "msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner",
        return_value=dict(run_directory=str(source_root)),
    ):
        result = execute(fields, source, {"refine_policy": "vendor_default"})
    product = result["manifest_extra_fields"]["products"]["fields"]["metadata"]
    assert product["field_representation"] == "producer_owned_rf_ip_fractional_family"
    field_product = result["manifest_extra_fields"]["products"]["fields"]
    policy = root / "capacity.json"
    policy.write_text(
        json.dumps(
            dict(
                capacity_admission._capacity_policy(), target_gib=1, minimum_free_gib=0
            )
        )
    )
    budget = root / "budget.json"
    budget.write_text('{"bytes":16777216}')
    retention = dict(
        policy_version=1,
        **{"class": "solver_review"},
        reason="Inert joint tracking owner, not native science",
    )
    stage = root / "stage.json"
    stage.write_text(
        json.dumps(
            dict(
                schema_version=1,
                role="execution_stage_policy",
                stages=dict(
                    track=dict(
                        limits=dict(
                            wall_clock_seconds=120,
                            transient_run_directory_bytes=16777216,
                            process_tree_working_set_bytes=536870912,
                            minimum_system_available_memory_bytes=1073741824,
                            compact_final_retained_bytes=16777216,
                            automatic_retry_count=0,
                        ),
                        artifact_retention=retention,
                    )
                ),
            )
        )
    )
    context = ExecutionContext(
        workspace=root / "study",
        python_executable=Path(sys.executable),
        powershell_executable=Path(shutil.which("pwsh")),
        tools=dict(simion=Path(sys.executable)),
        host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
        policy_path=resource_path("host_resource_policy.json"),
        capacity_policy_path=policy,
        stage_policy_path=stage,
    )

    def source_action(session):
        result_records = {}
        for name, record in field_product["data"].items():
            relative = (
                Path("clock") / Path(record["path"]).name
                if name in {"clock_authority", "instrument_epoch"}
                else Path(record["path"]).relative_to(fields.run_dir)
            )
            target = session.declare_file(
                session.input_dir / relative, record["retention_role"]
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(record["path"]).read_bytes())
            result_records[name] = file_record(
                session.canonical_path(target), record["retention_role"]
            )
            session.add_input(name, result_records[name])
        paths = [Path(r["path"]) for r in result_records.values()]
        return dict(
            status="success",
            summary=dict(fixture="INERT_ONLY"),
            output_paths=paths,
            required_output_paths=paths,
            retention_preserve_paths=[],
            manifest_extra_fields=dict(
                products=dict(fields=dict(field_product, data=result_records))
            ),
        )

    published = owner.run_managed_stage(
        context,
        descriptor=dict(
            project="instrument_assembly", mode="inert_joint_fields", software=[]
        ),
        run_id="20261113_000001__test__python__inert-joint-fields",
        payload={},
        committed_new_bytes=16777216,
        commitment_inputs=[file_record(budget, "required_evidence")],
        retention=retention,
        expected_operation_ids=(),
        operation_dependencies={},
        action=source_action,
        action_record=file_record(Path(__file__), "required_evidence"),
    )
    reference = dict(manifest=published["manifest"], product_id="fields")
    artifact = open_artifact(reference, expected_kind="field_bundle")
    originals = {
        r["path"]: Path(r["path"]).read_bytes()
        for key, r in artifact.data_records.items()
        if "_family_" in key
    }
    return reference, originals, context


def make_installed_fixture(root):
    """Create one author-side field producer and explicit child inputs."""
    from common.contracts.test_joint_ip_model import JointIpModelTests
    from common.contracts.test_simion_rf_tracking import rf_tracking_case
    from msplatform.backends.simion.model import RF_IP_PHYSICS, compile_prepared_model
    from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import (
        HS1_SOURCE_FIXTURE,
    )

    case = JointIpModelTests(methodName="runTest")
    case.setUp()
    try:
        compiled = case.compiled
        model = compile_prepared_model(
            compiled,
            compiled.components_resolved,
            drive=case.drive,
            physics=RF_IP_PHYSICS,
        )
        _, _, packet, _, propagation, numerics = rf_tracking_case()
        frame = compiled.frontend_geometry["composition_plan"]["components"][
            "multipole"
        ]["local_frame_id"]
        for row in [*packet["rows"], *packet["mother"]["records"].values()]:
            row.update(
                source_component_id="multipole",
                target_component_id="multipole",
                frame_id=frame,
                clock_epoch_id=model.document["drive"]["clock"]["clock_epoch_id"],
            )
        packet["clock"] = {
            key: model.document["drive"]["clock"][key]
            for key in ("clock_epoch_id", "authority_sha256")
        }
        propagation["dynamics"]["collisions"] = "hs1"
        numerics["grouped"] = 0
        baseline = model.document["drive"]["ip_schedule"]["baseline"]
        vendor = root / "original.lua"
        vendor.write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        reference, _, context = prepare_inert_field(root, model, compiled)
        return dict(
            reference=reference,
            packet=packet,
            propagation=propagation,
            numerics=numerics,
            gas_mass=baseline["gas"]["mass_amu"],
            gas_temperature=baseline["gas"]["temperature_k"],
            gas_frame=baseline["clock"]["frame_id"],
            vendor_path=str(vendor),
            context=dict(
                workspace=str(context.workspace),
                powershell_executable=str(context.powershell_executable),
                capacity_policy_path=str(context.capacity_policy_path),
                stage_policy_path=str(context.stage_policy_path),
            ),
        )
    finally:
        case.doCleanups()
