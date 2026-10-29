"""Freeze and analyze a bounded IP-to-first-prism placement experiment.

The measured source is held fixed. This workflow solves an independent local
electrostatic boundary problem and stops after P1; it never closes or flies MR.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

from common.contracts.particle_count_policy import load_particle_count_policy, POLICY_PATH
from common.contracts.write_run_manifest import file_record, publish_run_manifest
from common.contracts import artifact_retention, run_capacity_lifecycle
from common.simion import resource_profile, resource_scheduler, particle_batching
from common.simion.particle_source import render_standard_beams
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import verified_reference
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_geometry import prepare_geometry


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def lua_literal(value) -> str:
    """Encode only finite JSON-compatible data, never executable user text."""
    if isinstance(value, dict):
        return "{"+",".join("["+lua_literal(k)+"]="+lua_literal(v) for k,v in value.items())+"}"
    if isinstance(value, list):
        return "{"+",".join(lua_literal(v) for v in value)+"}"
    if isinstance(value, str):
        return json.dumps(value.replace("\\", "/"), ensure_ascii=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and math.isfinite(value):
        return format(value, ".17g")
    raise ValueError("unsupported Lua projection value")


def validate_contract(contract: dict) -> None:
    """Reject ambiguous source, observation or numerical experiment definitions."""
    required={"schema_version","role","references","distances_mm","numerics","observation_planes",
              "committed_new_bytes","limits","claim","official_sources"}
    if set(contract)!=required or contract["schema_version"]!=1 or contract["role"]!="ip_prism_distance_experiment":
        raise ValueError("unsupported distance experiment contract")
    if set(contract["references"])!={"geometry","voltages","component_particle_state","source_census","native_timing"}:
        raise ValueError("five explicit sealed references required")
    distances=contract["distances_mm"]
    if not distances or len(set(distances))!=len(distances) or any(isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in distances):
        raise ValueError("distinct positive distances required")
    _validate_local_controls(contract["numerics"], contract["observation_planes"], contract["committed_new_bytes"])


def _validate_local_controls(n: dict, planes: list, committed_new_bytes: int) -> None:
    """Share numerical, ordered-plane and capacity semantics between local authors."""
    if set(n)!={"box_mm","pitch_mm","convergence_v","maximum_step_us","sample_interval_us","maximum_flight_us","trajectory_quality","probe_step_mm"}:
        raise ValueError("complete local numerical contract required")
    for key in ("convergence_v","maximum_step_us","sample_interval_us","maximum_flight_us","probe_step_mm"):
        if isinstance(n[key],bool) or not math.isfinite(n[key]) or n[key]<=0:
            raise ValueError("positive local numerical controls required")
    if not isinstance(n["trajectory_quality"],int) or isinstance(n["trajectory_quality"],bool):
        raise ValueError("integer trajectory quality required")
    if not planes or planes[-1]["name"]!="p1_exit" or len({p["name"] for p in planes})!=len(planes):
        raise ValueError("distinct ordered planes ending at p1_exit required")
    if any(not math.isfinite(p["z_mm"]) for p in planes) or any(a["z_mm"]<=b["z_mm"] for a,b in zip(planes,planes[1:])):
        raise ValueError("planes must follow the negative-z beam direction")
    if committed_new_bytes<=0:
        raise ValueError("positive capacity commitment required")


def freeze_references(contract: dict, inputs: Path) -> dict:
    """Verify and freeze exact small sealed records, without reading historical PA."""
    values={};receipts={}
    for role,reference in contract["references"].items():
        owner=Path(reference["run"])
        source=verified_reference(owner,reference["relative"],required_status=reference["required_status"])
        target=inputs/(role+source.suffix)
        shutil.copyfile(source,target)
        record=file_record(source)
        if file_record(target)["sha256"]!=record["sha256"]:
            raise ValueError("frozen reference differs")
        receipts[role]={"owner_manifest":file_record(owner/"run_manifest.json"),"source":record,"frozen":file_record(target)}
        values[role]=target
    write_json(inputs/"source_binding.json",receipts)
    return values


def read_source(path: Path, census_path: Path) -> tuple[list, list]:
    """Keep all transferred IDs and the original full mother census."""
    with path.open(encoding="utf-8-sig",newline="") as handle:
        source=list(csv.DictReader(handle))
    with census_path.open(encoding="utf-8-sig",newline="") as handle:
        census=list(csv.DictReader(handle))
    ids=[int(r["particle_id"]) for r in source]
    mother=[int(r["particle_id"]) for r in census]
    if not source or len(ids)!=len(set(ids)) or len(mother)!=len(set(mother)) or not set(ids)<=set(mother):
        raise ValueError("source/census IDs do not close")
    for row in source:
        for key in ("instrument_time_us","mass_amu","charge_state","position_x_mm","position_y_mm","position_z_mm","velocity_x_m_s","velocity_y_m_s","velocity_z_m_s"):
            if not math.isfinite(float(row[key])):
                raise ValueError("nonfinite source state")
        if float(row["position_z_mm"])!=0 or float(row["velocity_z_m_s"])>=0:
            raise ValueError("measured source must leave z0 along negative z")
    if set(ids)!={int(r["particle_id"]) for r in census if r["transfer_status"]=="transferred"}:
        raise ValueError("transferred census differs from source")
    return source,census


def freeze_code(repo: Path, inputs: Path) -> None:
    """Freeze the actually imported repository closure and adjacent resources."""
    for module in tuple(sys.modules.values()):
        value=getattr(module,"__file__",None)
        if not value:
            continue
        path=Path(value).resolve()
        if path.suffix!=".py" or repo not in path.parents:
            continue
        relative=path.relative_to(repo)
        if relative.parts[0] not in {"common","projects"}:
            continue
        destination=inputs/"code"/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    for relative in (POLICY_PATH.relative_to(repo),Path("common/host_resource_policy.json"),
                     Path("common/contracts/artifact_retention.json"),Path("common/contracts/artifact_capacity_policy.json")):
        destination=inputs/"code"/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(repo/relative,destination)


def validate_contour_contract(contract: dict, *, recorded_author: bool = False) -> None:
    """Validate active v6 authors, or explicitly read frozen v2/v3/v4/v5 selectors.

    The historical v2 limits were inert metadata. They remain immutable when
    consuming an already recorded run; new preparation never accepts them.
    """
    required = {"schema_version", "role", "references", "source_registration", "cases", "numerics",
                "observation_planes", "aperture_comparison", "plain_lua_executable", "committed_new_bytes", "claim", "official_sources"}
    version = contract.get("schema_version")
    if recorded_author and version == 2:
        required.add("limits")
    elif recorded_author and version == 3:
        pass
    elif version == 6:
        required.update({"field_sources", "electrode_collision_model"})
    elif recorded_author and version in (4, 5):
        required.add("field_sources")
    else:
        raise ValueError("unsupported contour focus experiment contract")
    if set(contract) != required or contract["role"] != "ip_prism_contour_focus_experiment":
        raise ValueError("unsupported contour focus experiment contract")
    if version == 6 and contract["electrode_collision_model"] not in {"native_pa", "canonical_lens_first_contact"}:
        raise ValueError("explicit native_pa/canonical_lens_first_contact collision model required")
    if set(contract["references"]) != {"geometry", "voltages"}:
        raise ValueError("contour study requires geometry and voltage references")
    _validate_local_controls(contract["numerics"], contract["observation_planes"], contract["committed_new_bytes"])
    registration = contract["source_registration"]
    if set(registration) != {"translation_mm", "from_frame_id", "to_frame_id"}:
        raise ValueError("source registration must declare translation and both frame identities")
    translation = registration["translation_mm"]
    if (not isinstance(translation, list) or len(translation) != 3 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in translation)):
        raise ValueError("finite translation_mm xyz required")
    if not all(isinstance(registration[k], str) and registration[k] for k in ("from_frame_id", "to_frame_id")):
        raise ValueError("nonempty registration frames required")
    if translation[2] != 0:
        raise ValueError("registered measured exit must preserve z0")
    if not isinstance(contract["plain_lua_executable"], str) or not contract["plain_lua_executable"]:
        raise ValueError("explicit plain Lua executable required")
    cases = contract["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty contour case table required")
    fields = {"case_id", "label", "source_run", "distance_mm", "pitch_mm", "maximum_step_us", "field_case_id", "physical_aperture"}
    if version in (5, 6):
        fields.add("lens_elements")
    if any(set(row) != fields for row in cases) or len({row["case_id"] for row in cases}) != len(cases):
        raise ValueError("complete unique contour cases required")
    for row in cases:
        if version in (5, 6) and (not isinstance(row["lens_elements"], list) or
                             any(not isinstance(element, dict) for element in row["lens_elements"])):
            raise ValueError("lens_elements requires an explicit list of electrode specifications")
        if row["physical_aperture"] is not None and not isinstance(row["physical_aperture"], dict):
            raise ValueError("physical_aperture must be an explicit object or null")
        if not all(isinstance(row[key], str) and row[key] for key in ("case_id", "label", "source_run", "field_case_id")):
            raise ValueError("case identities, source run and label must be nonempty strings")
        for key in ("case_id", "field_case_id"):
            if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in row[key]):
                raise ValueError("case identities must be path-safe ASCII identifiers")
        if any(isinstance(row[k], bool) or not isinstance(row[k], (int, float)) or not math.isfinite(row[k]) or row[k] <= 0
               for k in ("distance_mm", "maximum_step_us")):
            raise ValueError("positive finite case distance and step required")
        if (not isinstance(row["pitch_mm"], list) or len(row["pitch_mm"]) != 3 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in row["pitch_mm"])):
            raise ValueError("positive finite case pitch xyz required")
    if version in (4, 5, 6):
        sources = contract["field_sources"]
        if not isinstance(sources, dict) or set(sources) != {row["field_case_id"] for row in cases}:
            raise ValueError("field_sources must exactly cover every unique field_case_id")
        for origin in sources.values():
            if not isinstance(origin, dict):
                raise ValueError("explicit field build/reuse source required")
            if origin == {"action": "build"}:
                continue
            if (set(origin) != {"action", "source_run", "source_field_case_id"} or origin["action"] != "reuse"
                    or not isinstance(origin["source_run"], str) or not Path(origin["source_run"]).is_absolute()
                    or not isinstance(origin["source_field_case_id"], str) or not origin["source_field_case_id"]):
                raise ValueError("reuse requires an absolute source_run and explicit source_field_case_id")
    aperture = contract["aperture_comparison"]
    if set(aperture) != {"plane_names", "half_widths_mm", "center_x_mm", "center_y_mm", "slit_x_half_width_mm", "reference_case_id", "frame"}:
        raise ValueError("complete aperture comparison required")
    if aperture["frame"] not in {"global_z", "reference_normal"}:
        raise ValueError("aperture frame must be global_z or reference_normal")
    names = aperture["plane_names"]
    if not names or len(set(names)) != len(names) or not set(names) <= {p["name"] for p in contract["observation_planes"]}:
        raise ValueError("aperture plane names must identify recorded observation planes")
    widths = aperture["half_widths_mm"]
    if (not isinstance(widths, list) or not widths or len(set(widths)) != len(widths) or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in widths)):
        raise ValueError("distinct positive aperture half widths required")
    for key in ("center_x_mm", "center_y_mm", "slit_x_half_width_mm"):
        value = aperture[key]
        if key == "slit_x_half_width_mm" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (key == "slit_x_half_width_mm" and value <= 0):
            raise ValueError("finite aperture centers and positive optional slit x half width required")
    if aperture["reference_case_id"] not in {row["case_id"] for row in cases}:
        raise ValueError("aperture reference case not declared")


def _freeze_recorded_contour_source(run: Path, label: str, destination: Path) -> dict:
    """Consume a complete physical cohort, retaining failed diagnostic identity."""
    from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison import load_recorded_case
    from common.contracts.verify_run_manifest import record_path, verify_record

    case = load_recorded_case(run, label, allow_failed=True)
    destination.mkdir(parents=True, exist_ok=False)
    bindings = []
    for record in case["source_records"]:
        original = Path(record["path"])
        target = destination / original.relative_to(run.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        frozen = file_record(target)
        if frozen["sha256"] != record["sha256"].upper() or frozen["bytes"] != record["bytes"]:
            raise ValueError("frozen native source differs from consumed identity")
        bindings.append(dict(source=record, frozen=frozen))
    producer_manifest = file_record(run / "run_manifest.json")
    shutil.copyfile(run / "run_manifest.json", destination / "producer_manifest.json")
    if file_record(destination / "producer_manifest.json")["sha256"] != producer_manifest["sha256"]:
        raise ValueError("frozen producer manifest differs")
    # Bind the exact source voltage schedule as well as its resolved configuration.
    manifest = read_json(run / "run_manifest.json")
    for relative in ("simion/native_drive.lua", "simion/voltage_waveforms.lua"):
        original = (run / relative).resolve()
        matches = [record for record in [*manifest["inputs"].values(), *manifest["outputs"]]
                   if record_path(record, base_dir=run) == original]
        if not matches:
            raise ValueError(f"native source schedule is not manifest-bound: {original}")
        record = matches[0]
        if any((other["bytes"], str(other["sha256"]).upper()) !=
               (record["bytes"], str(record["sha256"]).upper()) for other in matches[1:]):
            raise ValueError(f"conflicting native source schedule identity: {original}")
        verify_record(relative, record, base_dir=run)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        frozen = file_record(target)
        if frozen["bytes"] != record["bytes"] or frozen["sha256"] != str(record["sha256"]).upper():
            raise ValueError(f"frozen native source schedule differs: {target}")
        bindings.append(dict(source=dict(record, path=str(original)), frozen=frozen))
    write_json(destination / "consumption_binding.json", dict(source_manifest=producer_manifest,
               producer_manifest=file_record(destination / "producer_manifest.json"),
               producer_status=manifest["status"], records=bindings, physical_terminal_count=len(case["terminals"])))
    return case


def _write_rows(path: Path, rows: list[dict]) -> None:
    """Write a nonempty canonical local table without changing source values."""
    if not rows:
        raise ValueError("cannot materialize an empty local source table")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _contour_source_tables(case: dict, registration: dict) -> tuple[list[dict], list[dict]]:
    """Project recorded world-frame exits by translation only, preserving all IDs."""
    from common.contracts.particle_physics import kinetic_energy_ev

    model = case["config"]
    transform = model["coordinate_transform"]
    if transform["to_frame_id"] != registration["from_frame_id"]:
        raise ValueError("registered source frame differs from recorded IP frame")
    epoch = model["baseline"]["clock"]["epoch_us"]
    mass = model["source"]["species"]["mass_amu"]
    charge = model["source"]["species"]["charge_state"]
    event_path = Path(case["run"]) / "simion/events.csv"
    identity = next(r["sha256"] for r in case["source_records"] if Path(r["path"]) == event_path)
    raw_lines = event_path.read_bytes().splitlines(keepends=True)
    parsed = list(csv.DictReader([line.decode("utf-8-sig") for line in raw_lines]))
    terminal_lines = {int(row["particle_id"]): index for index, row in enumerate(parsed, 2) if row["event"] == "terminal"}
    rows, census = [], []
    for pid, terminal in sorted(case["terminals"].items()):
        number = terminal_lines[pid]
        census.append(dict(particle_id=pid, transfer_status="transferred" if pid in case["exits"] else "not_transferred",
                           terminal_reason=terminal["reason"], instrument_time_us=epoch + float(terminal["t_us"]),
                           raw_path=str(event_path), raw_sha256=identity, raw_line_number=number,
                           raw_line_sha256=hashlib.sha256(raw_lines[number-1]).hexdigest().upper()))
        if pid not in case["exits"]:
            continue
        raw = case["exits"][pid]
        position = [float(raw[f"{axis}_mm"]) + registration["translation_mm"][index] for index, axis in enumerate("xyz")]
        velocity = [float(raw[f"v{axis}_mm_us"]) * 1000 for axis in "xyz"]
        if position[2] != 0 or velocity[2] >= 0 or float(raw["t_us"]) < model["native_timing"]["pulse_start_us"]:
            raise ValueError("registered measured exit must be z0, forward and after extraction pulse")
        row = dict(particle_id=pid, instrument_time_us=epoch + float(raw["t_us"]), mass_amu=mass,
                   charge_state=charge, frame_id=registration["to_frame_id"], kinetic_energy_eV=kinetic_energy_ev(mass, *velocity))
        row.update({f"position_{axis}_mm": position[index] for index, axis in enumerate("xyz")})
        row.update({f"velocity_{axis}_m_s": velocity[index] for index, axis in enumerate("xyz")})
        rows.append(row)
    if not rows:
        raise ValueError("no recorded exit to propagate")
    return rows, census


def _contour_geometry_and_voltage(case: dict, registration: dict, geometry: dict,
                                  inputs: Path, lua_executable: Path, repo: Path) -> tuple[dict, dict]:
    """Project exact native CSG and evaluate the unchanged sole Lua voltage schedule."""
    import copy
    from common.contracts.particle_physics import kinetic_energy_ev
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly import transform_shape
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import project_provider_voltages

    model = case["config"]
    if geometry["frame_id"] != registration["to_frame_id"]:
        raise ValueError("MR reference and registration destination frames differ")
    transform = model["coordinate_transform"]
    if transform["to_frame_id"] != registration["from_frame_id"]:
        raise ValueError("IP and registration source frames differ")
    if model["native_projection"]["frame_id"] != transform["from_frame_id"]:
        raise ValueError("native projection and coordinate transform source frames differ")
    for source_relative, current_relative in (
            ("simion/native_drive.lua", "projects/dual_pressure_rectilinear_ion_processor/simion/native_drive.lua"),
            ("simion/voltage_waveforms.lua", "common/simion/voltage_waveforms.lua")):
        if file_record(inputs / source_relative)["sha256"] != file_record(repo / current_relative)["sha256"]:
            raise ValueError("current native voltage schedule differs from frozen source schedule: " + source_relative)
    shutil.copyfile(repo / "projects/parallel_mirror_dual_stripe_mr_tof/config/ion_processor_dependency.json",
                    inputs / "accelerator_dependency.json")
    mass = model["source"]["species"]["mass_amu"]
    charge = model["source"]["species"]["charge_state"]
    if charge <= 0:
        raise ValueError("local IP voltage projection requires positive ion charge")
    measured = sum(kinetic_energy_ev(mass, 0, 0, float(row["vz_mm_us"])*1000) / charge
                   for row in case["exits"].values()) / len(case["exits"])
    request = dict(policies=dict(energy_adjustment="preserve_measured_workpoint"),
                   target=dict(axial_energy_per_charge_v=measured),
                   current_measured_baseline=dict(directional_energy=dict(z=dict(mean=measured))))
    projection = project_provider_voltages(model, request, inputs, lua_executable)
    if projection["evaluated_native_operating_point"] != model["native_operating_point"]:
        raise ValueError("local voltage projection changed source operating point")
    translation = [a+b for a, b in zip(transform["translation_mm"], registration["translation_mm"])]
    local = copy.deepcopy(geometry)
    local["ion_processor_electrodes"] = [dict(e, solids=[transform_shape(s, transform["rotation"], translation) for s in e["solids"]],
                                            cutouts=[transform_shape(s, transform["rotation"], translation) for s in e["cutouts"]])
                                         for e in model["native_projection"]["electrodes"]]
    return local, projection


def _collision_config(contract: dict, geometry: dict) -> dict:
    """Derive absorption numerics and rods from the same frozen author/CSG.

    Frozen pre-v6 contour authors and the distance workflow used native PA
    absorption; this explicit historical interpretation is never a new-author
    fallback. Active v6 authors must choose their collision representation.
    """
    model = (contract["electrode_collision_model"] if contract["schema_version"] == 6
             else "native_pa")
    return dict(electrode_collision_model=model,
                lens_electrodes=geometry.get("geometry", geometry).get("lens_electrodes", []))


def _materialize_contour_case(run: Path, repo: Path, index: int, row: dict, prepared: dict,
                              source: list[dict], census: list[dict], model: dict, contract: dict,
                              field_path: Path) -> dict:
    """Write one complete local vendor case; no solver is invoked here."""
    folder = run / "simion" / f"case_{index:02d}"
    folder.mkdir(parents=True, exist_ok=False)
    case_inputs = run / "inputs" / "cases" / row["case_id"]
    case_inputs.mkdir(parents=True, exist_ok=False)
    source_csv, census_csv = case_inputs / "source.csv", case_inputs / "source_census.csv"
    _write_rows(source_csv, source)
    _write_rows(census_csv, census)
    epoch = min(r["instrument_time_us"] for r in source)
    states, beams = [], []
    for original in source:
        state = dict(particle_id=original["particle_id"], mass_amu=original["mass_amu"], charge_state=original["charge_state"],
                     t_us=original["instrument_time_us"], x_mm=original["position_x_mm"], y_mm=original["position_y_mm"],
                     z_mm=original["position_z_mm"]+prepared["delta_z_mm"],
                     **{f"v{a}_mm_us": original[f"velocity_{a}_m_s"]/1000 for a in "xyz"})
        states.append(state)
        beams.append(dict(n=1, tob=state["t_us"]-epoch, mass=state["mass_amu"], charge=state["charge_state"],
                          x=state["x_mm"], y=state["y_mm"], z=state["z_mm"], ke=original["kinetic_energy_eV"],
                          direction=[state[f"v{a}_mm_us"] for a in "xyz"], cwf=1, color=1))
    numerics = dict(contract["numerics"], pitch_mm=row["pitch_mm"], maximum_step_us=row["maximum_step_us"])
    config = dict(numerics, case_id=row["case_id"], distance_mm=row["distance_mm"], source_epoch_us=epoch, source=states,
                  workbench_seed_path=str((run/"inputs/workbench_seed.iob").resolve()),
                  observation_planes=contract["observation_planes"], nominal_y_mm=prepared["geometry_checks"]["nominal_y_mm"],
                  exit_z_mm=prepared["exit_z_mm"], field_case_id=row["field_case_id"], field_path=str(field_path),
                  **_collision_config(contract, prepared))
    (folder/"case_config.lua").write_text("return "+lua_literal(config)+"\n", encoding="utf-8", newline="\n")
    (folder/"field.gem").write_text(prepared.pop("gem"), encoding="utf-8", newline="\n")
    write_json(folder/"geometry.json", prepared)
    write_json(folder/"source_states.json", states)
    (folder/"local.fly2").write_text(render_standard_beams(beams), encoding="utf-8", newline="\n")
    for original, target in (("ip_prism_local.lua", "local.lua"), ("run_ip_prism_local_case.lua", "run_case.lua"), ("ip_prism_lens_contact.lua", "lens_contact.lua")):
        shutil.copyfile(repo/"projects/parallel_mirror_dual_stripe_mr_tof/simion"/original, folder/target)
    return dict(row, directory=str(folder), script=str(folder/"run_case.lua"), exit_z_mm=prepared["exit_z_mm"],
                delta_z_mm=prepared["delta_z_mm"], gap_mm=prepared["gap_mm"], source_count=len(source), mother_count=len(census),
                sample_interval_us=numerics["sample_interval_us"], source_epoch_us=epoch,
                mass_u=model["source"]["species"]["mass_amu"], charge_state=model["source"]["species"]["charge_state"],
                pulse_time_us=model["baseline"]["clock"]["epoch_us"]+model["native_timing"]["pulse_start_us"],
                source_csv=str(source_csv), source_census_csv=str(census_csv), field_path=str(field_path),
                field_node_count=math.prod(prepared["geometry_checks"]["grid_dimensions"]))


def _freeze_completed_field_source(owner: Path, field_id: str, destination: Path) -> dict:
    """Consume a manifest-bound completed field stage, retaining failed run status.

    Overall success is deliberately not a field qualification. The exact local
    field identity and complete finite/range result qualify this payload only.
    """
    from common.contracts.verify_run_manifest import record_path, verify_record
    from common.contracts.write_run_manifest import require_completed_terminal_publication

    owner = owner.resolve()
    require_completed_terminal_publication(owner/"run_manifest.json")
    manifest = read_json(owner/"run_manifest.json")
    if (manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
            or manifest.get("status") not in {"success", "failed"}):
        raise ValueError("field reuse requires a terminal successful or failed local producer")
    destination.mkdir(parents=True, exist_ok=False)
    records = [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]
    bindings = []
    def freeze(path: Path) -> Path:
        path = path.resolve()
        if owner not in path.parents:
            raise ValueError("field stage input escapes producer")
        matches = [r for r in records if record_path(r, base_dir=owner) == path]
        if not matches:
            raise ValueError(f"field stage input is not manifest-bound: {path}")
        identity = {(r["bytes"],str(r["sha256"]).upper()) for r in matches}
        if len(identity) != 1:
            raise ValueError("conflicting completed field input identity")
        verify_record("completed field source", matches[0], base_dir=owner)
        target = destination/path.relative_to(owner)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        frozen = file_record(target)
        if (frozen["bytes"],frozen["sha256"]) != next(iter(identity)):
            raise ValueError("frozen completed field source differs")
        bindings.append(dict(source=dict(matches[0],path=str(path)),frozen=frozen))
        return target
    freeze(owner/"run_config.json")
    resolved = read_json(freeze(owner/"inputs/resolved_study.json"))
    if resolved["role"] != "resolved_ip_prism_contour_focus_study":
        raise ValueError("field source must be a local contour study")
    owners = resolved.get("field_owners", resolved["build_cases"])
    selected = [r for r in owners if r["field_case_id"] == field_id]
    if len(selected) != 1:
        raise ValueError("completed source field owner is not unique")
    selected = selected[0]
    geometry = read_json(freeze(Path(selected["directory"])/"geometry.json"))
    gem = freeze(Path(selected["directory"])/"field.gem")
    validation = read_json(freeze(owner/"results/pa_payload_validation.json"))
    passed = [r for r in validation["fields"] if r["field_case_id"] == field_id]
    if (validation.get("role") != "ip_prism_local_pa_payload_validation"
            or validation.get("status") != "PASS" or len(passed) != 1):
        raise ValueError("source field stage is incomplete or failed")
    passed = passed[0]
    dimensions = geometry["geometry_checks"]["grid_dimensions"]
    count = math.prod(dimensions)
    field = Path(selected["field_path"]).resolve()
    if (owner not in field.parents or count <= 0 or passed.get("role") != "simion_standalone_pa_payload_validation"
            or passed.get("status") != "PASS" or passed.get("encoded_range_valid") is not True
            or any(passed.get(k) != count for k in ("expected_nodes", "validated_nodes", "finite_nodes"))
            or passed.get("dimensions") != dimensions
            or passed.get("pitch_mm") != geometry["geometry_checks"]["pitch_mm"]
            or Path(passed["path"]).resolve() != field):
        raise ValueError("source field stage lacks complete matching finite/grid validation")
    identity = resolved["field_cases"][field_id]
    if (identity["gem_sha256"].upper() != file_record(gem)["sha256"]
            or identity["convergence_v"] != geometry["geometry_checks"]["convergence_v"]):
        raise ValueError("completed field geometry or refine identity differs")
    inventory = _replay_payload_inventory(owner, field)
    if inventory[0]["bytes"] != passed["bytes"]:
        raise ValueError("completed field payload length differs from validation")
    producer_record = file_record(owner/"run_manifest.json")
    shutil.copyfile(owner/"run_manifest.json",destination/"producer_manifest.json")
    if file_record(destination/"producer_manifest.json")["sha256"] != producer_record["sha256"]:
        raise ValueError("frozen completed field manifest differs")
    result = dict(producer_status=manifest["status"],producer_manifest=producer_record,
                  frozen_manifest=file_record(destination/"producer_manifest.json"),records=bindings,
                  field_identity=identity,source_field_path=str(field),inventory=inventory)
    write_json(destination/"field_stage_binding.json",result)
    return result


def prepare_contour_study(run: Path, contract_path: Path) -> dict:
    """Freeze B/C/D measured cohorts and exact local fields without executing SIMION."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_focus_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_field_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import standalone_pa_composition
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_mesh_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_field_theory
    from common.simion.cache_generation import materialize_direct_inventory

    assert callable(ip_prism_focus_diagnostics.analyze_focus_study)
    assert callable(ip_prism_local_field_diagnostics.export_field_diagnostics)
    assert callable(standalone_pa_composition.validate_standalone_pa_payload)
    assert callable(ip_prism_mesh_diagnostics.export_mesh_diagnostics)
    assert callable(ip_prism_field_theory.export_field_theory)
    contract = read_json(contract_path)
    validate_contour_contract(contract)
    run = run.resolve()
    repo = Path(__file__).resolve().parents[3]
    inputs = run / "inputs"
    shutil.copyfile(contract_path, inputs/"experiment_contract.json")
    refs = freeze_references(contract, inputs)
    geometry, authority = (read_json(refs[k]) for k in ("geometry", "voltages"))
    prism_voltage = authority["analyzer_electrode_voltages_v"][15]
    seed = repo/"common/simion/assets/iob_instance_seeds/1_instance_seed.iob"
    shutil.copyfile(seed, inputs/"workbench_seed.iob")
    shutil.copyfile(seed.parent/"iob_seed_placeholder_01.pa0", inputs/"iob_seed_placeholder_01.pa0")
    source_cache, fields, field_paths, pending = {}, {}, {}, []
    reused, reuse_cache, reuse_paths = {}, {}, {}
    policy = load_particle_count_policy()
    for index, row in enumerate(contract["cases"], 1):
        source_run = Path(row["source_run"]).resolve()
        if source_run not in source_cache:
            destination = inputs/"native_sources"/f"source_{len(source_cache)+1:02d}"
            case = _freeze_recorded_contour_source(source_run, row["label"], destination)
            source, census = _contour_source_tables(case, contract["source_registration"])
            if len(census) != policy["functional_check_count"]:
                raise ValueError("contour study requires the complete functional mother cohort")
            local, projection = _contour_geometry_and_voltage(case, contract["source_registration"], geometry,
                                 destination, Path(contract["plain_lua_executable"]), repo)
            source_cache[source_run] = (case, source, census, local, projection)
        case, source, census, local, projection = source_cache[source_run]
        prepared = prepare_geometry(local, projection["values_v15"], prism_voltage, row["distance_mm"],
                                   contract["numerics"]["box_mm"], row["pitch_mm"], contract["numerics"]["convergence_v"],
                                   physical_aperture=row["physical_aperture"],
                                   lens_elements=row["lens_elements"],
                                   downstream_observation_z_mm=contract["observation_planes"][-1]["z_mm"])
        if contract["observation_planes"][0]["z_mm"] >= prepared["exit_z_mm"]:
            raise ValueError("contour observation plane lies upstream of registered source")
        identity = hashlib.sha256(prepared["gem"].encode("utf-8")).hexdigest().upper()
        field_identity = dict(gem_sha256=identity, convergence_v=contract["numerics"]["convergence_v"],
                              source_native_drive_sha256=projection["source_native_drive"]["sha256"])
        if row["field_case_id"] in fields and fields[row["field_case_id"]] != field_identity:
            raise ValueError("shared field_case_id refers to different geometry, voltage or numerical field")
        fields[row["field_case_id"]] = field_identity
        field_paths.setdefault(row["field_case_id"], run/"simion"/f"case_{index:02d}"/"field.pa")
        pending.append((index, row, prepared, source, census, case["config"]))
    for field_id, identity in fields.items():
        origin = contract["field_sources"][field_id]
        if origin["action"] == "build":
            continue
        key = (str(Path(origin["source_run"]).resolve()),origin["source_field_case_id"])
        owner = Path(key[0])
        if owner == run or owner in run.parents or run in owner.parents:
            raise ValueError("reused field producer must be independent of the new run")
        if key not in reuse_cache:
            reuse_cache[key] = _freeze_completed_field_source(owner,key[1],inputs/"field_sources"/f"field_{len(reuse_cache)+1:02d}")
        source_field = reuse_cache[key]
        if source_field["field_identity"] != identity:
            raise ValueError("reused field geometry, voltage, grid or convergence differs from compiled case")
        reused[field_id] = source_field
        # A private inventory directory keeps every associated surface adjacent.
        reuse_paths.setdefault(key,field_paths[field_id].parent/"field"/Path(source_field["source_field_path"]).name)
        field_paths[field_id] = reuse_paths[key]
    cases = [_materialize_contour_case(run, repo, index, row, prepared, source, census, model, contract,
                                     field_paths[row["field_case_id"]])
             for index, row, prepared, source, census, model in pending]
    build_owners = {}
    for case in cases:
        build_owners.setdefault(case["field_case_id"], case)
    # A coarse first case cannot measure the larger PA's memory requirement.
    # Separate execution order leaves the declared scientific case table intact.
    flight_cases=sorted(cases,key=lambda c:c["field_node_count"],reverse=True)
    field_owners=sorted(build_owners.values(),key=lambda c:c["field_node_count"],reverse=True)
    build_cases=[c for c in field_owners if contract["field_sources"][c["field_case_id"]]["action"] == "build"]
    resolved = dict(schema_version=1, role="resolved_ip_prism_contour_focus_study", contract=contract,
                    numerics=contract["numerics"], cases=cases, build_cases=build_cases, field_owners=field_owners, flight_cases=flight_cases,
                    dispatch_policy=dict(work_item_order="descending_field_node_count",first_formal_observation="wait_for_natural_completion"),
                    field_cases=fields, particle_count_policy=policy,
                    committed_new_bytes=contract["committed_new_bytes"],
                    prism_voltage_v=prism_voltage, gui_executed=False, full_analyzer_flight_executed=False)
    write_json(inputs/"resolved_study.json", resolved)
    request = dict(solver="SIMION", field_kind="electrostatic", work_item_count=len(cases), independent_work_items=True,
                   frontend_grid_profile_id="ip_p1_local_static", frontend_cell_mm_xyz=flight_cases[0]["pitch_mm"],
                   trajectory_quality=contract["numerics"]["trajectory_quality"], trajectory_quality_profile_id="local_exit_cohort",
                   time_integration_profile_id="bounded_static_maximum_step", workload_topology_id="shared_ordinary_static_local_field_fly_only",
                   field_loading_policy_id="shared_readonly_ordinary_local_field_per_process",
                   case_input_sha256=hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest().upper())
    resource_scheduler.plan_simion_dispatch(request, [])
    write_json(inputs/"simion_dispatch_request.json", request)
    if build_cases:
        build_request = dict(request, work_item_count=len(build_cases),frontend_cell_mm_xyz=build_cases[0]["pitch_mm"],
                             workload_topology_id="one_local_static_refine_per_unique_field",
                             field_loading_policy_id="one_ordinary_static_pa_per_field_owner")
        resource_scheduler.plan_simion_dispatch(build_request, [])
        write_json(inputs/"simion_build_dispatch_request.json", build_request)
    freeze_code(repo, inputs)
    config = read_json(run/"run_config.json")
    config["inputs"] = {str(p.relative_to(run)): str(p) for root in (inputs, run/"simion") for p in root.rglob("*") if p.is_file()}
    config["parameters"] = dict(workflow="ip_prism_contour_focus_study", claim=contract["claim"],
                                gui_executed=False, full_analyzer_flight_executed=False)
    write_json(run/"run_config.json", config)
    # Capacity protection is entered by the public runner before preparation.
    # Bind source metadata above, then snapshot each unique immutable inventory
    # once; large source PAs are never pre-hashed or opened for writing.
    copies, copied = [], {}
    required = sum(sum(r["bytes"] for r in item["inventory"]) for item in reuse_cache.values())
    if required and sum(p.stat().st_size for p in run.rglob("*") if p.is_file())+required > contract["committed_new_bytes"]:
        raise ValueError("reused private field inventories exceed declared capacity commitment")
    for owner in field_owners:
        field_id = owner["field_case_id"]
        if field_id not in reused:
            continue
        source_field = reused[field_id]
        key = source_field["source_field_path"]
        if key not in copied:
            target = Path(owner["field_path"]).parent
            actual = materialize_direct_inventory(Path(key).parent,target,source_field["inventory"])
            copied[key] = str(target/Path(key).name)
            copies.append(dict(field_case_id=field_id,source=source_field,destination=str(target),inventory=actual))
        elif copied[key] != owner["field_path"]:
            raise ValueError("one source field must resolve to one private payload path")
    write_json(run/"results/field_reuse_materialization.json",dict(role="ip_prism_completed_field_stage_reuse",fields=copies,
               reuse_field_count=len(reused),build_field_count=len(build_cases),source_runs_relabelled=False))
    return resolved


def validate_fields(run: Path) -> dict:
    """Validate every newly built unique ordinary field before any local Fly."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import (
        read_pa_header, validate_standalone_pa_payload,
    )

    study = read_json(run/"inputs/resolved_study.json")
    owners = study.get("field_owners", study.get("build_cases", study["cases"]))
    if not owners:
        raise ValueError("local field validation requires nonempty build cases")
    results = []
    report = dict(schema_version=1, role="ip_prism_local_pa_payload_validation", status="PASS", fields=results,
                  qualification="Full native node finite/range and declared grid validation; not field convergence")
    for case in owners:
        path = Path(case.get("field_path", str(Path(case["directory"])/"field.pa")))
        record = dict(field_case_id=case.get("field_case_id", case["case_id"]), path=str(path))
        results.append(record)
        try:
            checks = read_json(Path(case["directory"])/"geometry.json")["geometry_checks"]
            header = read_pa_header(path)
            if ([header.nx, header.ny, header.nz] != checks["grid_dimensions"] or
                    [header.dx_mm, header.dy_mm, header.dz_mm] != checks["pitch_mm"] or
                    header.symmetry != 1 or header.raw_mirror & 7 != 1):
                raise ValueError(f"local ordinary PA grid or x-mirror differs from frozen geometry: {path}")
            record.update(validate_standalone_pa_payload(path), dimensions=list(checks["grid_dimensions"]),
                          pitch_mm=list(checks["pitch_mm"]), boundary_mode=checks["boundary_mode"])
        except (OSError, ValueError, KeyError) as error:
            report.update(status="FAIL", failed_field_path=str(path), error=str(error))
            record.update(status="FAIL", error=str(error))
            write_json(run/"results/pa_payload_validation.json", report)
            raise
    write_json(run/"results/pa_payload_validation.json", report)
    return report


def prepare(run: Path, contract_path: Path) -> dict:
    """Freeze full experiment inputs and vendor projections before any solver."""
    if read_json(contract_path).get("role") == "ip_prism_recorded_aperture_comparison":
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_aperture_diagnostics import prepare_aperture_comparison
        run = run.resolve()
        result = prepare_aperture_comparison(run, contract_path)
        freeze_code(Path(__file__).resolve().parents[3], run/"inputs")
        config = read_json(run/"run_config.json")
        config["inputs"] = {str(p.relative_to(run)):str(p) for p in (run/"inputs").rglob("*") if p.is_file()}
        config["parameters"] = dict(workflow="ip_prism_recorded_aperture_comparison",
                                    new_solver_execution=False, gui_executed=False, full_analyzer_flight_executed=False)
        write_json(run/"run_config.json", config)
        if sum(p.stat().st_size for p in run.rglob("*") if p.is_file()) > result["committed_new_bytes"]:
            raise ValueError("recorded aperture observations plus frozen code exceed declared capacity commitment")
        return result
    if read_json(contract_path).get("role") == "ip_prism_local_replay_package":
        return prepare_replay_package(run, contract_path)
    if read_json(contract_path).get("role") == "ip_prism_contour_focus_experiment":
        return prepare_contour_study(run, contract_path)
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_field_diagnostics
    assert callable(ip_prism_local_diagnostics.analyze_study)
    assert callable(ip_prism_local_field_diagnostics.export_field_diagnostics)
    assert artifact_retention and run_capacity_lifecycle
    assert resource_profile.PROFILE_ROLE and resource_scheduler.RESOURCE_IDENTITY_KEYS and particle_batching
    contract=read_json(contract_path);validate_contract(contract)
    run=run.resolve();inputs=run/"inputs";repo=Path(__file__).resolve().parents[3]
    shutil.copyfile(contract_path,inputs/"experiment_contract.json")
    refs=freeze_references(contract,inputs)
    source,census=read_source(refs["component_particle_state"],refs["source_census"])
    geometry,authority,timing=[read_json(refs[k]) for k in ("geometry","voltages","native_timing")]
    masses={float(r["mass_amu"]) for r in source};charges={int(r["charge_state"]) for r in source}
    if len(masses)!=1 or len(charges)!=1:
        raise ValueError("this local metric workflow requires one species")
    policy=load_particle_count_policy()
    epoch=min(float(r["instrument_time_us"]) for r in source)
    ip_voltage=[next(v["voltage_v"] for v in authority["component_voltages_v"] if v["component_namespace"]=="ion_processor" and v["component_electrode_id"]==k) for k in range(1,16)]
    prism_voltage=authority["analyzer_electrode_voltages_v"][15]
    seed=repo/"common/simion/assets/iob_instance_seeds/1_instance_seed.iob"
    shutil.copyfile(seed,inputs/"workbench_seed.iob")
    shutil.copyfile(seed.parent/"iob_seed_placeholder_01.pa0",inputs/"iob_seed_placeholder_01.pa0")
    cases=[]
    for index,distance in enumerate(contract["distances_mm"],1):
        prepared=prepare_geometry(geometry,ip_voltage,prism_voltage,distance,contract["numerics"]["box_mm"],contract["numerics"]["pitch_mm"],contract["numerics"]["convergence_v"])
        folder=run/"simion"/f"case_{index:02d}";folder.mkdir(parents=True)
        if contract["observation_planes"][0]["z_mm"]>=prepared["exit_z_mm"]:
            raise ValueError("observation plane lies upstream of source")
        states=[];beams=[]
        for row in source:
            state=dict(particle_id=int(row["particle_id"]),mass_amu=float(row["mass_amu"]),charge_state=int(row["charge_state"]),
                       t_us=float(row["instrument_time_us"]),x_mm=float(row["position_x_mm"]),y_mm=float(row["position_y_mm"]),
                       z_mm=float(row["position_z_mm"])+prepared["delta_z_mm"],
                       **{a+"_mm_us":float(row["velocity_"+a[1]+"_m_s"])/1000 for a in ("vx","vy","vz")})
            states.append(state)
            beams.append(dict(n=1,tob=state["t_us"]-epoch,mass=state["mass_amu"],charge=state["charge_state"],
                              x=state["x_mm"],y=state["y_mm"],z=state["z_mm"],ke=float(row["kinetic_energy_eV"]),
                              direction=[state[k] for k in ("vx_mm_us","vy_mm_us","vz_mm_us")],cwf=1,color=1))
        config=dict(case_id=f"distance_{distance:g}mm",distance_mm=distance,source_epoch_us=epoch,source=states,
                    workbench_seed_path=str((inputs/"workbench_seed.iob").resolve()),observation_planes=contract["observation_planes"],
                    nominal_y_mm=prepared["geometry_checks"]["nominal_y_mm"],exit_z_mm=prepared["exit_z_mm"],
                    **contract["numerics"], **_collision_config(contract, prepared))
        (folder/"case_config.lua").write_text("return "+lua_literal(config)+"\n",encoding="utf-8")
        (folder/"field.gem").write_text(prepared.pop("gem"),encoding="utf-8")
        write_json(folder/"geometry.json",prepared)
        write_json(folder/"source_states.json",states)
        (folder/"local.fly2").write_text(render_standard_beams(beams),encoding="utf-8")
        for original,target in (("ip_prism_local.lua","local.lua"),("run_ip_prism_local_case.lua","run_case.lua"),("ip_prism_lens_contact.lua","lens_contact.lua")):
            shutil.copyfile(repo/"projects/parallel_mirror_dual_stripe_mr_tof/simion"/original,folder/target)
        cases.append(dict(case_id=config["case_id"],distance_mm=distance,directory=str(folder),script=str(folder/"run_case.lua"),
                          exit_z_mm=prepared["exit_z_mm"],delta_z_mm=prepared["delta_z_mm"],gap_mm=prepared["gap_mm"]))
    resolved=dict(schema_version=1,role="resolved_ip_prism_distance_study",contract=contract,cases=cases,
                  source_epoch_us=epoch,pulse_time_us=timing["pulse_start_us"],mother_particle_count=len(census),source_count=len(source),
                  mass_u=masses.pop(),charge_state=charges.pop(),committed_new_bytes=contract["committed_new_bytes"],limits=contract["limits"],
                  particle_count_policy=policy,prism_voltage_v=prism_voltage,gui_executed=False,full_analyzer_flight_executed=False)
    write_json(inputs/"resolved_study.json",resolved)
    request=dict(solver="SIMION",field_kind="electrostatic",work_item_count=len(cases),independent_work_items=True,
                 frontend_grid_profile_id="ip_p1_local_static",frontend_cell_mm_xyz=contract["numerics"]["pitch_mm"],
                 trajectory_quality=contract["numerics"]["trajectory_quality"],trajectory_quality_profile_id="local_exit_cohort",
                 time_integration_profile_id="bounded_static_maximum_step",workload_topology_id="single_ordinary_pa_local_ip_p1_refine_and_fly",
                 field_loading_policy_id="one_ordinary_static_pa_per_complete_case",
                 case_input_sha256=hashlib.sha256(json.dumps(resolved,sort_keys=True).encode()).hexdigest().upper())
    resource_scheduler.plan_simion_dispatch(request,[])
    write_json(inputs/"simion_dispatch_request.json",request)
    freeze_code(repo,inputs)
    config=read_json(run/"run_config.json")
    config["inputs"]={str(path.relative_to(run)).replace("/","_"):str(path) for root in (inputs,run/"simion") for path in root.rglob("*") if path.is_file()}
    config["parameters"]={"workflow":"ip_prism_distance_study","claim":contract["claim"],"gui_executed":False,"full_analyzer_flight_executed":False}
    write_json(run/"run_config.json",config)
    return resolved


def validate_replay_contract(contract: dict) -> None:
    """Require explicit source selection and execution-only GUI policy."""
    if (set(contract) != {"schema_version", "role", "cases", "frontend", "committed_new_bytes", "scope"}
            or contract["schema_version"] != 1 or contract["role"] != "ip_prism_local_replay_package"):
        raise ValueError("unsupported local replay package contract")
    if (contract["frontend"] != dict(schema_version=1, role="ip_prism_local_frontend", trajectory_image_control=0)
            or type(contract["frontend"]["schema_version"]) is not int
            or type(contract["frontend"]["trajectory_image_control"]) is not int):
        raise ValueError("GUI replay requires explicit View/Retain control 0")
    cases = contract["cases"]
    if (not isinstance(cases, list) or not cases or any(set(c) != {"source_run", "case_id"} for c in cases)
            or any(not isinstance(c[k], str) or not c[k] for c in cases for k in ("source_run", "case_id"))
            or len({c["case_id"] for c in cases}) != len(cases)):
        raise ValueError("explicit unique replay case IDs required; duplicate IDs collide in delivery")
    if (isinstance(contract["committed_new_bytes"], bool) or not isinstance(contract["committed_new_bytes"], int)
            or contract["committed_new_bytes"] <= 0
            or not isinstance(contract["scope"], str) or not contract["scope"]):
        raise ValueError("positive capacity commitment and delivery scope required")


def _replay_payload_inventory(owner: Path, field: Path) -> list[dict]:
    """Locate exact manifest-bound PA/surface; snapshot checks their copied bytes."""
    from common.contracts.verify_run_manifest import record_path

    manifest = read_json(owner/"run_manifest.json")
    records = [*manifest["inputs"].values(), *manifest["outputs"]]
    inventory = []
    for path in (field, Path(str(field)+"-surf")):
        matches = [r for r in records if record_path(r, base_dir=owner) == path.resolve()]
        if not matches:
            if path == field or path.exists():
                raise ValueError(f"replay payload is not manifest-bound: {path}")
            continue
        identity = {(r["bytes"], r["sha256"].upper()) for r in matches}
        if len(identity) != 1 or not path.is_file() or path.stat().st_size != matches[0]["bytes"]:
            raise ValueError(f"conflicting or missing replay payload: {path}")
        inventory.append(dict(name=path.name, bytes=matches[0]["bytes"], sha256=matches[0]["sha256"].upper()))
    return inventory


def prepare_replay_package(run: Path, contract_path: Path) -> dict:
    """Create writable private fields and companions; never refine or fly sources.

    The public runner enters its capacity session before this materialization.
    Large-file identity is checked by the common immutable snapshot primitive.
    """
    from common.contracts.write_run_manifest import require_completed_terminal_publication
    from common.simion.cache_generation import materialize_direct_inventory
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_focus_diagnostics import contour_projection_paths

    contract = read_json(contract_path)
    validate_replay_contract(contract)
    run = run.resolve()
    inputs = run/"inputs"
    repo = Path(__file__).resolve().parents[3]
    shutil.copyfile(contract_path, inputs/"experiment_contract.json")
    pending, bindings = [], []
    native_stages = {}
    for index, selection in enumerate(contract["cases"], 1):
        owner = Path(selection["source_run"]).resolve()
        if owner == run or owner in run.parents or run in owner.parents:
            raise ValueError("replay delivery must be independent of scientific source directories")
        require_completed_terminal_publication(owner/"run_manifest.json")
        if owner not in native_stages:
            native_stages[owner] = _completed_native_stage(owner)
        resolved, stage_records, stage_qualification, _, reference = native_stages[owner]
        if resolved["role"] != "resolved_ip_prism_contour_focus_study":
            raise ValueError("replay requires a completed contour producer")
        matches = [c for c in resolved["cases"] if c["case_id"] == selection["case_id"]]
        if len(matches) != 1:
            raise ValueError("replay selection does not identify exactly one source case")
        case = matches[0]
        directory = Path(case["directory"])
        field = Path(case["field_path"])
        if owner not in directory.resolve().parents or owner not in field.resolve().parents:
            raise ValueError("replay case/field lies outside its producer")
        evidence = [owner/"inputs/resolved_study.json", owner/"summary.json", directory/"geometry.json",
                    directory/"source_states.json", directory/"case_config.lua", directory/"local.fly2",
                    Path(case["source_csv"]), Path(case["source_census_csv"]),
                    *contour_projection_paths(resolved).values(), *map(Path, stage_records)]
        frozen = inputs/"replay_sources"/f"source_{index:02d}"
        frozen.mkdir(parents=True)
        records = []
        for source in dict.fromkeys(evidence):
            source = reference(source.relative_to(owner).as_posix())
            target = frozen/source.relative_to(owner)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            identity = file_record(source)
            if file_record(target)["sha256"] != identity["sha256"]:
                raise ValueError("frozen replay evidence differs")
            records.append(dict(source=identity, frozen=file_record(target)))
        manifest_identity = file_record(owner/"run_manifest.json")
        shutil.copyfile(owner/"run_manifest.json", frozen/"producer_manifest.json")
        if file_record(frozen/"producer_manifest.json")["sha256"] != manifest_identity["sha256"]:
            raise ValueError("frozen replay producer manifest differs")
        if stage_qualification is None and read_json(frozen/"summary.json")["status"] != "success":
            raise ValueError("replay source summary must be successful")
        source, census = read_source(Path(case["source_csv"]), Path(case["source_census_csv"]))
        states = read_json(directory/"source_states.json")
        if (len(census) != load_particle_count_policy()["functional_check_count"] or len(census) != case["mother_count"] or len(source) != case["source_count"]
                or len(states) != len(source) or {s["particle_id"] for s in states} != {int(s["particle_id"]) for s in source}):
            raise ValueError("replay mother/actual exit census does not close")
        by_id = {int(s["particle_id"]): s for s in source}
        for state in states:
            raw = by_id[state["particle_id"]]
            expected = dict(particle_id=int(raw["particle_id"]), mass_amu=float(raw["mass_amu"]), charge_state=int(raw["charge_state"]),
                            t_us=float(raw["instrument_time_us"]), **{f"{a}_mm":float(raw[f"position_{a}_mm"])+(case["delta_z_mm"] if a == "z" else 0) for a in "xyz"},
                            **{f"v{a}_mm_us":float(raw[f"velocity_{a}_m_s"])/1000 for a in "xyz"})
            if state != expected:
                raise ValueError("saved replay state differs from measured exit/clock")
        inventory = _replay_payload_inventory(owner, field)
        bindings.append(dict(source_run=str(owner), case_id=case["case_id"], producer_manifest=file_record(frozen/"producer_manifest.json"),
                             consumed_records=records, stage_qualification=stage_qualification,
                             producer_status=read_json(owner/"run_manifest.json")["status"],
                             payload_source=str(field.parent), payload_inventory=inventory))
        pending.append((case, resolved, directory, field, inventory, states))
    seed = repo/"common/simion/assets/iob_instance_seeds/1_instance_seed.iob"
    for original, target in ((seed, inputs/"workbench_seed.iob"), (seed.parent/"iob_seed_placeholder_01.pa0", inputs/"iob_seed_placeholder_01.pa0")):
        shutil.copyfile(original, target)
    cases = []
    for index, (case, resolved, directory, field, inventory, states) in enumerate(pending, 1):
        folder = run/"simion"/f"case_{index:02d}"
        folder.mkdir(parents=True)
        for name in ("geometry.json", "source_states.json", "local.fly2"):
            shutil.copyfile(directory/name, folder/name)
        for original, target in (("ip_prism_local.lua", "local.lua"), ("run_ip_prism_local_case.lua", "run_case.lua"), ("ip_prism_lens_contact.lua", "lens_contact.lua")):
            shutil.copyfile(repo/"projects/parallel_mirror_dual_stripe_mr_tof/simion"/original, folder/target)
        private_field = folder/"field"/field.name
        geometry = read_json(folder/"geometry.json")
        config = dict(resolved["numerics"], pitch_mm=case["pitch_mm"], maximum_step_us=case["maximum_step_us"],
                      case_id=case["case_id"], distance_mm=case["distance_mm"], source_epoch_us=case["source_epoch_us"], source=states,
                      workbench_seed_path=str(inputs/"workbench_seed.iob"), observation_planes=resolved["contract"]["observation_planes"],
                      nominal_y_mm=geometry["geometry_checks"]["nominal_y_mm"], exit_z_mm=case["exit_z_mm"],
                      field_case_id=case["field_case_id"], field_path=str(private_field), frontend=contract["frontend"],
                      **_collision_config(resolved["contract"], geometry))
        (folder/"case_config.lua").write_text("return "+lua_literal(config)+"\n", encoding="utf-8", newline="\n")
        cases.append(dict(case, directory=str(folder), script=str(folder/"run_case.lua"), field_path=str(private_field),
                          source_run=str(directory.parent.parent), source_case_directory=str(directory),
                          field_node_count=math.prod(geometry["geometry_checks"]["grid_dimensions"])))
    write_json(inputs/"replay_source_binding.json", dict(role="ip_prism_local_replay_source_binding", sources=bindings))
    frozen = dict(schema_version=1, role="resolved_ip_prism_local_replay_package", contract=contract, cases=cases,
                  assembly_cases=sorted(cases, key=lambda c:c["field_node_count"], reverse=True),
                  dispatch_policy=dict(work_item_order="descending_field_node_count", first_formal_observation="wait_for_natural_completion"),
                  committed_new_bytes=contract["committed_new_bytes"],
                  gui_executed=False, refine_executed=False, fly_executed=False, default_replay_verification="pending")
    write_json(inputs/"resolved_study.json", frozen)
    first = frozen["assembly_cases"][0]
    request = dict(solver="SIMION", field_kind="electrostatic", work_item_count=len(cases), independent_work_items=True,
                   frontend_grid_profile_id="ip_p1_local_static", frontend_cell_mm_xyz=first["pitch_mm"],
                   trajectory_quality=pending[0][1]["numerics"]["trajectory_quality"], trajectory_quality_profile_id="local_exit_cohort",
                   time_integration_profile_id="bounded_static_maximum_step", workload_topology_id="private_local_workbench_assembly_only",
                   field_loading_policy_id="private_ordinary_static_pa_assembly_without_refine_or_fly",
                   case_input_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest().upper())
    resource_scheduler.plan_simion_dispatch(request, [])
    write_json(inputs/"simion_dispatch_request.json", request)
    companions = [file_record(p) for case in cases for p in Path(case["directory"]).iterdir() if p.is_file()]
    write_json(inputs/"replay_companion_identity.json", dict(records=companions))
    freeze_code(repo, inputs)
    payload_bytes = sum(r["bytes"] for item in pending for r in item[4])
    current_bytes = sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
    if current_bytes+payload_bytes > contract["committed_new_bytes"]:
        raise ValueError("private PA payload plus measured preparation exceeds declared capacity commitment")
    write_json(inputs/"replay_capacity_projection.json", dict(payload_bytes=payload_bytes, measured_preparation_bytes=current_bytes,
               available_preparation_room_bytes=contract["committed_new_bytes"]-payload_bytes))
    config = read_json(run/"run_config.json")
    config["inputs"] = {str(p.relative_to(run)):str(p) for root in (inputs, run/"simion") for p in root.rglob("*") if p.is_file()}
    config["parameters"] = dict(workflow="ip_prism_local_replay_package", scope=contract["scope"], gui_executed=False, refine_executed=False, fly_executed=False)
    write_json(run/"run_config.json", config)
    copies = []
    for case, item in zip(cases, pending):
        remaining = sum(r["bytes"] for r in item[4])
        if sum(p.stat().st_size for p in run.rglob("*") if p.is_file())+remaining > contract["committed_new_bytes"]:
            raise ValueError("private PA copy exceeds declared capacity commitment")
        actual = materialize_direct_inventory(item[3].parent, Path(case["field_path"]).parent, item[4])
        copies.append(dict(case_id=case["case_id"], destination=str(Path(case["field_path"]).parent), inventory=actual))
    write_json(run/"results/private_field_materialization.json", dict(role="ip_prism_private_field_materialization", cases=copies,
               proof="Manifest length and copied destination SHA-256; immutable source opened only for reading; no hardlinks"))
    return frozen


def analyze_replay_package(run: Path) -> dict:
    """Report assembled private workbenches without claiming replay validation."""
    study = read_json(run/"inputs/resolved_study.json")
    from common.contracts.verify_run_manifest import verify_record
    for record in read_json(run/"inputs/replay_companion_identity.json")["records"]:
        verify_record("preserved replay companion", record)
    for case in study["cases"]:
        folder = Path(case["directory"])
        for name in ("local.iob", "local.lua", "local.fly2", "source_states.json", "source_occupancy.csv", "axis_field.csv"):
            if not (folder/name).is_file():
                raise ValueError(f"assembled replay companion missing: {folder/name}")
        if (folder/"events.csv").exists() or (folder/"samples.csv").exists():
            raise ValueError("assembly-only delivery unexpectedly contains Fly output")
        with (folder/"source_occupancy.csv").open(encoding="utf-8-sig", newline="") as handle:
            occupancy = list(csv.DictReader(handle))
        expected = {s["particle_id"] for s in read_json(folder/"source_states.json")}
        if (len(occupancy) != len(expected) or {int(r["particle_id"]) for r in occupancy} != expected
                or any(r["electrode"] != "0" for r in occupancy)):
            raise ValueError("assembled replay source occupancy does not close in vacuum")
    result = dict(schema_version=1, role="ip_prism_local_replay_package_summary", status="success", cases=study["cases"],
                  gui_executed=False, refine_executed=False, fly_executed=False, default_replay_verification="pending")
    write_json(run/"summary.json", result)
    return result


def publish_manifest(run: Path,status: str) -> None:
    config=read_json(run/"run_config.json")
    frozen={Path(p).resolve() for p in config["inputs"].values()}
    outputs=[p for p in run.rglob("*") if p.is_file() and p.resolve() not in frozen and p.name not in {"run_config.json","run_manifest.json",".run_terminal_publication.lock"}]
    publish_run_manifest(run/"run_config.json",status,software=["SIMION 2020","Python 3.11"],output_paths=outputs)


def _completed_native_stage(source_run: Path):
    """Load one local producer's qualified observations, preserving failed status.

    Both recorded analysis and private GUI delivery consume this same narrow
    qualification. The returned reference reader verifies additional exact
    manifest records without changing the shared success-only verifier.
    """
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_focus_diagnostics
    source_run=source_run.resolve()
    consumed={}
    manifest=read_json(source_run/"run_manifest.json")
    failed_native=manifest.get("status")=="failed"

    def reference(relative: str) -> Path:
        if not failed_native:
            return verified_reference(source_run, relative)
        from common.contracts.verify_run_manifest import record_path, verify_record
        desired=(source_run/relative).resolve()
        desired.relative_to(source_run)
        records=[*manifest.get("inputs",{}).values(), *manifest.get("outputs",[])]
        matches=[r for r in records if record_path(r,base_dir=source_run)==desired]
        if not matches:
            raise ValueError("Failed native producer does not bind "+relative)
        for record in matches:
            verify_record("completed native stage observation",record,base_dir=source_run)
        return desired

    stage_receipt=None
    if failed_native:
        from common.contracts.verify_run_manifest import record_path, verify_record
        project="parallel_mirror_dual_stripe_mr_tof"
        if manifest.get("project")!=project or record_path(manifest["run_config"],base_dir=source_run)!=(source_run/"run_config.json"):
            raise ValueError("Failed native producer project/config binding mismatch")
        verify_record("failed native producer config",manifest["run_config"],base_dir=source_run)
        producer_config=read_json(source_run/"run_config.json")
        if (producer_config.get("project")!=project or producer_config.get("run_id")!=source_run.name
                or manifest.get("run_id")!=source_run.name):
            raise ValueError("Failed native producer run identity mismatch")
        summary_path=reference("summary.json")
        summary=read_json(summary_path)
        if (summary.get("status")!="failed" or summary.get("stage")!="automatic_local_diagnostics"
                or summary.get("role")!="ip_prism_distance_study_summary"):
            raise ValueError("Failed native producer did not complete the native stage")
        consumed[str(summary_path)]=file_record(summary_path)
    source=reference("inputs/resolved_study.json")
    resolved=read_json(source)
    if resolved["role"] not in {"resolved_ip_prism_distance_study", "resolved_ip_prism_contour_focus_study"}:
        raise ValueError("unsupported recorded local study role")
    contour=resolved["role"]=="resolved_ip_prism_contour_focus_study"
    rebound=False
    for case in resolved["cases"]:
        for key in ("directory", "source_csv", "source_census_csv"):
            if key in case and not Path(case[key]).is_absolute():
                case[key]=str((source_run/case[key]).resolve())
                rebound=True
    if failed_native:
        if not contour:
            raise ValueError("Failed native stage consumption requires a contour study")
        usage_path=reference("results/simion_batch_resource_usage.json")
        usage=read_json(usage_path)
        count=usage.get("execution_wave",{}).get("process_count",0)
        if (usage.get("role")!="multipole_resource_usage" or usage.get("status")!="completed"
                or "failure_class" not in usage or usage["failure_class"] is not None
                or not isinstance(count,int) or count<1):
            raise ValueError("Failed producer lacks completed native resource evidence")
        consumed[str(usage_path)]=file_record(usage_path)
        from common.contracts.verify_run_manifest import record_path
        logs=sorted({record_path(r,base_dir=source_run) for r in manifest.get("outputs",[])
                     if record_path(r,base_dir=source_run).parent==source_run/"logs"
                     and record_path(r,base_dir=source_run).name.startswith("fly_batch_")
                     and record_path(r,base_dir=source_run).suffix==".log"
                     and not record_path(r,base_dir=source_run).name.endswith(".stderr.log")})
        if len(logs)!=count:
            raise ValueError("Completed native process/log coverage mismatch")
        markers=[]
        for path in logs:
            reference(path.relative_to(source_run).as_posix())
            consumed[str(path)]=file_record(path)
            markers.extend(line.split()[1] for line in path.read_text(encoding="utf-8-sig").splitlines()
                           if line.startswith("IP_PRISM_CASE=PASS ") and line.endswith(" stage=fly"))
        expected=[case["case_id"] for case in resolved["cases"]]
        if len(set(expected))!=len(expected) or sorted(markers)!=sorted(expected):
            raise ValueError("Completed native case coverage mismatch")
        stage_receipt=dict(producer_status="failed",failed_stage="automatic_local_diagnostics",
                           native_completion_basis="bound completed resource receipt and unique fly PASS markers; no invented exit-code records",
                           declared_case_ids=expected,process_count=count,cohort_closure=[])
    if failed_native:
        for case in resolved["cases"]:
            for path in (Path(case["directory"])/"events.csv", Path(case["source_csv"]), Path(case["source_census_csv"])):
                reference(path.relative_to(source_run).as_posix())
                consumed[str(path)]=file_record(path)
            cohort=ip_prism_focus_diagnostics._load_case_events(source_run,case,resolved["contract"]["observation_planes"])
            stage_receipt["cohort_closure"].append(dict(case_id=case["case_id"],
                source_count=len(cohort["births"]),terminal_count=len(cohort["terminals"]),
                mother_count=len(cohort["census"])))
    return resolved, consumed, stage_receipt, rebound, reference


def prepare_recorded_analysis(run: Path, source_run: Path, contract_path: Path | None = None) -> None:
    """Freeze exact completed case observations for analysis without another Fly."""
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_field_diagnostics
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_focus_diagnostics
    assert callable(ip_prism_local_diagnostics.analyze_study)
    assert callable(ip_prism_local_field_diagnostics.export_field_diagnostics)
    assert callable(ip_prism_focus_diagnostics.analyze_focus_study)
    run,source_run=run.resolve(),source_run.resolve()
    inputs=run/"inputs"
    resolved,consumed,stage_receipt,rebound,reference=_completed_native_stage(source_run)
    contour=resolved["role"]=="resolved_ip_prism_contour_focus_study"
    names=("resolved_study.json",) if contour else ("resolved_study.json","component_particle_state.csv","source_census.csv")
    for name in names:
        source=reference("inputs/"+name)
        shutil.copyfile(source,inputs/name)
        consumed[str(source)]=file_record(source)
    for case in resolved["cases"]:
        for name in ("events.csv","samples.csv","axis_field.csv","geometry.json","source_occupancy.csv"):
            source=Path(case["directory"])/name
            relative=source.relative_to(source_run).as_posix()
            reference(relative)
            consumed[str(source)]=file_record(source)
        if contour:
            for name in ("source_csv", "source_census_csv"):
                source=Path(case[name])
                relative=source.relative_to(source_run).as_posix()
                reference(relative)
                consumed[str(source)]=file_record(source)
    if contour:
        for source in ip_prism_focus_diagnostics.contour_projection_paths(resolved).values():
            reference(source.relative_to(source_run).as_posix())
            consumed[str(source)]=file_record(source)
    if rebound:
        shutil.copyfile(source_run/"inputs/resolved_study.json",inputs/"native_resolved_study.json")
        write_json(inputs/"resolved_study.json",resolved)
    if contract_path is not None:
        if not contour:
            raise ValueError("analysis selection override requires a contour study")
        replacement=read_json(contract_path)
        validate_contour_contract(replacement, recorded_author=True)
        immutable=lambda c: {k:v for k,v in c.items() if k not in {"aperture_comparison", "claim"}}
        if immutable(replacement)!=immutable(resolved["contract"]):
            raise ValueError("recorded analysis may change only aperture comparison and claim; physical/numerical inputs must remain identical")
        shutil.copyfile(source_run/"inputs/resolved_study.json",inputs/"native_resolved_study.json")
        shutil.copyfile(contract_path,inputs/"analysis_contract.json")
        resolved["contract"]=replacement
        write_json(inputs/"resolved_study.json",resolved)
    write_json(inputs/"recorded_source_binding.json",dict(producer_manifest=file_record(source_run/"run_manifest.json"),
        consumed_records=consumed,stage_qualification=stage_receipt,scope="Path-bound small native observations only; no PA reread or new Fly"))
    freeze_code(Path(__file__).resolve().parents[3],inputs)
    config=read_json(run/"run_config.json")
    config["inputs"]={str(p.relative_to(run)):str(p) for p in inputs.rglob("*") if p.is_file()}
    config["inputs"].update({"native_record_"+str(k):p for k,p in enumerate(consumed)})
    config["parameters"]={"workflow":"ip_prism_contour_recorded_analysis" if contour else "ip_prism_distance_recorded_analysis","source_run":str(source_run),
                          "new_solver_execution":False,"gui_executed":False,"full_analyzer_flight_executed":False}
    if contract_path is not None:
        config["parameters"]["analysis_override_scope"]="Explicit virtual selector contract only; native resolved input retained, all physical and numerical fields unchanged"
    write_json(run/"run_config.json",config)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=("prepare","prepare-recorded-analysis","validate-fields","analyze","publish-manifest"))
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--contract",type=Path)
    parser.add_argument("--status",choices=("success","failed"))
    parser.add_argument("--source-run",type=Path)
    args=parser.parse_args()
    if args.operation=="prepare":
        if args.contract is None: parser.error("prepare requires --contract")
        prepare(args.run,args.contract)
    elif args.operation=="prepare-recorded-analysis":
        if args.source_run is None: parser.error("recorded analysis requires --source-run")
        prepare_recorded_analysis(args.run,args.source_run,args.contract)
    elif args.operation=="validate-fields":
        validate_fields(args.run)
        if read_json(args.run/"inputs/resolved_study.json")["role"] == "resolved_ip_prism_contour_focus_study":
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_mesh_diagnostics import export_mesh_diagnostics
            export_mesh_diagnostics(args.run)
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_field_theory import export_field_theory
            export_field_theory(args.run)
    elif args.operation=="analyze":
        if read_json(args.run/"inputs/resolved_study.json")["role"] == "resolved_ip_prism_recorded_aperture_comparison":
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_aperture_diagnostics import analyze_aperture_comparison
            result = analyze_aperture_comparison(args.run)
            write_json(args.run/"summary.json", dict(result, status="success", gui_executed=False,
                                                     full_analyzer_flight_executed=False, new_solver_execution=False))
            return
        if read_json(args.run/"inputs/resolved_study.json")["role"] == "resolved_ip_prism_local_replay_package":
            analyze_replay_package(args.run)
            return
        if read_json(args.run/"inputs/resolved_study.json")["role"] == "resolved_ip_prism_contour_focus_study":
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_focus_diagnostics import analyze_focus_study
            result = analyze_focus_study(args.run)
            write_json(args.run/"summary.json", dict(result, status="success", role="ip_prism_contour_focus_study_summary",
                                                     gui_executed=False, full_analyzer_flight_executed=False))
            return
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_diagnostics import analyze_study
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_field_diagnostics import export_field_diagnostics
        result=analyze_study(args.run)
        export_field_diagnostics(args.run)
        write_json(args.run/"summary.json",dict(result,status="success",role="ip_prism_distance_study_summary",gui_executed=False,full_analyzer_flight_executed=False))
    else:
        if args.status is None: parser.error("publish-manifest requires --status")
        publish_manifest(args.run,args.status)


if __name__=="__main__":
    main()
