"""Explicit axisymmetric empty-enclosure High Mach gas-flow operation."""

from __future__ import annotations
import json
import base64
import hashlib
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from importlib.resources import files
from msplatform.components.dual_cone_tandem_quadrupole.geometry import (
    validate_baseline,
    resolve_geometry,
    serialized,
)
from msplatform.components.dual_cone_tandem_quadrupole.gas_field_validation import (
    _load_json,
    SCIENCE_ROLE,
    NUMERICS_ROLE,
    validate_gas_field,
)
from msplatform.components.dual_cone_tandem_quadrupole.gas_environment import (
    project_dual_cone_flow_science, resolve_dual_cone_conditions,
)
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.stage_policy import read_stage_policy
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.contracts.particle_physics import REFERENCE_DATASET_SHA256
from msplatform.results.artifacts import OpenedArtifact
from msplatform.results.gas_field import read_gas_field, read_gas_model
from .native_execution import (
    declare_runtime_files,
    freeze_native_sources,
    matlab_text,
    require_launcher_completion,
)

PROJECT = "dual_cone_tandem_quadrupole"
RESOURCES = ("build_and_solve_axisymmetric_gas_flow.m", "run_axisymmetric_gas_flow.m", "comsolstartup.m")


def resolve_gas_flow_request(
    baseline_path: Path, geometry_path: Path, science_path: Path, numerics_path: Path, environment_path: Path
) -> dict[str, Any]:
    """Bind explicit contracts; preserve the original exact geometry freshness check."""
    data_root = files("msplatform").joinpath("physics/data")
    paths = dict(baseline=baseline_path, geometry=geometry_path, science=science_path, numerics=numerics_path,
                 environment=environment_path, species_data=Path(str(data_root.joinpath("nitrogen.json"))),
                 constants_data=Path(str(data_root.joinpath("reference.json"))),
                 transport_data=Path(str(data_root.joinpath("nitrogen_transport_300k.json"))))
    if any(not Path(path).is_absolute() for path in paths.values()):
        raise ValueError("Gas-flow inputs require explicit absolute paths")
    snapshots = {name: Path(paths[name]).read_bytes() for name in ("baseline", "environment")}
    records = {name: file_record(Path(path), "required_evidence") for name, path in paths.items() if name not in snapshots}
    for name, data in snapshots.items():
        records[name] = dict(path=str(Path(paths[name]).resolve()), exists=True, bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest().upper(), retention_role="required_evidence")
    baseline = validate_baseline(json.loads(snapshots["baseline"].decode("utf-8-sig")))
    expected = serialized(resolve_geometry(baseline))
    if Path(geometry_path).read_text(encoding="utf-8-sig") != expected:
        raise ValueError("Gas-flow resolved geometry is stale")
    science = _load_json(Path(science_path), SCIENCE_ROLE)
    if science["schema_version"] != 2:
        raise ValueError("current gas-flow execution requires model-only science schema 2")
    environment = json.loads(snapshots["environment"].decode("utf-8-sig"))
    geometry = json.loads(Path(geometry_path).read_text(encoding="utf-8-sig"))
    conditions = resolve_dual_cone_conditions(environment, geometry)
    if records["species_data"]["sha256"].lower() != conditions["species_data"]["dataset_sha256"]:
        raise ValueError("nitrogen dataset differs from the resolved environment")
    if records["constants_data"]["sha256"].upper() != REFERENCE_DATASET_SHA256:
        raise ValueError("reference constants dataset differs from the imported authority")
    if records["transport_data"]["sha256"].lower() != conditions["transport_data"]["dataset_sha256"]:
        raise ValueError("nitrogen transport dataset differs from the imported authority")
    projected_science = project_dual_cone_flow_science(science, conditions)
    numerics = _load_json(Path(numerics_path), NUMERICS_ROLE)
    if science["model_id"] != numerics["model_id"] or science["physics"]["comsol_interface"] != "HighMachNumberFlow":
        raise ValueError("Gas-flow model or HighMachNumberFlow interface differs")
    names = numerics["artifact_names"]
    if (
        set(names) != {"model", "field_csv", "field_metadata"}
        or any(
            not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."} for name in names.values()
        )
        or len(set(names.values())) != 3
    ):
        raise ValueError("Gas-flow artifact names must be distinct filenames")
    for name, record in records.items():
        if name not in snapshots:
            verify_record("gas-flow " + name, record)
    return dict(
        project_id=PROJECT,
        model_id=science["model_id"],
        claim_scope=science["claim_scope"],
        inputs=records,
        artifact_names=names,
        projected_science=projected_science,
        author_snapshots={name: base64.b64encode(data).decode("ascii") for name, data in snapshots.items()},
    )


def solve_axisymmetric_gas_flow(
    baseline_path: Path,
    geometry_path: Path,
    science_path: Path,
    numerics_path: Path,
    environment_path: Path,
    *,
    context: ExecutionContext,
    resume: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> OpenedArtifact:
    """Build/solve/export, or explicitly reexport a matching published solved model.

    This gas-only prototype neither computes electric fields nor propagates ions.
    Resume requires exact manifest/model/writer-completion records, including failed-export producers;
    it does not invent a missing solver checkpoint.
    """
    request = resolve_gas_flow_request(baseline_path, geometry_path, science_path, numerics_path, environment_path)
    for name in ("comsol_launcher", "matlab_root"):
        path = context.tools.get(name)
        if path is None or not (path.is_dir() if name == "matlab_root" else path.is_file()):
            raise ValueError("Gas flow requires explicit available tool: " + name)
    parent = read_gas_model(resume, request["inputs"]) if resume is not None else None
    stage, authority = read_stage_policy(context, "solve_gas_flow", required_roles=("solver_native_binary",))
    if stage.get("runtime", {}):
        raise ValueError("Gas flow has no additional runtime overrides")
    result = run_managed_stage(
        context,
        descriptor=dict(project=PROJECT, mode="axisymmetric_gas_flow_screening", software=["COMSOL", "MATLAB"]),
        run_id=run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__comsol__gas-flow-" + uuid4().hex[:12],
        payload=dict(
            action="solve_gas_flow", request=request, resume=None if parent is None else parent, stage_policy=stage
        ),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority],
        source_references=(
            ()
            if parent is None
            else [dict(manifest_record=parent["manifest"], protected_paths=[parent["model"]["path"]])]
        ),
        retention=stage["artifact_retention"],
        expected_operation_ids=("solve_gas_flow",),
        operation_dependencies={},
        action=partial(_execute, request=request, limits=stage["limits"], parent=parent),
        action_record=file_record(Path(__file__).resolve(), "required_evidence"),
        use_short_execution_path=True,
        completion_api=no_particle_batch_completion_api,
    )
    return read_gas_field({"manifest": result["manifest"], "product_id": "gas_field"}).artifact


def _execute(session, *, request, limits, parent):
    launcher, sources = freeze_native_sources(session, RESOURCES)
    inputs = {}
    for name, original in request["inputs"].items():
        target = session.declare_file(session.input_dir / (name + ".json"), "required_evidence")
        if name in request["author_snapshots"]:
            data = base64.b64decode(request["author_snapshots"][name], validate=True)
            if len(data) != original["bytes"] or hashlib.sha256(data).hexdigest().upper() != original["sha256"].upper():
                raise ValueError("gas-flow captured author differs from its identity: " + name)
            with target.open("xb") as stream:
                stream.write(data)
        else:
            verify_record("gas-flow authority " + name, original)
            freeze_file(Path(original["path"]), target)
        verify_record("frozen gas-flow authority " + name, dict(original, path=str(target)))
        inputs[name] = file_record(target, "required_evidence")
        session.add_input(name, inputs[name])
    science_author = inputs["science"]
    projected = session.declare_file(session.input_dir / "science_resolved.json", "required_evidence")
    projected.write_text(json.dumps(request["projected_science"], ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    inputs["science_author"] = science_author
    inputs["science"] = file_record(projected, "required_evidence")
    session.add_input("science_resolved", inputs["science"])
    native = session.run_dir / "comsol"
    native.mkdir()
    model = native / request["artifact_names"]["model"]
    if parent is not None:
        model = Path(parent["model"]["path"])
        session.add_input("resume_model", parent["model"])
        session.add_input("resume_manifest", parent["manifest"])
        session.add_input("resume_completion", parent["completion"])
    else:
        session.declare_file(model, "solver_native_binary")
    csv_path = session.declare_file(native / request["artifact_names"]["field_csv"], "required_evidence")
    metadata_path = session.declare_file(native / request["artifact_names"]["field_metadata"], "required_evidence")
    report = session.declare_file(native / "comsol_run_report.txt", "required_evidence")
    bootstrap = session.declare_file(session.log_dir / "gas_flow.bootstrap.log", "required_evidence")
    completion = session.declare_file(session.log_dir / "gas_flow.launcher.json", "required_evidence")
    task = session.declare_file(session.input_dir / "gas_flow.m", "required_evidence")
    args = [Path(inputs[name]["path"]) for name in ("science", "numerics", "geometry")]
    args += [native, "" if parent is None else model]
    matlab = launcher.parent.parent / "matlab"
    task.write_text(
        "addpath("
        + matlab_text(matlab)
        + ");\nrun_axisymmetric_gas_flow("
        + ",".join(matlab_text(value) for value in args)
        + ");\n",
        encoding="utf-8",
        newline="\n",
    )
    host = json.dumps(
        {
            name: str(getattr(session.context, name))
            for name in ("workspace", "python_executable", "host_state_path", "policy_path")
        }
    )
    runtime = session.run_dir / "comsol_runtime"
    runtime.mkdir()
    argv = [
        "-NoProfile",
        "-File",
        str(launcher),
        "-HostContextJson",
        host,
        "-WorkingDirectory",
        str(session.run_dir),
        "-ComsolLauncherPath",
        str(session.context.tools["comsol_launcher"]),
        "-MatlabRootPath",
        str(session.context.tools["matlab_root"]),
        "-TaskScript",
        str(task),
        "-ReportPath",
        str(bootstrap),
        "-StartupAttempts",
        "1",
        "-RunId",
        session.run_id,
        "-RunDir",
        str(runtime),
        "-CompletionPath",
        str(completion),
    ]
    guards = [*sources, *inputs.values(), file_record(task, "required_evidence")]
    if parent is not None:
        guards.append(parent["model"])
    try:
        primary = None
        try:
            session.run_process(
                "solve_gas_flow",
                executable=session.context.powershell_executable,
                arguments=argv,
                role="COMSOL",
                stage="solver",
                limits=limits,
                immutable_input_records=guards,
            )
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                declare_runtime_files(session, runtime, bootstrap=bootstrap)
            except BaseException as secondary:
                if primary is None:
                    raise
                primary.add_note(f"COMSOL runtime diagnostic preservation failed: {secondary!r}")
        for record in guards:
            verify_record("gas-flow immutable input", record)
        require_launcher_completion(completion, session.run_id)
        if "STATUS=PASS" not in bootstrap.read_text(encoding="utf-8-sig") or "STATUS=PASS" not in report.read_text(
            encoding="utf-8-sig"
        ):
            raise ValueError("Gas-flow task or launcher did not complete")
        validation = validate_gas_field(
            csv_path,
            metadata_path,
            Path(inputs["science"]["path"]),
            Path(inputs["numerics"]["path"]),
            Path(inputs["geometry"]["path"]),
        )
        data = dict(
            inputs,
            field_csv=file_record(csv_path, "required_evidence"),
            field_metadata=file_record(metadata_path, "required_evidence"),
        )
        metadata = dict(
            backend="comsol",
            model_id=request["model_id"],
            claim_scope=request["claim_scope"],
            field_type="axisymmetric_gas",
            source_status="not_requested",
            scientific_qualification="not_granted",
            validation=validation,
            resumed=parent is not None,
        )
        outputs = [csv_path, metadata_path, report] + ([] if parent is not None else [model])
        return dict(
            status="success",
            summary=metadata,
            output_paths=list(map(str, outputs)),
            required_output_paths=list(map(str, outputs)),
            retention_preserve_paths=[],
            manifest_extra_fields=dict(
                products=dict(
                    gas_field=dict(schema_version=1, kind="gas_field", status="complete", metadata=metadata, data=data)
                )
            ),
        )
    except BaseException as failure:
        try:
            if parent is None and model.is_file():
                failure.failure_output_paths = [model]
        except BaseException as secondary:
            failure.add_note(f"Gas model recovery identity preservation failed: {secondary!r}")
        raise


def compiled_gas_flow_paths(path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Consume the five actually frozen scientific members of a compiled profile."""
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("role") != "compiled_execution_inputs" or document.get("project_id") != PROJECT:
        raise ValueError("Compiled gas-flow input identity differs")
    root = Path(document["root"]).resolve(strict=True)
    paths = []
    for name in ("geometry_baseline", "resolved_geometry", "gas_flow_science", "comsol_solver_numerics", "gas_environment"):
        members = [member for member in document["files"] if member["name"] == name]
        if len(members) != 1:
            raise ValueError("Compiled gas-flow input is missing or ambiguous: " + name)
        member = members[0]
        target = (root / member["relative_path"]).resolve(strict=True)
        if not target.is_relative_to(root):
            raise ValueError("Compiled gas-flow input escapes its frozen root")
        verify_record(name, dict(path=str(target), exists=True, bytes=member["bytes"], sha256=member["sha256"]))
        paths.append(target)
    return tuple(paths)


def main() -> int:
    """Run from an ordinary installation with explicit science and deployment."""
    import argparse
    from msplatform.execution.context import load_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled-inputs", type=Path)
    for name in ("baseline", "geometry", "science", "numerics", "environment"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--engineering-profile", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume-reference", type=Path)
    args = parser.parse_args()
    manual = (args.baseline, args.geometry, args.science, args.numerics, args.environment)
    if args.compiled_inputs:
        if any(value is not None for value in manual):
            parser.error("compiled inputs cannot be combined with separate scientific paths")
        paths = compiled_gas_flow_paths(args.compiled_inputs.absolute())
    else:
        if any(value is None for value in manual):
            parser.error("provide compiled inputs or all five explicit scientific paths")
        paths = tuple(value.absolute() for value in manual)
    context = load_environment(
        args.deployment.absolute(), workspace=args.workspace.absolute(), profile=args.engineering_profile
    )
    resume = (
        None if args.resume_reference is None else json.loads(args.resume_reference.read_text(encoding="utf-8-sig"))
    )
    product = solve_axisymmetric_gas_flow(*paths, context=context, resume=resume, run_id=args.run_id)
    print(json.dumps(product.reference))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
