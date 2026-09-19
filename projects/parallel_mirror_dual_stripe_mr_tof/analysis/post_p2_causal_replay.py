"""Materialize and assess a conditional post-P2 causal replay.

The source cohort is exactly the detector-hit cohort from one complete N>1
flight.  No source or peak filtering is performed after replay: every replay
particle must end in a terminal event and collisions/timeouts remain outcomes.
This is a conditional diagnostic, not a transmission or resolution result.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.simion.particle_source import render_standard_beams
from common.simion.operating_pa_cache import (
    CacheDisposition,
    probe_operating_pa_cache,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    EVENT,
    FIELD,
    FLY_COMPLETED,
    _fwhm,
    parse_events,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic import (
    _event_batches,
    _load_object,
    _load_selected_events,
    _load_source_rows,
    _one,
    _verify_manifest,
)

_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "finite_3d_two_prism_voltage_trial"
_CASES = ("original", "vz_dechirp")
_BRANCHES = ("mechanical_detector", "transparent_planes")
_LOCAL_PA_NAMES = (
    "local_negative_mirror.pa0",
    "local_negative_bridge.pa0",
    "local_central.pa0",
    "local_positive_bridge.pa0",
    "local_positive_mirror.pa0",
)
_BRIDGE_PLANE = "handoff_positive_bridge_to_mirror__z_plane"


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path).lower(),
    }


def _unique_manifest_output(manifest: Mapping[str, Any], path: Path, label: str) -> None:
    resolved = path.resolve()
    matches = [
        item for item in manifest.get("outputs", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
        and Path(item["path"]).resolve() == resolved
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"{label} is not one immutable manifest output")
    try:
        verify_record(label, matches[0])
    except (AssertionError, TypeError) as error:
        raise CandidateContractError(f"{label} failed byte-identity verification") from error


def resolve_immutable_operating_bundle(
    *, run_dir: Path, manifest: Mapping[str, Any],
    operating_cache_identity_path: Path | None = None,
    operating_cache_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve the exact retained 0.25-mm PA/IOB inputs without rebuilding them."""
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("flight manifest inputs are missing")
    required = (
        "local_workbench_run_manifest", "read_only_analyzer_pa",
        "read_only_accelerator_pa", "read_only_detector_pa", "iob_builder",
        "iob_seed", "local_refinement_sidecar", "trial_materialization",
        "batch_iob_bundle_portability_receipt", "voltage_map",
        "mirror_cycle_counter", "flight_launcher",
    )
    try:
        paths = {
            key: record_path(inputs[key], base_dir=run_dir)
            for key in required
        }
        for key in required:
            verify_record(key, inputs[key], base_dir=run_dir)
    except (AssertionError, KeyError, TypeError) as error:
        raise CandidateContractError(
            "immutable 0.25-mm operating bundle is incomplete; replay assembly is blocked"
        ) from error

    workbench_manifest = _load_object(paths["local_workbench_run_manifest"], "local workbench manifest")
    if workbench_manifest.get("status") != "success":
        raise CandidateContractError("local 0.25-mm workbench is not successful")
    workbench_run = paths["local_workbench_run_manifest"].parent
    workbench_config = _load_object(workbench_run / "run_config.json", "local workbench config")
    parameters = workbench_config.get("parameters", {})
    if (
        parameters.get("fixed_operating_pa") is not True
        or parameters.get("local_mesh_mm_per_gu") != [0.25, 0.25, 0.25]
    ):
        raise CandidateContractError("workbench is not the immutable fixed 0.25-mm operating point")

    outputs = [
        record for record in workbench_manifest.get("outputs", []) if isinstance(record, dict)
    ]
    template_iobs = [
        Path(record["path"]) for record in outputs
        if Path(str(record.get("path", ""))).name == "mrtof_complete_fixed_0p25mm_gui_review.iob"
    ]
    if len(template_iobs) != 1:
        raise CandidateContractError("immutable 0.25-mm template IOB is unavailable")
    _unique_manifest_output(workbench_manifest, template_iobs[0], "fixed 0.25-mm template IOB")
    local_paths: list[Path] = []
    for name in _LOCAL_PA_NAMES:
        matches = [Path(record["path"]) for record in outputs if Path(str(record.get("path", ""))).name == name]
        if len(matches) != 1:
            raise CandidateContractError(f"immutable local operating PA is unavailable: {name}")
        _unique_manifest_output(workbench_manifest, matches[0], name)
        local_paths.append(matches[0].resolve())

    cache_evidence = None
    if operating_cache_identity_path is not None:
        if operating_cache_root is None:
            raise CandidateContractError("operating cache root is required with its identity")
        identity = _load_object(
            operating_cache_identity_path.resolve(), "operating PA cache identity",
        )
        probe = probe_operating_pa_cache(operating_cache_root.resolve(), identity)
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise CandidateContractError("the exact operating PA cache generation is not a valid HIT")
        names = [str(member["output_name"]) for member in identity.get("members", [])]
        if sorted(names) != sorted((
            "local_negative_mirror.pa", "local_negative_bridge.pa", "local_central.pa",
            "local_positive_bridge.pa", "local_positive_mirror.pa",
        )):
            raise CandidateContractError("operating PA cache identity does not contain five regions")
        by_name = {name: probe.generation_directory / name for name in names}
        local_paths = [by_name[name.replace(".pa0", ".pa")] for name in _LOCAL_PA_NAMES]
        cache_evidence = {
            "identity": _record(operating_cache_identity_path.resolve()),
            "cache_root": str(operating_cache_root.resolve()),
            "cache_key": probe.cache_key,
            "generation_directory": str(probe.generation_directory.resolve()),
            "generation_sha256": probe.generation_directory.name,
        }

    for key in ("read_only_analyzer_pa", "read_only_accelerator_pa", "read_only_detector_pa"):
        _unique_manifest_output(workbench_manifest, paths[key], key)

    portability = _load_object(paths["batch_iob_bundle_portability_receipt"], "batch IOB receipt")
    members = portability.get("members")
    if (
        portability.get("status") != "success"
        or portability.get("all_private_pa_hashes_unchanged") is not True
        or not isinstance(members, list) or not members
    ):
        raise CandidateContractError("batch IOB receipt does not prove immutable PA consumption")
    pa_paths = [paths["read_only_analyzer_pa"], *local_paths,
                paths["read_only_accelerator_pa"], paths["read_only_detector_pa"]]
    expected_hashes = [file_sha256(path).upper() for path in pa_paths]
    source_hashes = members[0].get("pa_hashes_before")
    source_identity_match = all(
        member.get("pa_hashes_before") == expected_hashes
        and member.get("pa_hashes_after") == expected_hashes
        for member in members
    )
    if not source_identity_match and operating_cache_identity_path is None:
        raise CandidateContractError("retained PA bytes differ from the successful batch IOB proof")
    if not isinstance(source_hashes, list) or len(source_hashes) != 8:
        raise CandidateContractError("source-flight PA proof lacks eight hashes")
    if cache_evidence is not None:
        cache_evidence["source_flight_pa_identity_match"] = source_identity_match
        cache_evidence["source_flight_pa_sha256"] = [str(value).lower() for value in source_hashes]
        cache_evidence["selected_pa_sha256"] = [value.lower() for value in expected_hashes]
        cache_evidence["qualification"] = (
            "exact_source_flight_pa_identity"
            if source_identity_match
            else "newer_validated_operating_generation__mechanical_replay_required_to_measure_delta"
        )
    origins = portability.get("instance_origins_project_mm")
    if not isinstance(origins, list) or len(origins) != 8:
        raise CandidateContractError("batch IOB receipt lacks the eight instance origins")
    return {
        "qualification": "existing_manifest_bound_fixed_0p25_operating_pas__no_refine",
        "assembly_mode": "rebuild_iob_from_manifest_bound_seed_and_exact_immutable_pa_bytes__no_refine",
        "template_iob": _record(template_iobs[0]),
        "pa_paths": [str(path.resolve()) for path in pa_paths],
        "pa_sha256": [value.lower() for value in expected_hashes],
        "instance_origins_project_mm": origins,
        "iob_builder": _record(paths["iob_builder"]),
        "iob_seed": _record(paths["iob_seed"]),
        "local_refinement_sidecar": _record(paths["local_refinement_sidecar"]),
        "builder_compatibility_companions": {
            "voltage_map": _record(paths["voltage_map"]),
            "mirror_cycle_counter": _record(paths["mirror_cycle_counter"]),
        },
        "flight_launcher": _record(paths["flight_launcher"]),
        "operating_cache": cache_evidence,
    }


def _source_species(run_dir: Path, manifest: Mapping[str, Any]) -> tuple[float, int]:
    try:
        receipt_path = record_path(manifest["inputs"]["bunch_source_receipt"], base_dir=run_dir)
        receipt = _load_object(receipt_path, "bunch source receipt")
        species = receipt["species"]
        mass, charge = float(species["mass_th"]), species["charge_e"]
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("bunch source species is unavailable") from error
    if not math.isfinite(mass) or mass <= 0 or type(charge) is not int or charge == 0:
        raise CandidateContractError("bunch source species is nonphysical")
    return mass, charge


def extract_replay_rows(
    *, events: Mapping[tuple[str, int], list[dict[str, Any]]],
    source_rows: Mapping[int, Mapping[str, float]], particle_count: int,
) -> list[dict[str, Any]]:
    """Extract every and only complete detector-hit P2 state, preserving order."""
    rows: list[dict[str, Any]] = []
    for source_id in range(1, particle_count + 1):
        detector = events.get(("detector", source_id), [])
        if not detector:
            continue
        if len(detector) != 1:
            raise CandidateContractError(f"source ion {source_id} has duplicate detector events")
        p2 = _one(events, "return_p2_pass", source_id)
        turn = _one(events, "return_positive_mirror_turn", source_id)
        terminal = _one(events, "terminal", source_id)
        if int(terminal["splat"]) != 1:
            raise CandidateContractError(f"source ion {source_id} detector/terminal outcome conflicts")
        values = {key: float(p2[key]) for key in (
            "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
        )}
        if not all(math.isfinite(value) for value in values.values()) or values["vz_mm_us"] <= 0:
            raise CandidateContractError(f"source ion {source_id} has an invalid P2 state")
        detector_time = float(detector[0]["t_us"])
        turn_time = float(turn["t_us"])
        rows.append({
            "replay_particle_id": len(rows) + 1,
            "source_particle_id": source_id,
            "source_z_mm": float(source_rows[source_id]["z_mm"]),
            **values,
            "reference_turn_time_us": turn_time,
            "reference_detector_time_us": detector_time,
            "reference_turn_to_detector_us": detector_time - turn_time,
        })
    if len(rows) < 2:
        raise CandidateContractError("post-P2 replay requires at least two complete detector hits")
    return rows


def render_replay_fly2(
    rows: Sequence[Mapping[str, Any]], *, mass_th: float, charge_e: int,
    case: str, dechirped_vz_mm_us: float | None = None,
) -> str:
    if case not in _CASES:
        raise CandidateContractError(f"unsupported replay case: {case}")
    if case == "vz_dechirp" and (
        dechirped_vz_mm_us is None or not math.isfinite(dechirped_vz_mm_us)
        or dechirped_vz_mm_us <= 0
    ):
        raise CandidateContractError("vz-dechirp requires one finite positive common vz")
    beams: list[dict[str, Any]] = []
    for row in rows:
        vx, vy = float(row["vx_mm_us"]), float(row["vy_mm_us"])
        vz = float(row["vz_mm_us"] if case == "original" else dechirped_vz_mm_us)
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        beams.append({
            "tob": "0", "mass": f"{mass_th:.17g}", "charge": str(charge_e),
            "x": f"{float(row['x_mm']):.17g}", "y": f"{float(row['y_mm']):.17g}",
            "z": f"{float(row['z_mm']):.17g}",
            "direction": [f"{value / speed:.17g}" for value in (vx, vy, vz)],
            "ke": f"{kinetic_energy_ev(mass_th, vx * 1000, vy * 1000, vz * 1000):.17g}",
            "cwf": "1", "color": str(int(row["replay_particle_id"])),
        })
    return render_standard_beams(beams)


def _lua_number(value: float) -> str:
    if not math.isfinite(value):
        raise CandidateContractError("Lua replay configuration contains a non-finite number")
    return format(value, ".17g")


def render_replay_operating_point(
    trial: Mapping[str, Any], *, branch: str = "mechanical_detector",
) -> str:
    if branch not in _BRANCHES:
        raise CandidateContractError(f"unsupported replay branch: {branch}")
    detector = trial.get("detector_box_mm")
    planes = trial.get("patch_interface_planes_project")
    trajectory = trial.get("trajectory_profile")
    if not isinstance(detector, list) or len(detector) != 6 or not isinstance(planes, list) or not isinstance(trajectory, dict):
        raise CandidateContractError("trial materialization lacks replay geometry/numerics")
    bridge = [plane for plane in planes if isinstance(plane, dict) and plane.get("name") == _BRIDGE_PLANE]
    mirror_z = {
        plane.get("face"): float(plane["coordinate_mm"])
        for plane in planes if isinstance(plane, dict) and plane.get("region") == "mirror_turn_positive"
        and plane.get("axis") == "z"
    }
    if len(bridge) != 1 or set(mirror_z) != {"z_min", "z_max"}:
        raise CandidateContractError("trial materialization lacks the positive terminal planes")
    plane = bridge[0]
    if plane.get("axis") != "z" or float(plane["coordinate_mm"]) != 105.0:
        raise CandidateContractError("post-P2 replay requires the reviewed z=105 mm interface")
    numbers = lambda values: ",".join(_lua_number(float(value)) for value in values)
    return (
        "return {\n"
        f"  detector_box_mm={{{numbers(detector)}}},\n"
        f"  positive_mirror_z_mm={{{_lua_number(mirror_z['z_min'])},{_lua_number(mirror_z['z_max'])}}},\n"
        f"  bridge_plane={{name='{_BRIDGE_PLANE}',region='local_handoff',face='z_plane',"
        f"z_mm={_lua_number(float(plane['coordinate_mm']))},x_min_mm={_lua_number(float(plane['u_min_mm']))},"
        f"x_max_mm={_lua_number(float(plane['u_max_mm']))},y_min_mm={_lua_number(float(plane['v_min_mm']))},"
        f"y_max_mm={_lua_number(float(plane['v_max_mm']))}}},\n"
        f"  trajectory_quality={_lua_number(float(trajectory['trajectory_quality']))},\n"
        f"  maximum_step_us={_lua_number(float(trajectory['maximum_step_us']))},\n"
        f"  replay_branch='{branch}',\n"
        "  accelerator_field_state='grounded_after_frozen_pulse',\n"
        "  transparent_planes_z_mm={97,72,26,0},\n"
        "  post_p2_timeout_us=20\n}\n"
    )


def stage_ready_iob_bundle(
    *, destination: Path, simion_exe: Path, seed_iob: Path, builder: Path,
    pa_paths: Sequence[Path], origins: Sequence[Sequence[float]], program: Path,
    fly2: Path, operating_point: Path, local_refinement: Path, voltage_map: Path,
    mirror_cycle_counter: Path, placeholder_source_directory: Path,
) -> dict[str, Any]:
    """Build one IOB from hard-linked immutable PAs; never copy, alter, or refine them."""
    destination.mkdir(parents=True, exist_ok=True)
    stem = destination / destination.name
    input_directory = destination / "builder_inputs"
    input_directory.mkdir()
    input_stem = input_directory / "post_p2_replay_input"
    targets = {
        "iob": stem.with_suffix(".iob"),
        "program": stem.with_suffix(".lua"),
        "fly2": stem.with_suffix(".fly2"),
        "operating_point": destination / f"{destination.name}.operating_point.lua",
        "local_refinement": destination / f"{destination.name}.local_refinement.lua",
    }
    staged = {
        "program": input_stem.with_suffix(".lua"),
        "fly2": input_stem.with_suffix(".fly2"),
        "operating_point": input_directory / "post_p2_replay_input.operating_point.lua",
        "local_refinement": input_directory / "post_p2_replay_input.local_refinement.lua",
    }
    sources = {"program": program, "fly2": fly2, "operating_point": operating_point,
               "local_refinement": local_refinement}
    for key, source in sources.items():
        if not source.is_file():
            raise CandidateContractError(f"replay bundle source is missing: {key}")
        shutil.copyfile(source, staged[key])
    shutil.copyfile(voltage_map, input_stem.with_suffix(".voltage_map.lua"))
    shutil.copyfile(mirror_cycle_counter, input_stem.with_suffix(".mirror_cycle_counter.lua"))
    local_names = [
        "iob_input_analyzer.pa", "iob_input_local_1.pa", "iob_input_local_2.pa",
        "iob_input_local_3.pa", "iob_input_local_4.pa", "iob_input_local_5.pa",
        "iob_input_accelerator.pa", "iob_input_detector.pa",
    ]
    if len(pa_paths) != 8 or len(origins) != 8:
        raise CandidateContractError("replay IOB assembly requires eight PAs and eight origins")
    linked: list[Path] = []
    for source, name in zip(pa_paths, local_names, strict=True):
        target = destination / name
        if target.exists():
            raise CandidateContractError(f"replay PA hard-link target already exists: {target}")
        os.link(source, target)
        linked.append(target)
    local_seed = destination / "8_instance_seed.iob"
    shutil.copyfile(seed_iob, local_seed)
    for index in range(1, 9):
        placeholder = seed_iob.parent / f"iob_seed_placeholder_{index:02d}.pa0"
        if not placeholder.is_file():
            placeholder = placeholder_source_directory / placeholder.name
        if not placeholder.is_file():
            raise CandidateContractError(f"IOB seed placeholder is missing: {placeholder}")
        shutil.copyfile(placeholder, destination / placeholder.name)
    arguments = [
        str(simion_exe), "--nogui", "--noprompt", "lua", str(builder), "--",
        str(local_seed), *(str(path) for path in linked), str(targets["iob"]),
        str(staged["program"]), str(staged["fly2"]), str(staged["local_refinement"]),
        *(format(float(value), ".17g") for origin in origins for value in origin),
    ]
    completed = subprocess.run(
        arguments, cwd=destination, capture_output=True, text=True, timeout=120,
    )
    if completed.returncode != 0 or "MRTOF_LOCAL_REFINEMENT_IOB_BUILD=PASS" not in completed.stdout:
        raise CandidateContractError(
            "SIMION replay IOB assembly failed: " + (completed.stdout + completed.stderr)[-2000:]
        )
    return {key: _record(path) for key, path in targets.items()}


def materialize_replay(
    *, run_dir: Path, output_dir: Path, particle_limit: int | None = None,
    simion_exe: Path | None = None, operating_cache_identity_path: Path | None = None,
    operating_cache_root: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "flight run manifest")
    if manifest.get("project") != _PROJECT or manifest.get("mode") != _MODE or manifest.get("status") != "success":
        raise CandidateContractError("post-P2 replay requires one successful complete flight run")
    _verify_manifest(manifest, manifest_path)
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    observation = _load_object(observation_path, "flight observation")
    cohort = observation.get("cohort_analysis")
    if not isinstance(cohort, dict) or cohort.get("event_integrity_passed") is not True:
        raise CandidateContractError("flight observation did not pass complete-cohort integrity")
    try:
        particle_count = int(cohort["expected_particle_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("flight observation lacks the expected particle count") from error
    if particle_count <= 1 or cohort.get("observed_particle_ids") != list(range(1, particle_count + 1)):
        raise CandidateContractError("post-P2 replay requires one complete ordered N>1 cohort")
    source_rows, source_evidence = _load_source_rows(
        run_dir=run_dir, manifest=manifest, expected_count=particle_count,
    )
    events, logs = _load_selected_events(_event_batches(
        run_dir=run_dir, manifest=manifest, particle_count=particle_count,
    ))
    complete_rows = extract_replay_rows(
        events=events, source_rows=source_rows, particle_count=particle_count,
    )
    if particle_limit is not None and not 2 <= particle_limit <= len(complete_rows):
        raise CandidateContractError("replay particle limit must select 2..complete-hit-count")
    rows = complete_rows if particle_limit is None else complete_rows[:particle_limit]
    mass, charge = _source_species(run_dir, manifest)
    common_vz = statistics.median(float(row["vz_mm_us"]) for row in rows)
    bundle = resolve_immutable_operating_bundle(
        run_dir=run_dir, manifest=manifest,
        operating_cache_identity_path=operating_cache_identity_path,
        operating_cache_root=operating_cache_root,
    )
    trial_path = record_path(manifest["inputs"]["trial_materialization"], base_dir=run_dir)
    trial = _load_object(trial_path, "trial materialization")

    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / "post_p2_reference_states.csv"
    with table_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    case_records: dict[str, Any] = {}
    for case in _CASES:
        path = output_dir / f"post_p2_{case}.fly2"
        path.write_text(render_replay_fly2(
            rows, mass_th=mass, charge_e=charge, case=case,
            dechirped_vz_mm_us=common_vz,
        ), encoding="utf-8", newline="\n")
        case_records[case] = _record(path)
    branch_records: dict[str, Any] = {}
    for branch in _BRANCHES:
        sidecar = output_dir / f"post_p2_{branch}.operating_point.lua"
        sidecar.write_text(
            render_replay_operating_point(trial, branch=branch), encoding="utf-8", newline="\n",
        )
        branch_records[branch] = {
            "operating_point_sidecar": _record(sidecar),
            "detector_instance_policy": (
                "retained_mechanical_detector_instance"
                if branch == "mechanical_detector"
                else "instance_8_suppressed_by_documented_instance_adjust_fallback__"
                     "analyzer_and_accelerator_unchanged"
            ),
        }
    program_path = Path(__file__).resolve().parents[1] / "simion" / "post_p2_causal_replay.lua"
    runnable_bundles: dict[str, Any] = {}
    if simion_exe is None or not simion_exe.is_file():
        raise CandidateContractError("a valid SIMION executable is required to assemble replay IOBs")
    for case in _CASES:
        for branch in _BRANCHES:
            key = f"{case}__{branch}"
            runnable_bundles[key] = stage_ready_iob_bundle(
                destination=output_dir / "bundles" / key,
                simion_exe=simion_exe.resolve(), seed_iob=Path(bundle["iob_seed"]["path"]),
                builder=Path(bundle["iob_builder"]["path"]),
                pa_paths=[Path(path) for path in bundle["pa_paths"]],
                origins=bundle["instance_origins_project_mm"],
                program=program_path,
                fly2=Path(case_records[case]["path"]),
                operating_point=Path(branch_records[branch]["operating_point_sidecar"]["path"]),
                local_refinement=Path(bundle["local_refinement_sidecar"]["path"]),
                voltage_map=Path(bundle["builder_compatibility_companions"]["voltage_map"]["path"]),
                mirror_cycle_counter=Path(
                    bundle["builder_compatibility_companions"]["mirror_cycle_counter"]["path"]
                ),
                placeholder_source_directory=Path(bundle["template_iob"]["path"]).parent,
            )
    receipt = {
        "schema_version": 1,
        "role": "mrtof_post_p2_conditional_causal_replay_source",
        "status": "materialized",
        "qualification": (
            "complete_original_detector_hit_cohort__conditional_diagnostic_only"
            if particle_limit is None
            else "ordered_prefix_of_original_detector_hit_cohort__conditional_screen_only"
        ),
        "source_flight": {"path": str(manifest_path), "sha256": file_sha256(manifest_path).lower()},
        "source_particle_count": particle_count,
        "available_conditional_particle_count": len(complete_rows),
        "conditional_particle_count": len(rows),
        "conditional_selection": (
            "complete_detector_hit_cohort"
            if particle_limit is None else "ordered_prefix_of_complete_detector_hit_cohort"
        ),
        "replay_particle_ids": [1, len(rows)],
        "source_particle_ids": [int(row["source_particle_id"]) for row in rows],
        "all_conditional_particles_must_terminate": True,
        "post_replay_filtering": "forbidden",
        "species": {"mass_th": mass, "charge_e": charge},
        "vz_dechirp": {
            "common_vz_mm_us": common_vz,
            "preserved_components": ["x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us"],
            "qualification": "kinematic_vz_dechirp__not_exact_equal_hamiltonian",
        },
        "reference_states": _record(table_path),
        "cases": case_records,
        "branches": branch_records,
        "operating_bundle": bundle,
        "replay_program": _record(program_path),
        "runnable_bundles": runnable_bundles,
        "evidence": {"native_logs": logs, **source_evidence},
    }
    receipt_path = output_dir / "post_p2_causal_replay_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


def analyze_replay_log(
    *, receipt_path: Path, case: str, log_path: Path,
    branch: str = "mechanical_detector",
) -> dict[str, Any]:
    if case not in _CASES:
        raise CandidateContractError(f"unsupported replay case: {case}")
    if branch not in _BRANCHES:
        raise CandidateContractError(f"unsupported replay branch: {branch}")
    receipt = _load_object(receipt_path, "post-P2 replay receipt")
    if receipt.get("role") != "mrtof_post_p2_conditional_causal_replay_source":
        raise CandidateContractError("replay receipt role is invalid")
    verify_record("reference states", receipt["reference_states"])
    with Path(receipt["reference_states"]["path"]).open("r", encoding="utf-8", newline="") as stream:
        references = {int(row["replay_particle_id"]): row for row in csv.DictReader(stream)}
    text = log_path.read_text(encoding="utf-8-sig")
    completions = list(FLY_COMPLETED.finditer(text))
    expected = int(receipt["conditional_particle_count"])
    if len(completions) != 1 or int(completions[0].group("splats")) != expected:
        raise CandidateContractError("replay completion does not cover the conditional cohort")
    replay_plane_events: list[dict[str, Any]] = []
    ordinary_lines: list[str] = []
    required_plane_fields = {
        "ion", "label", "direction_z", "t_us", "x_mm", "y_mm", "z_mm",
        "vx_mm_us", "vy_mm_us", "vz_mm_us",
    }
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = EVENT.match(line.strip())
        if match is None or match.group("kind") != "replay_plane":
            ordinary_lines.append(line)
            continue
        event: dict[str, Any] = {"kind": "replay_plane"}
        for token in match.group("fields").split():
            field = FIELD.fullmatch(token)
            if field is None or field.group("key") in event:
                raise CandidateContractError(f"malformed replay-plane event at line {line_number}")
            try:
                value: Any = float(field.group("value"))
            except ValueError:
                value = field.group("value")
            event[field.group("key")] = value
        if not required_plane_fields <= event.keys() or event["direction_z"] != -1:
            raise CandidateContractError(f"invalid replay-plane event at line {line_number}")
        replay_plane_events.append(event)
    events = parse_events("\n".join(ordinary_lines)) + replay_plane_events
    terminal = [event for event in events if event["kind"] == "terminal"]
    by_terminal = {int(event["ion"]): event for event in terminal}
    if len(terminal) != expected or set(by_terminal) != set(range(1, expected + 1)):
        raise CandidateContractError("replay must retain one terminal event per conditional particle")
    comparisons: list[dict[str, Any]] = []
    hit_count = collision_count = timeout_count = 0
    for ion in range(1, expected + 1):
        outcome = int(by_terminal[ion]["splat"])
        hit_count += outcome == 1
        collision_count += outcome == -1
        timeout_count += outcome == 2
        turns = [event for event in events if event["kind"] == "return_positive_mirror_turn" and int(event["ion"]) == ion]
        detectors = [event for event in events if event["kind"] == "detector" and int(event["ion"]) == ion]
        observed = None
        if outcome == 1:
            if len(turns) != 1 or len(detectors) != 1:
                raise CandidateContractError(f"replay hit {ion} lacks one turn/detector pair")
            observed = float(detectors[0]["t_us"]) - float(turns[0]["t_us"])
        reference = float(references[ion]["reference_turn_to_detector_us"])
        comparisons.append({
            "replay_particle_id": ion,
            "source_particle_id": int(references[ion]["source_particle_id"]),
            "terminal_splat": outcome,
            "observed_turn_to_detector_us": observed,
            "reference_turn_to_detector_us": reference,
            "difference_us": None if observed is None else observed - reference,
        })
    finite = [row["difference_us"] for row in comparisons if row["difference_us"] is not None]
    plane_events = [event for event in events if event["kind"] == "replay_plane"]
    planes: dict[str, Any] = {}
    for label in ("detector_z97", "handoff_z72", "p2_near_z26", "focus_z0"):
        selected = [event for event in plane_events if event.get("label") == label]
        by_ion = {int(event["ion"]): event for event in selected}
        if len(by_ion) != len(selected):
            raise CandidateContractError(f"duplicate transparent-plane event: {label}")
        times = [float(event["t_us"]) for event in selected]
        absolute_times = [
            float(references[int(event["ion"])]["t_us"]) + float(event["t_us"])
            for event in selected
        ]
        source_z = []
        for event in selected:
            value = references[int(event["ion"])].get("source_z_mm")
            if value not in (None, ""):
                source_z.append(float(value))
        def association(values: Sequence[float]) -> float | None:
            if len(source_z) != len(values) or len(values) < 2 or min(source_z) == max(source_z):
                return None
            mean_z, mean_t = statistics.mean(source_z), statistics.mean(values)
            return sum(
                (z - mean_z) * (time - mean_t)
                for z, time in zip(source_z, values, strict=True)
            ) / sum((z - mean_z) ** 2 for z in source_z)
        duration_slope = association(times)
        absolute_slope = association(absolute_times)
        planes[label] = {
            "crossing_count": len(selected),
            "missing_particle_ids": sorted(set(range(1, expected + 1)) - set(by_ion)),
            "time_us": {
                "median": None if not times else statistics.median(times),
                "fwhm": None if not times else _fwhm(times),
                "dt_d_source_z_us_per_mm": duration_slope,
            },
            "post_p2_duration_us": {
                "median": None if not times else statistics.median(times),
                "fwhm": None if not times else _fwhm(times),
                "dt_d_source_z_us_per_mm": duration_slope,
            },
            "reconstructed_absolute_time_us": {
                "median": None if not absolute_times else statistics.median(absolute_times),
                "fwhm": None if not absolute_times else _fwhm(absolute_times),
                "dt_d_source_z_us_per_mm": absolute_slope,
                "definition": "source_flight_P2_time_plus_rebased_replay_duration",
            },
            "crossings": selected,
        }
    return {
        "schema_version": 1,
        "role": "mrtof_post_p2_causal_replay_observation",
        "status": "candidate_diagnostic",
        "case": case,
        "branch": branch,
        "conditional_particle_count": expected,
        "detector_hit_count": hit_count,
        "electrode_collision_count": collision_count,
        "timeout_count": timeout_count,
        "other_terminal_count": expected - hit_count - collision_count - timeout_count,
        "all_conditional_particles_retained": True,
        "peak_filtering": "none",
        "baseline_per_particle_comparison": comparisons,
        "baseline_difference": {
            "available_count": len(finite),
            "maximum_absolute_us": None if not finite else max(abs(value) for value in finite),
            "median_us": None if not finite else statistics.median(finite),
        },
        "transparent_plane_crossings": planes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--run-dir", type=Path, required=True)
    materialize.add_argument("--output-dir", type=Path, required=True)
    materialize.add_argument("--particle-limit", type=int)
    materialize.add_argument("--simion-exe", type=Path, required=True)
    materialize.add_argument("--operating-cache-identity", type=Path)
    materialize.add_argument("--operating-cache-root", type=Path)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--receipt", type=Path, required=True)
    analyze.add_argument("--case", choices=_CASES, required=True)
    analyze.add_argument("--branch", choices=_BRANCHES, default="mechanical_detector")
    analyze.add_argument("--log", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        result = materialize_replay(
            run_dir=args.run_dir, output_dir=args.output_dir, particle_limit=args.particle_limit,
            simion_exe=args.simion_exe,
            operating_cache_identity_path=args.operating_cache_identity,
            operating_cache_root=args.operating_cache_root,
        )
    else:
        result = analyze_replay_log(
            receipt_path=args.receipt, case=args.case, branch=args.branch, log_path=args.log,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
