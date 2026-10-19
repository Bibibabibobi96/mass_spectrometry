"""Project projections around repository SIMION dispatch and ID rebasing.

No resource decision is made here. Canonical particles are sliced unchanged;
the common scheduler owns intervals, and the common CSV merger owns ID offsets.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import remove_recorded_files
from common.contracts.write_run_manifest import build_run_manifest, resolve_path, write_json_atomic
from common.contracts.verify_run_manifest import record_path
from common.ion_release.release import generate_release_states
from common.contracts.particle_physics import kinetic_energy_ev
from common.simion.particle_batching import merge_rebased_particle_csvs
# Import public dependencies before prepare freezes the loaded source closure.
from common.simion import resource_profile as resource_profile
from common.simion import resource_scheduler
from common.simion.particle_source import render_standard_beams, render_source_states
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import to_project_position, to_project_vector


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def publish_manifest(run: Path, status: str) -> dict:
    """Pass arbitrarily many worker outputs directly to the public Python API.

    Repeated absolute --output arguments can exceed Windows' command-line limit.
    Frozen inputs retain their input identity; only generated files are outputs.
    """
    if status not in {"success", "failed"}:
        raise ValueError("native run requires a terminal status")
    config = _read(run/"run_config.json")
    project_root = Path(config["project_root"]).resolve() if config.get("project_root") else None
    input_paths = {resolve_path(value, run.resolve(), project_root)
                   for value in config.get("inputs", {}).values() if isinstance(value, str)}
    outputs = sorted(path for path in run.rglob("*") if path.is_file()
                     and path.resolve() not in input_paths
                     and path.name not in {"run_manifest.json", "run_config.json"}
                     and not path.name.startswith("."))
    manifest = build_run_manifest(run/"run_config.json", status,
                                  software=["SIMION 2020", "Python 3.11"], output_paths=outputs)
    write_json_atomic(run/"run_manifest.json", manifest)
    return manifest


def prepare_request(run: Path) -> dict:
    """Describe the real one-instance native loading identity without CPU limits."""
    c = _read(run/"inputs/resolved_model.json")
    _archive_policy(run)
    profile = _read(run/"inputs/execution_profiles.json")["profiles"][0]
    retain = profile["retain_batch_trajectories"]
    if not isinstance(retain, bool):
        raise ValueError("retain_batch_trajectories must be boolean")
    field = Path(c["native_field"]["directory"])/"processor.pa0"
    source_manifest = c["native_field"].get("source_manifest")
    if source_manifest:
        parent = Path(source_manifest).parent
        manifest = _read(Path(source_manifest))
        outputs = manifest["outputs"]
        records = list(manifest["inputs"].values()) + (list(outputs.values()) if isinstance(outputs, dict) else outputs)
        pa_sha = next(r["sha256"] for r in records if record_path(r, base_dir=parent)==field.resolve())
    else:
        pa_sha = file_sha256(field)
    identity = {key:c[key] for key in ("baseline", "numerics", "source", "native_operating_point", "native_projection")}
    if "coordinate_transform" in c:
        identity["coordinate_transform"] = c["coordinate_transform"]
    identity["native_timing"] = c["native_timing"]
    identity["programs"] = {name:file_sha256(run/"simion"/name) for name in ("processor.lua", "collision_hs1.lua", "native_drive.lua", "simion_rf_drive.lua", "extraction_force_audit.lua")}
    identity["retain_batch_trajectories"] = retain
    request = dict(solver="SIMION", field_kind="rf", particle_count=c["source"]["particle_count"], independent_particles=True,
                   rf_steps_per_period=c["numerics"]["rf_steps_per_period"], trajectory_quality=c["numerics"]["trajectory_quality"],
                   frontend_grid_profile_id="ion_processor_native_uniform_grid", frontend_cell_mm_xyz=[c["numerics"]["native_grid_mm"]]*3,
                   trajectory_quality_profile_id=("ion_processor_retained_native_trajectories" if retain else "ion_processor_csv_native_trajectories"), time_integration_profile_id="ion_processor_rf_hs1_stage_boundaries",
                   frontend_pa0_sha256=pa_sha, case_input_sha256=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest().upper(),
                   workload_topology_id="ion_processor_one_native_instance_15_adjustable_electrodes",
                   field_loading_policy_id=("native_all_15_basis_force_audit_retained_trajectories" if retain else "native_all_15_basis_force_audit_csv_diagnostics"))
    templates = not bool(source_manifest)
    preparation = dict(requires_vendor_templates=templates, native_pa0_record=dict(path=str(field.resolve()),bytes=field.stat().st_size,sha256=pa_sha),
                       template_count=request["particle_count"],script=str(run/"simion/build_batch_iobs.lua"))
    if templates:
        destinations=[]
        for index in range(1,request["particle_count"]+1):
            folder=run/f"simion_batch_{index:04d}"
            folder.mkdir(exist_ok=True)
            destinations.append(str((folder/"processor.iob").resolve()).replace("\\","/"))
        canonical=json.dumps(str((run/"simion/processor.iob").resolve()).replace("\\","/"))
        expected=json.dumps(str(field.resolve()).replace("\\","/").lower())
        script="local wb=simion.wb\nwb:load("+canonical+")\n"
        script+="assert(wb.instances[1].pa.path:gsub(string.char(92),'/'):lower()=="+expected+",'batch template PA identity mismatch')\n"
        for target in destinations:script+="wb:save("+json.dumps(target)+")\n"
        script+="print('ION_PROCESSOR_BATCH_IOB_TEMPLATES=PASS')\n"
        (run/"simion/build_batch_iobs.lua").write_text(script,encoding="utf-8")
    _write(run/"inputs/batch_iob_preparation.json",preparation)
    # Validate using the public planner; the runner performs live planning again.
    resource_scheduler.plan_simion_dispatch(request, [])
    _write(run/"inputs/simion_dispatch_request.json", request)
    return request


def materialize_batches(run: Path, batch_plan: Path) -> dict:
    """Create isolated sibling workbenches; keep IOB relative PA references valid."""
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal
    run = run.resolve()
    c = _read(run/"inputs/resolved_model.json")
    retain = _read(run/"inputs/execution_profiles.json")["profiles"][0]["retain_batch_trajectories"]
    if not isinstance(retain, bool):
        raise ValueError("retain_batch_trajectories must be boolean")
    plan = _read(batch_plan)
    mother = generate_release_states(c["source"])
    if plan["particle_count"] != len(mother):
        raise ValueError("batch plan population differs from frozen mother cohort")
    controls = ("processor.lua", "collision_hs1.lua", "native_drive.lua", "simion_rf_drive.lua", "extraction_force_audit.lua", "processor.iob")
    workers = []
    for batch in plan["batches"]:
        first, last, offset = (batch[k] for k in ("particle_id_min", "particle_id_max", "simion_particle_id_offset"))
        if not 1<=first<=last<=len(mother) or last-first+1!=batch["count"] or offset!=first-1:
            raise ValueError("invalid canonical batch interval")
        folder = run/f"simion_batch_{batch['index']:04d}"
        receipt = folder/"batch_input.json"
        if receipt.exists():
            if _read(receipt)["batch"] != batch:
                raise ValueError("replan changed an already materialized batch")
        else:
            template=folder/"processor.iob"
            is_template=not c["native_field"].get("source_manifest")
            if folder.exists():
                allowed = {"processor.iob", "processor.lua", "processor.fly2"}
                if not is_template or not {path.name for path in folder.iterdir()} <= allowed:
                    raise ValueError("batch directory exists without an immutable input receipt")
                # Official wb:save copies associated programs and particles along
                # with the relocated IOB. Only exact master controls may be
                # replaced by the immutable worker copy / canonical source slice.
                for name in ("processor.lua", "processor.fly2"):
                    associated = folder / name
                    if (associated.exists() or associated.is_symlink()) and (
                        not associated.is_file() or associated.is_symlink()
                        or associated.stat().st_nlink != 1
                        or associated.resolve().parent != folder.resolve()
                        or file_sha256(associated) != file_sha256(run/"simion"/name)
                    ):
                        raise ValueError("vendor batch template companion differs from canonical master: " + name)
            folder.mkdir(exist_ok=True)
            if is_template and not template.is_file():raise ValueError("native batch IOB template was not built before flight")
            # Same parent and depth as canonical simion: every relative IOB PA
            # reference resolves identically. No binary rewrite or vendor save.
            if folder.parent != (run/"simion").parent:
                raise ValueError("batch IOB must be a sibling of canonical IOB")
            for name in controls:
                if name == "processor.iob" and is_template:continue
                shutil.copyfile(run/"simion"/name, folder/name)
            worker_config = copy.deepcopy(c)
            worker_config["execution_batch"] = dict(particle_id_offset=offset, particle_id_min=first, particle_id_max=last, retain_trajectories=retain)
            beams, companions = [], []
            for local_id, row in enumerate(mother[first-1:last], 1):
                v = [row[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s")]
                energy = kinetic_energy_ev(row["mass_amu"], *v)
                xyz = [row[k] for k in ("x_mm", "y_mm", "z_mm")]
                world = to_project_position(c, xyz)
                companions.append(dict(particle_id=local_id,t=0,x=xyz[0],y=xyz[1],z=xyz[2],vx=v[0]/1000,vy=v[1]/1000,vz=v[2]/1000,ke=energy))
                beams.append(dict(tob=0,mass=row["mass_amu"],charge=row["charge_state"],x=world[0],y=world[1],z=world[2],direction=to_project_vector(c,v),ke=energy,cwf=1,color=1))
            (folder/"processor.fly2").write_text(render_standard_beams(beams),encoding="utf-8")
            (folder/"source_states.lua").write_text(render_source_states(companions),encoding="utf-8")
            (folder/"frozen_config.lua").write_text("return "+lua_literal(worker_config)+"\n",encoding="utf-8")
            _write(receipt,dict(batch=batch,source_global_ids=list(range(first,last+1)),iob_policy=("vendor_saved_absolute_PA_reference_template" if is_template else "byte_exact_sibling_copy_same_relative_PA_resolution"),native_field_directory=c["native_field"]["directory"]))
        workers.append(dict(batch=batch,directory=str(folder)))
    config = _read(run/"run_config.json")
    for worker in workers:
        for path in Path(worker["directory"]).iterdir():
            if path.name in (*controls,"processor.fly2","source_states.lua","frozen_config.lua","batch_input.json"):
                config.setdefault("inputs",{})[str(path.relative_to(run))]=str(path)
    config.setdefault("inputs",{}).update(simion_dispatch_request=str(run/"inputs/simion_dispatch_request.json"),simion_batch_plan=str(batch_plan))
    _write(run/"run_config.json",config)
    _write(run/"results/batch_materialization.json",dict(workers=workers))
    return dict(workers=workers)


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        return reader.fieldnames or [],list(reader)


def _csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def _archive_policy(run: Path) -> bool:
    profiles = _read(run/"inputs/execution_profiles.json")["profiles"]
    matches = [profile for profile in profiles if profile["profile_id"] == "native_functional"]
    if len(matches) != 1:
        raise ValueError("exactly one frozen native_functional execution profile is required")
    enabled = matches[0]["archive_merged_worker_csv"]
    if not isinstance(enabled, bool):
        raise ValueError("archive_merged_worker_csv must be boolean")
    return enabled


def _verify_worker_archive(archive: Path, records: list[dict]) -> None:
    """Read every archived byte and verify CRC plus original SHA/size identities."""
    with zipfile.ZipFile(archive) as bundle:
        if bundle.namelist() != [record["path"] for record in records] or bundle.testzip() is not None:
            raise ValueError("worker CSV archive member inventory or CRC differs")
        for record in records:
            digest, size = hashlib.sha256(), 0
            with bundle.open(record["path"]) as stream:
                while block := stream.read(1024*1024):
                    digest.update(block)
                    size += len(block)
            if size != record["bytes"] or digest.hexdigest().upper() != record["sha256"]:
                raise ValueError("worker CSV archive identity differs: " + record["path"])


def _archive_merged_worker_csv(run: Path, batch: dict) -> dict:
    """Retain one consumed worker before the public merger opens the next."""
    run = run.resolve()
    prefix = f"merged_worker_csv_batch_{batch['index']:04d}"
    archive = run/"results"/(prefix+".zip")
    plan_path = run/"results"/(prefix+"_archive_plan.json")
    receipt_path = run/"results"/(prefix+"_archive_receipt.json")
    if any(path.exists() for path in (archive, plan_path, receipt_path)):
        raise ValueError("worker CSV archive outputs already exist; use a new run")
    records = []
    for name in ("events.csv", "samples.csv", "events_id_first.csv", "extraction_steps.csv", "extraction_impulses.csv"):
        path = run/f"simion_batch_{batch['index']:04d}"/name
        if path.resolve() != path or not path.is_file() or path.is_symlink():
            raise ValueError("worker CSV archive source is not an exact same-run regular file")
        records.append(dict(path=path.relative_to(run).as_posix(),
                            bytes=path.stat().st_size, sha256=file_sha256(path)))
    if not records or len({record["path"] for record in records}) != len(records):
        raise ValueError("worker CSV archive source inventory is empty or duplicated")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for record in records:
            with (run/record["path"]).open("rb") as source, bundle.open(record["path"], "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, length=1024*1024)
    with archive.open("rb+") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    _verify_worker_archive(archive, records)
    plan = dict(schema_version=1, role="ion_processor_worker_csv_archive_plan", status="verified",
                source_files=records, archive=dict(path=archive.relative_to(run).as_posix(),
                    bytes=archive.stat().st_size, sha256=file_sha256(archive)),
                validation_receipt_sha256=file_sha256(run/"results/batch_input_validation_receipt.json"),
                semantics="Byte-exact worker CSV preservation after all ID/HS1/seed checks and consumption by the public CSV merger; archives reconstruct evidence even if a later batch merge fails")
    write_json_atomic(plan_path, plan)
    receipt = dict(schema_version=1, role="ion_processor_worker_csv_archive_receipt", status="removal_pending",
                   plan_path=plan_path.relative_to(run).as_posix(), plan_sha256=file_sha256(plan_path), removed_files=[])
    write_json_atomic(receipt_path, receipt)
    try:
        for record in remove_recorded_files(run, records):
            receipt["removed_files"].append(record["path"])
            write_json_atomic(receipt_path, receipt)
    except Exception as exc:
        receipt.update(status="removal_failed", error=str(exc))
        write_json_atomic(receipt_path, receipt)
        raise
    receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    return receipt


def merge_batches(run: Path, batch_plan: Path) -> dict:
    """Validate full native batch closure, then use public offset rebasing once."""
    archive_workers = _archive_policy(run)
    c, plan = _read(run/"inputs/resolved_model.json"), _read(batch_plan)
    events, samples, seeds, audits, log_parts = [], [], [], [], []
    from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import STEP_COLUMNS, IMPULSE_COLUMNS
    force_headers = {"extraction_steps.csv":STEP_COLUMNS, "extraction_impulses.csv":IMPULSE_COLUMNS}
    force_sources = {name:[] for name in force_headers}
    original_fields = None
    for batch in plan["batches"]:
        folder=run/f"simion_batch_{batch['index']:04d}"
        offset=batch["simion_particle_id_offset"]
        log=run/f"logs/flight_batch_{batch['index']:04d}.log"
        if "ION_PROCESSOR_END" not in log.read_text(encoding="utf-8-sig"):
            raise ValueError("batch lacks native completion sentinel")
        fields, rows=_rows(folder/"events.csv")
        if original_fields is None:original_fields=fields
        if fields!=original_fields:raise ValueError("batch event columns differ")
        expected=list(range(1,batch["count"]+1))
        for event in ("source","terminal"):
            if sorted(int(row["particle_id"]) for row in rows if row["event"]==event)!=expected:
                raise ValueError("batch source/terminal IDs do not close")
        if any(int(row["particle_id"]) not in expected for row in rows):raise ValueError("foreign batch ID")
        # Transparent column projection only: the public helper requires ID first.
        reordered=folder/"events_id_first.csv"
        _csv(reordered,["particle_id",*[field for field in fields if field!="particle_id"]],rows)
        _, sample_rows = _rows(folder/"samples.csv")
        if any(int(row["particle_id"]) not in expected for row in sample_rows):
            raise ValueError("foreign batch sample ID")
        events.append((reordered,offset));samples.append((folder/"samples.csv",offset))
        for name in force_sources:
            force_fields, force_rows = _rows(folder/name)
            if tuple(force_fields) != force_headers[name]:
                raise ValueError("batch force-audit header differs from declared protocol")
            if any(int(row["particle_id"]) not in expected for row in force_rows):
                raise ValueError("foreign batch force-audit ID")
            force_sources[name].append((folder/name,offset))
        seeds.append((folder/"collision_rng_seeds.csv",offset))
        audit_fields,audit=_rows(folder/"hs1_bound_parameters.csv")
        if len(audit)!=2 or {row["phase"] for row in audit}!={"before_init","after_init"}:raise ValueError("batch lacks HS1 audit phases")
        audits.append((audit_fields,audit))
        log_parts.append(f"BATCH_LOG index={batch['index']} offset={offset}\n"+log.read_text(encoding="utf-8-sig"))
    merged=run/"simion/events_id_first.csv"
    merge_rebased_particle_csvs(events,merged)
    _,rows=_rows(merged);_csv(run/"simion/events.csv",original_fields,rows)
    merge_rebased_particle_csvs(seeds,run/"simion/collision_rng_seeds.csv")
    _,seed_rows=_rows(run/"simion/collision_rng_seeds.csv")
    ids=[]
    for row in seed_rows:
        particle=int(row["particle_id"]);ids.append(particle)
        if int(row["global_particle_id"])!=particle or int(row["seed"])!=c["numerics"]["seed"]+particle-1:
            raise ValueError("collision RNG does not match canonical per-particle policy")
    if ids!=list(range(1,c["source"]["particle_count"]+1)):raise ValueError("seed receipt does not cover full mother cohort")
    expected_audit = dict(gas_mass_amu=c["baseline"]["gas"]["mass_amu"],temperature_k=c["baseline"]["gas"]["temperature_k"],pressure_pa=0,
                          sigma_m2=c["baseline"]["gas"]["cross_section_m2"],mean_free_path_mm=c["baseline"]["gas"]["mean_free_path_mm"],
                          steps_per_mfp=c["numerics"]["hs1_steps_per_mfp"],random_seed=c["numerics"]["seed"]+1,mark_collisions=0,trace_level=0)
    for fields,audit in audits:
        for row in audit:
            if any(float(row[key])!=value for key,value in expected_audit.items()):raise ValueError("worker HS1 bindings differ from frozen authority")
    canonical=[next(row for row in audits[0][1] if row["phase"]==phase) for phase in ("before_init","after_init")]
    _csv(run/"simion/hs1_bound_parameters.csv",audits[0][0],canonical)
    (run/"logs/flight.log").write_text("\n".join(log_parts),encoding="utf-8")
    for name, sources in force_sources.items():
        merge_rebased_particle_csvs(sources,run/"simion"/name)
    result=dict(schema_version=1,role="ion_processor_batch_merge",particle_count=len(ids),batch_count=len(plan["batches"]),all_ids_closed=True,
                hs1_audit="all per-worker rows validated; canonical CSV is the identical before/after pair",rng_policy=c["numerics"]["collision_rng_policy"])
    write_json_atomic(run/"results/batch_input_validation_receipt.json",
           {**result, "role": "ion_processor_batch_input_validation", "status": "validated_before_sample_merge"})
    archive_receipts = []
    def consumed_samples():
        for batch, source in zip(plan["batches"], samples, strict=True):
            yield source
            # The public merger closes each source before requesting the next.
            # Retain its byte-exact ZIP before removing any raw source file.
            if archive_workers:
                archive_receipts.append(_archive_merged_worker_csv(run, batch))
    merge_rebased_particle_csvs(consumed_samples(),run/"simion/samples.csv")
    _write(run/"results/batch_merge_receipt.json",result)
    if archive_workers:
        write_json_atomic(run/"results/merged_worker_csv_archive_receipt.json",
            dict(schema_version=1, role="ion_processor_worker_csv_archive_aggregate", status="complete",
                 merge_receipt_sha256=file_sha256(run/"results/batch_merge_receipt.json"), batches=archive_receipts))
    return result
