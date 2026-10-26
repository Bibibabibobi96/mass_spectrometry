"""Freeze cooled-field receipts and materialize scheduler-owned local flights."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import stat
from dataclasses import asdict
import shutil

from common.contracts.file_identity import file_sha256
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.simion.pa_family_cache import (
    advance_pa_family_cache_transaction, canonical_pa_family_cache_key,
    load_pa_family_cache_transaction, validate_pa_family_cache_generation,
)
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION, _resolve_standalone_dynamic_field_bank,
)
from integrations.workflows.local_frontend import runtime as shared


FIELD_ROLE = "rf_oatof_cooled_frontend_field_stage"
_FIELD_PUBLICATION_PIN_REASON = (
    "Retained canonical standalone cooled frontend fields for saved workbenches and explicit field-source consumers; "
    "rebuildable from frozen inputs."
)
KINDS = ("carrier_off", "rf_differential_unit", "entry_close_delta", "release_delta", "pulse_delta", "inner_auxiliary_unit", "hp_common_unit")


def field_cache_plan(run: Path, *, cache_root: Path | None = None) -> dict:
    """Bind the seven actual working points to the public transaction owner."""
    run = Path(run).resolve(strict=True)
    inputs = run / "inputs"
    front = shared._load(inputs / "frontend_contract.json")
    plan = shared._load(inputs / "cooled_field_plan.json")
    if plan["role"] != "rf_oatof_cooled_frontend_laplace_endpoints":
        raise ValueError("only the ordinary full-domain working fields use this cache")
    if tuple(point["kind"] for point in plan["working_points"]) != KINDS:
        raise ValueError("exact seven cooled working points required")
    repository = Path(__file__).resolve().parents[3]
    builders = {
        "operating_point": repository / "common/simion/build_dirichlet_patch_operating_pa.lua",
        "standalone_export": repository / "common/simion/export_detached_standalone_pa.lua",
    }
    native = shared._load(inputs / "native_discovery.json")
    identity = dict(
        geometry=dict(dimensions=front["dimensions"]), gem=file_sha256(inputs / "frontend.gem"),
        working_points=[dict(point, kind="rf_reference" if point["kind"] == "rf_differential_unit" else point["kind"],
                             refine_convergence_v=plan["refine_convergence_v"]) for point in plan["working_points"]],
        mesh=front["cell_mm_xyz"], grid_phase=front["instance_origin_mm"], surface="none",
        boundary_policy=plan["boundary_policy"], rf_reference_voltage_v=1.,
        simion_identity=dict(release="SIMION 2020", executable_bytes=native["bytes"],
                             executable_sha256=native["sha256"], file_version=native["file_version"]),
        builder_identity={name: file_sha256(path) for name, path in builders.items()},
    )
    key = canonical_pa_family_cache_key(identity)
    path = inputs / "cooled_field_cache_identity.json"
    shared._json_once(path, identity)
    root = cache_root if cache_root is not None else run.parents[3] / "common/simion/pa_family_cache"
    return dict(cache_root=str(root), cache_key=key, identity=identity,
                filenames=[point["output_basename"] for point in plan["working_points"]],
                verifier_path=str(Path(__file__).with_name("verify_cooled_fields.lua")))


def field_verification_spec(run: Path, directory: Path) -> Path:
    """Sample provider metal and real working voltages, without a basis model."""
    from integrations.runtime.frontend_field_plan import _bare_samples, sample_node
    from integrations.runtime.single_flight_electrode_contract import require_pa_plus_solution_model
    from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import contains_shape, shape_bounds

    run = Path(run)
    front = shared._load(run / "inputs/frontend_contract.json")
    plan = shared._load(run / "inputs/cooled_field_plan.json")
    _, samples = _bare_samples(front, require_pa_plus_solution_model(front["pa_plus_solution_model"]))
    conditioner = front["conditioner_contract"]
    pose = conditioner["native_to_mr"]
    # Provider CSG is only used to choose bounded audit nodes. It is never
    # redrawn or used as a second field/electrode authority.
    for electrode in conditioner["native_projection_fragment"]["electrodes"]:
        anchor = None
        for solid in electrode["solids"]:
            lower, upper = shape_bounds(solid)
            for fraction in (.5, .25, .75):
                point = [lo + fraction * (hi - lo) for lo, hi in zip(lower, upper)]
                gu, body = sample_node(point, pose["rotation"], pose["translation_mm"],
                                       front["instance_origin_mm"], front["cell_mm_xyz"], front["dimensions"])
                if contains_shape(solid, body) and not any(contains_shape(cut, body) for cut in electrode["cutouts"]):
                    anchor = gu
                    break
            if anchor is not None:
                break
        if anchor is None:
            raise ValueError(f"no represented metal audit node for conditioner electrode {electrode['name']}")
        samples.append(dict(label=electrode["name"], electrode_id=electrode["electrode_id"], gu=anchor))
    lines = ["cooled_working_field_verification_v1", "\t".join(map(str, ["grid", *[front["dimensions"]["n" + a] for a in "xyz"],
                       *[front["cell_mm_xyz"][a] for a in "xyz"]]))]
    for point in plan["working_points"]:
        lines.append("\t".join(["field", point["kind"], str(directory / point["output_basename"])]))
        for sample in samples:
            voltage = point["electrode_voltages_v"][str(sample["electrode_id"])]
            lines.append("\t".join(map(str, ["metal", point["kind"], sample["label"], *sample["gu"], format(voltage, ".17g")])))
    path = run / "inputs/cooled_field_verification.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def advance_field_cache(run: Path, plan: dict, verification_output: Path | None = None) -> dict:
    """Continue the original public transaction; never adopt it as a new owner."""
    run = Path(run).resolve(strict=True)
    transaction_path = Path(plan["cache_root"]) / ".transactions" / plan["cache_key"] / "transaction.json"
    transaction = load_pa_family_cache_transaction(plan["cache_root"], plan["cache_key"]) if transaction_path.exists() else None
    arguments = dict(published_pin_reason=transaction["published_pin_reason"] if transaction else _FIELD_PUBLICATION_PIN_REASON)
    if transaction is None:
        arguments.update(owner=str(run), producer_run_config=run / "run_config.json")
    elif transaction.get("producer"):
        producer_config = Path(transaction["producer"]["run_config_path"])
        producer = producer_config.parent.resolve(strict=True)
        if producer != run:
            manifest_path = producer / "run_manifest.json"
            require_completed_terminal_publication(manifest_path)
            manifest = shared._load(manifest_path)
            if manifest["status"] not in ("success", "failed"):
                raise ValueError("field transaction producer is not terminal")
            if _verified_small_record(manifest["run_config"]) != producer_config.resolve(strict=True):
                raise ValueError("field transaction producer config binding differs")
            identity_source = producer / "inputs/cooled_field_cache_identity.json"
            if not any(_record_path(row, strict=False) == identity_source for row in manifest.get("inputs",{}).values()):
                raise ValueError("field transaction producer identity is not manifest-bound")
            # Creation-time config SHA is an audit record, not an immutable
            # config claim: the owner's normal finalization updates this file.
            for name, source in (("manifest", manifest_path), ("run_config", producer_config),
                                 ("identity", producer / "inputs/cooled_field_cache_identity.json")):
                target = run / "inputs" / ("cooled_field_producer_" + name + ".json")
                if not target.exists():
                    shutil.copyfile(source, target)
                if target.read_bytes() != source.read_bytes():
                    raise ValueError("frozen original field producer evidence changed")
            if shared._load(producer / "inputs/cooled_field_cache_identity.json") != plan["identity"]:
                raise ValueError("original field producer scientific identity differs")
    if verification_output is not None:
        if transaction is None or transaction["status"] != "building" or not transaction["inventory_sha256"]:
            raise ValueError("field verification requires the public prepared inventory")
        arguments["verification_evidence"] = dict(
            schema_version=1, role="simion_pa_family_verification", status="pass",
            cache_key=plan["cache_key"], inventory_sha256=transaction["inventory_sha256"],
            solver_release="SIMION 2020", verifier_path=plan["verifier_path"],
            verifier_sha256=file_sha256(plan["verifier_path"]),
            verification_output_path=str(verification_output), verification_output_sha256=file_sha256(verification_output),
        )
    result = advance_pa_family_cache_transaction(plan["cache_root"], plan["identity"], plan["filenames"],
                                                recovery_policy="none", **arguments)
    return json.loads(json.dumps(asdict(result), default=str))


def _records(records: list[dict]) -> dict:
    """Recheck immutable field handles without rescanning large solved payloads."""
    if not isinstance(records, list) or len(records) != len(KINDS) or {r["kind"] for r in records} != set(KINDS):
        raise ValueError("exactly seven unique real-field records required")
    parents = set()
    for row in records:
        path = Path(row["path"]).resolve(strict=True)
        if path.suffix.lower() != ".pa" or not path.is_file() or row.get("read_only") is not True or path.stat().st_mode & stat.S_IWRITE or path.stat().st_size != row["bytes"] or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64:
            raise ValueError("solved ordinary PA identity/stat/read-only differs")
        parents.add(path.parent)
    if len(parents) != 1:
        raise ValueError("all seven working fields must share one immutable directory")
    return {r["kind"]: dict(r) for r in records}


def finalize_field_stage(run: Path, cache: dict, progress: dict) -> dict:
    """Bind the field bank to one already-published public generation."""
    run = shared._owner(run, "discovery")
    if progress["status"] != "published" or progress["action_required"] != "complete":
        raise ValueError("cooled fields require a published cache generation")
    directory = Path(progress["generation_directory"])
    manifest = validate_pa_family_cache_generation(directory, expected_cache_key=cache["cache_key"],
        expected_filenames=cache["filenames"], verify_payload=False)
    if manifest["identity"] != cache["identity"]:
        raise ValueError("published cooled field identity differs")
    indexed = {row["name"]: row for row in manifest["files"]}
    plan = shared._load(run/"inputs/cooled_field_plan.json")
    records = [dict(indexed[point["output_basename"]], path=str(directory / point["output_basename"]),
                    kind=point["kind"], read_only=True) for point in plan["working_points"]]
    by_kind = _records(records)
    if tuple(p["kind"] for p in plan["working_points"]) != KINDS:
        raise ValueError("built fields differ from frozen scientific field plan")
    for p in plan["working_points"]:
        if Path(by_kind[p["kind"]]["path"]).name != p["output_basename"]:
            raise ValueError("field basename differs from frozen endpoint")
    bank = dict(schema_version=STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION, role=STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
                runtime_representation=STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
                dynamic_roles=[dict(role="coarse_frontend", instance_index=1,
                    carrier_pa_basename=Path(by_kind["carrier_off"]["path"]).name,
                    rf_differential_pa_basenames=[Path(by_kind["rf_differential_unit"]["path"]).name],
                    rf_reference_voltage_v=1.,
                    pulse_delta_pa_basename=Path(by_kind["pulse_delta"]["path"]).name)])
    path = run/"inputs/cooled_field_bank.json"
    shared._json_once(path, bank)
    receipt = dict(schema_version=2, role=FIELD_ROLE, status="success", working_points=records,
                   field_bank_path=str(path), field_bank_record=file_record(path),
                   field_plan_record=file_record(run/"inputs/cooled_field_plan.json"),
                   geometry_record=file_record(run/"inputs/frontend.gem"),
                   cache_identity_record=file_record(run/"inputs/cooled_field_cache_identity.json"),
                   cache_key=cache["cache_key"], generation_directory=str(directory),
                   generation_sha256=manifest["generation_sha256"],
                   identity_validation="public_published_generation__runtime_stat_and_readonly_recheck")
    receipt_path = run/"inputs/cooled_frontend_field_stage_receipt.json"
    shared._json_once(receipt_path, receipt)
    return dict(receipt_path=str(receipt_path), receipt=receipt, working_points=records)


def _record_path(record: dict,workspace_root: Path | None = None, *, strict: bool = True) -> Path:
    path=Path(record["path"])
    if not path.is_absolute():
        if workspace_root is None:
            raise ValueError("relative file identity requires an explicit workspace root")
        path=Path(workspace_root).resolve(strict=True)/path
    return path.resolve(strict=strict)


def _verified_small_record(record: dict,workspace_root: Path | None = None) -> Path:
    path=_record_path(record,workspace_root)
    if path.stat().st_size != record["bytes"] or file_sha256(path) != record["sha256"]:
        raise ValueError("frozen small-file identity differs")
    return path


def _same_identity(left: dict,right: dict,workspace_root: Path | None = None) -> bool:
    return _record_path(left,workspace_root,strict=False)==_record_path(right,workspace_root,strict=False) and left.get("bytes")==right.get("bytes") and left.get("sha256")==right.get("sha256")


def fields(run: Path) -> dict:
    """Consume an explicit completed same-owner or sealed shared field receipt."""
    run=Path(run).resolve(strict=True)
    workspace=run.parents[4]
    request=shared._load(run/"inputs/cooled_experiment.json")
    source=request["field_source"]
    envelope=None
    if source:
        envelope=shared._load(_verified_small_record(source,workspace))
        if envelope.get("schema_version") != 1 or envelope.get("role") != "rf_oatof_cooled_frontend_field_source":
            raise ValueError("sealed field-source envelope required")
    path = _verified_small_record(envelope["field_stage_receipt_record"],workspace) if envelope else run/"inputs/cooled_frontend_field_stage_receipt.json"
    stage=shared._load(path)
    if stage.get("schema_version") != 2 or stage.get("role") != FIELD_ROLE or stage.get("status") != "success":
        raise ValueError("successful cooled field stage required")
    identity = shared._load(_verified_small_record(stage["cache_identity_record"],workspace))
    if canonical_pa_family_cache_key(identity) != stage["cache_key"]:
        raise ValueError("cooled field source cache identity differs")
    generation = Path(stage["generation_directory"])
    transaction = load_pa_family_cache_transaction(generation.parents[2], stage["cache_key"])
    if (transaction["status"] != "published" or transaction["generation_sha256"] != stage["generation_sha256"]
            or generation != generation.parents[2] / stage["cache_key"] / "generations" / stage["generation_sha256"]):
        raise ValueError("cooled field generation is not published")
    cache_manifest = validate_pa_family_cache_generation(generation, expected_cache_key=stage["cache_key"],
        expected_filenames=[p["output_basename"] for p in shared._load(run/"inputs/cooled_field_plan.json")["working_points"]],
        verify_payload=False)
    if cache_manifest["generation_sha256"] != stage["generation_sha256"] or cache_manifest["identity"] != identity:
        raise ValueError("cooled fields are not the exact published generation")
    records=_records(stage["working_points"])
    indexed = {row["name"]: row for row in cache_manifest["files"]}
    for record in records.values():
        name = Path(record["path"]).name
        if Path(record["path"]).resolve() != (generation/name).resolve() or any(record[key] != indexed[name][key] for key in ("bytes", "sha256")):
            raise ValueError("cooled working point differs from published inventory")
    for key, local in (("field_plan_record","cooled_field_plan.json"),("geometry_record","frontend.gem")):
        verified_path=_verified_small_record(stage[key],workspace)
        local_path=(run/"inputs"/local).resolve(strict=True)
        if local_path != verified_path and file_sha256(local_path) != stage[key]["sha256"]:
            raise ValueError("pressure control changed geometry, mesh or voltage endpoint plan")
    if source:
        if envelope.get("source_owner_manifest_record") is None:
            raise ValueError("shared fields require a sealed owner manifest identity")
        manifest_path=_record_path(envelope["source_owner_manifest_record"],workspace)
        frozen_manifest = run / "inputs/cooled_field_source_manifest.json"
        owner=shared._load(_verified_small_record(dict(envelope["source_owner_manifest_record"],path=str(frozen_manifest))))
        require_completed_terminal_publication(manifest_path)
        if owner.get("status") not in ("success", "failed"):
            raise ValueError("shared field owner is not a terminal sealed run")
        if manifest_path.parent.parent.name != "runs" or _record_path(owner["run_config"],workspace) != manifest_path.parent/"run_config.json":
            raise ValueError("shared field producer config is not its managed owner")
        _verified_small_record(dict(owner["run_config"],path=str(run/"inputs/cooled_field_source_run_config.json")))
        receipt_record=envelope["field_stage_receipt_record"]
        if not any(_same_identity(receipt_record,r,workspace) for r in [*owner.get("inputs",{}).values(),*owner.get("outputs",[])]):
            raise ValueError("shared field receipt is not bound by its sealed owner manifest")
        for key in ("geometry_record","field_plan_record","cache_identity_record"):
            if not any(_same_identity(stage[key],r,workspace) for r in owner.get("inputs",{}).values()):
                raise ValueError("field scientific provenance is not bound by its terminal owner")
    bank_path=_verified_small_record(stage["field_bank_record"],workspace)
    if bank_path != _record_path(dict(path=stage["field_bank_path"]),workspace):
        raise ValueError("field bank path identity differs")
    bank=shared._load(bank_path)
    roles=_resolve_standalone_dynamic_field_bank(bank,{"coarse_frontend":1})
    if len(roles) != 1:
        raise ValueError("cooled field bank must have one coarse frontend role")
    role=roles[0]
    expected=dict(carrier_pa_basename=Path(records["carrier_off"]["path"]).name,
                  rf_differential_pa_basenames=[Path(records["rf_differential_unit"]["path"]).name],
                  rf_reference_voltage_v=1.,
                  pulse_delta_pa_basename=Path(records["pulse_delta"]["path"]).name)
    if any(role[key] != value for key,value in expected.items()):
        raise ValueError("core field bank differs from cooled records")
    return dict(records=records,bank=bank,receipt=dict(path=str(path), exists=True, bytes=path.stat().st_size, sha256=envelope["field_stage_receipt_record"]["sha256"]) if envelope else file_record(path),identity_validation=stage["identity_validation"])


def context(run: Path, *, reference_phase: dict | None = None, shared_context: dict | None = None) -> dict:
    """Add the physical adapter, reusing a context verified in this same call."""
    run=Path(run).resolve(strict=True)
    workspace=run.parents[4]
    result=shared._context(run,field_provider=fields) if shared_context is None else shared_context
    inputs=run/"inputs"
    result.update(conditioner=shared._load(inputs/"conditioner_contract.json"),
                  cooled_drive=shared._load(inputs/"cooled_drive.json"), experiment=shared._load(inputs/"cooled_experiment.json"))
    decision_record=result["experiment"]["common_pulse_decision"]
    if reference_phase is not None:
        if result["experiment"]["pressure_scale"] != 0 or decision_record is not None:
            raise ValueError("reference calibration requires explicit vacuum and no production decision")
        if reference_phase.get("role") != "cooled_reference_phase" or reference_phase.get("pulse_mode") not in (1, 2):
            raise ValueError("explicit reference phase and pulse mode required")
        decision=reference_phase
        mode=decision["pulse_mode"]
        if mode == 2 and decision["pulse_time_us"] is not None:
            raise ValueError("held-OFF reference has no applied pulse clock")
    else:
        if decision_record is None or result["experiment"]["field_source"] is None:
            raise ValueError("population dispatch requires sealed fields and a shared actual-field pulse decision")
        decision_path=_verified_small_record(decision_record,workspace)
        decision=shared._load(decision_path)
        if decision.get("schema_version") != 1 or decision.get("role") != "actual_field_reference_exit_centering":
            raise ValueError("unsupported actual-field pulse decision")
        mode=1
        result["decision"]=decision
    identity_record=decision.get("field_identity",{}).get("field_stage_receipt_record")
    if identity_record is None or not _same_identity(identity_record,result["fields"]["receipt"],workspace):
        raise ValueError("calibration is bound to different actual fields")
    release=decision["release_start_us"]
    if reference_phase is not None:
        result["flight_horizon_us"]=release+result["numerics"]["maximum_flight_us"]
    pulse=decision["pulse_time_us"] if reference_phase is not None else decision["actual_pulse_time_us"]
    if not result["cooled_drive"]["entrance_close_us"] < release < result["flight_horizon_us"]:
        raise ValueError("reference release lies outside the ordered physical horizon")
    if mode == 1 and (isinstance(pulse,bool) or not isinstance(pulse,(int,float)) or not math.isfinite(pulse)
                      or not release < pulse < result["flight_horizon_us"]):
        raise ValueError("common calibrated clocks lie outside the ordered physical horizon")
    calibration=decision["voltage_calibration"]
    for key in ("inner_correction_v","release_hp_common_correction_v"):
        value=calibration.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError("explicit finite actual-field voltage calibration required")
    result["voltage_calibration"]=calibration
    result["cooled_drive"]=dict(result["cooled_drive"],release_start_us=release)
    hs1_path=inputs/"cooled_collision_hs1.lua"
    identity=shared._load(inputs/"cooled_hs1_identity.json")
    if _verified_small_record(identity["adapted"],workspace) != hs1_path.resolve(strict=True):
        raise ValueError("frozen official HS1 adapter identity differs")
    result["hs1_source"]=hs1_path.read_text(encoding="utf-8")
    module=Path(__file__).resolve().with_name("cooled_frontend.lua")
    result["cooled_module_source"]=module.read_text(encoding="utf-8")
    result["code_records"]["cooled_module"]=file_record(module)
    result["code_records"]["hs1"]=dict(path=str(hs1_path),exists=True,
        bytes=identity["adapted"]["bytes"],sha256=identity["adapted"]["sha256"])
    if decision_record is not None:
        result["code_records"]["common_pulse_decision"]=dict(path=str(decision_path),exists=True,
            bytes=decision_record["bytes"],sha256=decision_record["sha256"])
    for name in ("program.py","runtime.py"):
        source=Path(__file__).resolve().with_name(name)
        result["code_records"]["cooled_"+name]=file_record(source)
    for name in ("cooled_experiment.json","cooled_drive.json","conditioner_contract.json","cooled_field_plan.json"):
        result["code_records"][name]=file_record(inputs/name)
    return result


def prepare_dispatch_request(run: Path,phase: str,pulse: float,times: list[float]) -> dict:
    run=shared._owner(run,phase)
    ctx=context(run)
    if pulse != ctx["decision"]["actual_pulse_time_us"]:
        raise ValueError("both pressure arms must use the exact common OA pulse clock")
    shared._phase(run,phase,pulse,times)
    return shared.prepare_dispatch_request(run,phase,context=ctx,workload_topology_id="cooled_frontend_one_carrier_six_readonly_responses_v1")


def materialize_batches(run: Path,phase: str,plan: dict,pulse: float,times: list[float]) -> dict:
    from integrations.workflows.cooled_frontend.program import build_program
    ctx=context(run)
    if pulse != ctx["decision"]["actual_pulse_time_us"]:
        raise ValueError("both pressure arms must use the exact common OA pulse clock")
    gas = ctx["conditioner"]["gas"]
    parameters = gas["parameters"]
    scale = ctx["experiment"]["pressure_scale"]
    pressure = parameters["hp_pressure_pa"]*scale
    collision_active = scale > 0 and pressure > 0 and (
        parameters["cross_section_m2"] > 0 or parameters["mean_free_path_mm"] > 0)
    policy = dict(
        comparison_policy="independent_stochastic_collisions" if collision_active else "deterministic_trajectory_parity",
        scope="saved_controls_only" if collision_active else "fresh_process",
        collision_active=collision_active, pressure_scale=scale, effective_hp_pressure_pa=pressure,
        gas_parameters={key: parameters[key] for key in ("cross_section_m2", "mean_free_path_mm")},
        gas_domain_native_mm=gas["domain_native_mm"],
    )
    validate_pa_family_cache_generation(
        Path(next(iter(ctx["fields"]["records"].values()))["path"]).parent,
        verify_payload=False, require_publication_pin=True)
    return shared.materialize_batches(run,phase,plan,pulse,times,context=ctx,program_builder=build_program,
                                      default_replay_policy=policy)


def materialize_reference_case(run: Path,ctx: dict,phase_input: dict) -> dict:
    """Build the already validated one-ID reference phase, never an N=100 cohort."""
    from integrations.workflows.cooled_frontend.program import build_program
    run=shared._owner(run,"extraction")
    reference_rows=ctx["rows"]
    if len(reference_rows)!=1 or set(reference_rows[0])!=set(shared.GLOBAL_COLUMNS) or int(reference_rows[0]["particle_id"])!=1 or any(not math.isfinite(float(v)) for v in reference_rows[0].values()):
        raise ValueError("cold reference requires exactly one explicit GLOBAL_COLUMNS state with ID1")
    suffix="__"+phase_input["phase"]
    reference_phase=dict(role="cooled_reference_phase",pulse_mode=phase_input["pulse_mode"],
        pulse_time_us=phase_input["pulse_time_us"],release_start_us=ctx["cooled_drive"]["release_start_us"],
        voltage_calibration=ctx["voltage_calibration"],
        field_identity=dict(field_stage_receipt_record=ctx["fields"]["receipt"]))
    role=dict(schema_version=1,role="rf_oatof_cooled_frontend_cold_reference",particle_count=1,
              reference_rows=reference_rows,reference_phase=reference_phase,
              qualification="independent_actual_field_calibration__not_mother_population_evidence")
    shared._json_once(run/"inputs"/("cooled_reference_role"+suffix+".json"),role)
    # The common FLY2 renderer consumes CSV-shaped strings. Preserve the
    # supplied binary64 state exactly while keeping this adapter typed numeric.
    case_rows=[{key:format(float(value),".17g") for key,value in row.items()} for row in reference_rows]
    validate_pa_family_cache_generation(
        Path(next(iter(ctx["fields"]["records"].values()))["path"]).parent,
        verify_payload=False, require_publication_pin=True)
    result=shared._case(run,"extraction","cold_reference"+suffix,case_rows,ctx,phase_input,program_builder=build_program)
    result.update(role=role["role"],qualification=role["qualification"],mother_population_flight=False)
    shared._json_once(run/"inputs"/("cooled_reference_case"+suffix+".json"),result)
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    for command in ("prepare-dispatch", "materialize-batches"):
        item=sub.add_parser(command)
        item.add_argument("--run",type=Path,required=True)
        item.add_argument("--phase",choices=shared.PHASES,required=True)
        item.add_argument("--pulse-time-us",type=float,required=True)
        item.add_argument("--shared-times-json",type=Path,required=True)
        if command=="materialize-batches":
            item.add_argument("--batch-plan",type=Path,required=True)
    args=parser.parse_args()
    times=json.loads(args.shared_times_json.read_text(encoding="utf-8-sig"))
    if args.command=="prepare-dispatch":
        result=prepare_dispatch_request(args.run,args.phase,args.pulse_time_us,times)
    else:
        result=materialize_batches(args.run,args.phase,shared._load(args.batch_plan),args.pulse_time_us,times)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
