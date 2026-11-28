"""Test-only registered producers for SFI scalar owner and installed checks.

All model and PA bytes here are inert software fixtures, not native qualification.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys


from contextlib import contextmanager
import tempfile


@contextmanager
def retained_owner_directory():
    """Retain failed or incompletely closed test runs for owner inspection."""
    from msplatform.io.manifest_records import require_completed_terminal_publication

    root = Path(tempfile.mkdtemp(prefix="sfi-scalar-owner-"))
    try:
        yield root
        configs = list(root.rglob("run_config.json"))
        if not configs:
            raise ValueError("fixture has no owner runs to verify")
        for config in configs:
            run = config.parent
            manifest = run / "run_manifest.json"
            completion = run / "results" / "execution_completion.json"
            require_completed_terminal_publication(manifest)
            if json.loads(manifest.read_text(encoding="utf-8-sig"))["status"] != "success":
                raise ValueError("fixture run is not successful")
            record = json.loads(completion.read_text(encoding="utf-8-sig"))
            if record.get("status") != "success" or record.get("exception") is not None or not isinstance(record.get("writer_completion"), dict):
                raise ValueError("fixture writer completion is not confirmed")
    except BaseException:
        print("RETAINED_SFI_OWNER_FIXTURE", root, flush=True)
        raise
    else:
        shutil.rmtree(root)

def make_context(root: Path):
    """Use the real owner and shared host admission for task-owned evidence."""
    from msplatform.execution import capacity_admission
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import file_record

    root.mkdir(parents=True, exist_ok=True)
    policy = root / "capacity.json"
    policy.write_text(
        json.dumps(dict(capacity_admission._capacity_policy(), target_gib=1, minimum_free_gib=0)), encoding="utf-8"
    )
    budget = root / "budget.json"
    budget.write_text('{"bytes":16777216}', encoding="utf-8")
    retention = {"policy_version": 1, "class": "solver_review", "reason": "Inert test fixture, not native science"}
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
        ),
        encoding="utf-8",
    )
    context = ExecutionContext(
        workspace=root / "workspace",
        python_executable=Path(sys.executable),
        powershell_executable=Path(shutil.which("pwsh")),
        tools={"simion": Path(sys.executable)},
        host_state_path=Path(os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]),
        policy_path=resource_path("host_resource_policy.json"),
        capacity_policy_path=policy,
        stage_policy_path=stage,
    )
    return context, file_record(budget, "required_evidence"), retention


def publish_fixture(context, budget, retention, *, name, kind, data, metadata, inputs=None, linked=None):
    """Publish selected test evidence through the existing managed owner."""
    from msplatform.execution.owner import run_managed_stage
    from msplatform.io.manifest_records import file_record

    linked = linked or {}
    author_inputs = inputs or {}
    source_refs = (
        [{"manifest_record": linked["field_solution_manifest"]}] if "field_solution_manifest" in linked else []
    )
    payload = author_inputs.get("execution_request", {}).get("payload", {"action": "test_inert_fixture"})

    def action(session):
        records = {}
        for key, value in data.items():
            suffix = ".pa" if key in ("field_v", "field_valid") else ".mph"
            path = session.declare_file(
                session.result_dir / (key + suffix if isinstance(value, bytes) else key + ".json"),
                "solver_native_binary" if isinstance(value, bytes) else "required_evidence",
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode("utf-8"))
            records[key] = file_record(
                session.canonical_path(path),
                "solver_native_binary" if isinstance(value, bytes) else "required_evidence",
            )
        for key, record in linked.items():
            session.add_input(key, record)
            if key == "field_solution_manifest":
                records[key] = record
        paths = [Path(record["path"]) for key, record in records.items() if key not in linked]
        product_id = "solution" if kind == "field_solution" else "product"
        return dict(
            status="success",
            summary={"fixture": "inert_test_only"},
            output_paths=paths,
            required_output_paths=paths,
            retention_preserve_paths=[],
            manifest_extra_fields={
                "products": {
                    product_id: dict(schema_version=1, kind=kind, status="complete", metadata=metadata, data=records)
                }
            },
        )

    result = run_managed_stage(
        context,
        descriptor=dict(project="instrument_assembly", mode="test_fixture", software=[]),
        run_id="20261114_000000__test__python__sfi-" + name,
        payload=payload,
        committed_new_bytes=16777216,
        commitment_inputs=[budget],
        retention=retention,
        expected_operation_ids=(),
        operation_dependencies={},
        action=action,
        action_record=file_record(Path(__file__), "required_evidence"),
        source_references=source_refs,
    )
    return {"manifest": result["manifest"], "product_id": "solution" if kind == "field_solution" else "product"}


def registered_scalar_fixture(context, budget, retention):
    """Reuse the canonical admission fixture but give each producer a real owner."""
    from tests.contracts.test_sfi_scalar_binding import SfiScalarAdmissionTests

    class Registered(SfiScalarAdmissionTests):
        def publish(self, name, kind, data, metadata, inputs=None, linked=None):
            return publish_fixture(
                context,
                budget,
                retention,
                name=name.replace("_", "-"),
                kind=kind,
                data=data,
                metadata=metadata,
                inputs=inputs,
                linked=linked,
            )

    case = Registered(methodName="runTest")
    case.setUp()
    return case


def publish_refinement_samples(case, label):
    """Create distinct registered 7³ software-only samples for each basis."""
    from msplatform.backends.simion.standalone_pa_composition import PaHeader
    from msplatform.results.artifacts import open_artifact

    result = {}
    for name, reference in case.sample_refs.items():
        item = open_artifact(reference, expected_kind="scalar_field_samples")
        data = {}
        for key in item.data_records:
            if key == "field_solution_manifest":
                continue
            path = item.data_path(key)
            data[key] = path.read_bytes() if key in ("field_v", "field_valid") else json.loads(path.read_text(encoding="utf-8"))
        data["grid"].update(origin_mm=[-2., -2., -2.], pitch_mm=[1., 1., 1.],
                            dimensions=[7, 7, 7], point_count=343, maximum_mm=[4., 4., 4.])
        data["report"].update(data["grid"])
        data["report"].update(fem_valid=343, invalid_count=0)
        pa = PaHeader(-2, 1, 10000., 7, 7, 7, 1 << 28, 1., 1., 1.).pack() + bytes(343 * 8)
        data["field_v"] = pa
        data["field_valid"] = pa
        manifest = json.loads(item.manifest_location.read_text(encoding="utf-8"))
        result[name] = case.publish("window-" + label + "-" + name, "scalar_field_samples", data, item.metadata,
            linked={"field_solution_manifest": item.data_records["field_solution_manifest"],
                    "field_solution_model": manifest["inputs"]["field_solution_model"]})
    return result


def inert_native_leaf(actual_process, observed):
    """Replace only the commercial executable with a controlled Python child."""

    def run(context, **options):
        if options["role"] != "SIMION":
            return actual_process(context, **options)
        working = Path(options["working_directory"])
        args = options["arguments"]
        observed.append(copy.deepcopy(options))
        if "fly" not in args:
            mode = args[-2]
            iob = working / "simion/tracking/instrument.iob"
            marker = "SINGLE_REFLECTION_IOB=PASS" if mode == "build" else "SINGLE_REFLECTION_IOB_REOPEN=PASS"
            code = "from pathlib import Path\n"
            if mode == "build":
                code += "Path(" + repr(str(iob)) + ').write_bytes(b"INERT_IOB")\n'
            code += "print(" + repr(marker) + ")"
        else:
            # Read the 100-row fixture inside the inert child; embedding all
            # trace rows in -c exceeds Windows' command-line length limit.
            source_path = working / "inputs/canonical_source_states.json"
            import runpy
            terminal_helpers = runpy.run_path(str(Path(__file__).with_name("terminal_evidence_fixture.py")))
            token = terminal_helpers["native_run_from_program"](working / "simion/tracking/instrument.lua")
            code = terminal_helpers["inert_wire_source"]() + "native_run=" + repr(token) + "\n" + """import json,sys
source=json.load(open(sys.argv[1],encoding='utf-8'))
for index,row in enumerate(source,1):
    pid,t=row['particle_id'],row['instrument_time_us']
    state=' '.join(f'{axis}_mm={row["position_"+axis+"_mm"]:.17g}' for axis in 'xyz')
    state+=' '+' '.join(f'v{axis}_mm_per_us={row["velocity_"+axis+"_m_s"]/1000:.17g}' for axis in 'xyz')
    xyz=' '.join(f'{axis}={row["position_"+axis+"_mm"]:.17g}' for axis in 'xyz')
    print(f'TRACE: source_release ion={index} particle_id={pid} instrument_time_us={t:.17g} {state}')
    print(f'TRACE: handoff_terminal_raw ion={index} instance=3 instrument_time_us={t+1:.17g} {state}')
    print(f'TRACE: non_detector_splat ion={index} instance=3 t={t+1:.17g} {xyz} zmax=0')
    print("\\n".join(terminal_wire_lines(row,index,native_run,t+1,3)))
print(f'status,Fly completed. {len(source)} splats')
"""
        return actual_process(
            context,
            **dict(
                options,
                executable=Path(sys.executable),
                arguments=["-I", "-c", code] + ([str(source_path)] if "fly" in args else []),
                role="GATE",
                stage="inert_sfi_tracking",
            ),
        )

    return run


def publish_sfi_fields(context, budget, retention, artifact):
    """Publish an existing complete inert SFI field protocol under one owner."""
    from msplatform.execution.owner import run_managed_stage
    from msplatform.io.manifest_records import file_record

    def action(session):
        records = {}
        for key, record in artifact.data_records.items():
            source = Path(record["path"])
            target = session.declare_file(
                session.result_dir / "fields" / source.name, record.get("retention_role", "required_evidence")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            records[key] = file_record(
                session.canonical_path(target), record.get("retention_role", "required_evidence")
            )
        paths = [Path(record["path"]) for record in records.values()]
        return dict(
            status="success",
            summary={"fixture": "inert_test_only"},
            output_paths=paths,
            required_output_paths=paths,
            retention_preserve_paths=[],
            manifest_extra_fields={
                "products": {
                    "fields": dict(
                        schema_version=1,
                        kind="field_bundle",
                        status="complete",
                        metadata=artifact.metadata,
                        data=records,
                    )
                }
            },
        )

    result = run_managed_stage(
        context,
        descriptor=dict(project="instrument_assembly", mode="test_fixture", software=[]),
        run_id="20261114_000001__test__python__sfi-inert-fields",
        payload={"action": "inert_sfi_fields"},
        committed_new_bytes=16777216,
        commitment_inputs=[budget],
        retention=retention,
        expected_operation_ids=(),
        operation_dependencies={},
        action=action,
        action_record=file_record(Path(__file__), "required_evidence"),
    )
    return {"manifest": result["manifest"], "product_id": "fields"}


def make_fixture(root: Path, *, refinement_windows: bool = False):
    """Construct current native-preflight, fields and registered scalar producers."""
    from importlib.resources import files
    from tests.contracts import test_simion_tracking_execution as tracking_test
    from msplatform.execution.owner import run_managed_stage
    from msplatform.io.manifest_records import file_record
    from msplatform.recipes import load_recipe
    from msplatform.workflows.native_tracing import preflight_native

    root = Path(root).resolve()
    context, budget, retention = make_context(root)
    if type(refinement_windows) is not bool:
        raise ValueError("refinement_windows must be a boolean")
    scalar = registered_scalar_fixture(context, budget, retention)
    try:
        author = Path(str(files("msplatform.examples").joinpath("rf_split_oatof_native_small_v1.toml")))
        recipe = load_recipe(author)

        def preflight_action(session):
            report = preflight_native(recipe.to_dict())
            output = session.declare_file(session.input_dir / "native_preflight.json", "required_evidence")
            output.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
            return dict(
                status="success",
                summary={"fixture": "inert_test_only", "native_verified": report["native_verified"]},
                output_paths=[output],
                required_output_paths=[output],
                retention_preserve_paths=[],
                manifest_extra_fields={},
            )

        result = run_managed_stage(
            context,
            descriptor=dict(project="instrument_assembly", mode="test_fixture", software=[]),
            run_id="20261114_000002__test__python__sfi-native-preflight",
            payload={"action": "native_preflight"},
            committed_new_bytes=16777216,
            commitment_inputs=[budget],
            retention=retention,
            expected_operation_ids=(),
            operation_dependencies={},
            action=preflight_action,
            action_record=file_record(Path(__file__), "required_evidence"),
        )
        tracking = tracking_test.TrackingExecutionPlanTests(methodName="runTest")
        tracking.setUp()
        try:
            field_root = root / "field-author"
            field_root.mkdir()
            artifact, _, _ = tracking_test.tracking_action_fixture(tracking, field_root)
            field_ref = publish_sfi_fields(context, budget, retention, artifact)
        finally:
            tracking.doCleanups()
        from msplatform.results.artifacts import open_artifact
        carrier = open_artifact(scalar.sample_refs["carrier"], expected_kind="scalar_field_samples")
        selection = dict(geometry_artifact=scalar.geometry_ref, samples=scalar.sample_refs)
        window_carrier = None
        if refinement_windows:
            first = publish_refinement_samples(scalar, "a")
            second = publish_refinement_samples(scalar, "b")
            selection["refinement_windows"] = [
                dict(name="first", active_box_mm=[[0., .5]] * 3, samples=first),
                dict(name="second", active_box_mm=[[0., .5]] * 3, samples=second),
                dict(name="repeat_first", active_box_mm=[[0., .5]] * 3, samples=copy.deepcopy(first)),
            ]
            window_carrier = str(open_artifact(first["carrier"], expected_kind="scalar_field_samples").data_path("field_v"))
        return dict(
            tamper_scalar_pa=str(carrier.data_path("field_v")),
            preparation_manifest=result["manifest"],
            fields=field_ref,
            scalar_field_basis=selection,
            tamper_scalar_window_pa=window_carrier,
            expected_particle_ids=list(range(1, 101)),
            species_id="inert_fixture_species",
            context=dict(
                workspace=str(context.workspace),
                powershell_executable=str(context.powershell_executable),
                capacity_policy_path=str(context.capacity_policy_path),
                stage_policy_path=str(context.stage_policy_path),
            ),
        )
    finally:
        scalar.doCleanups()
