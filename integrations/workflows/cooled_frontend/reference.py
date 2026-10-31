"""Actual-field cold-reference and original-birth N1 adapters for the public runner.

This module materializes inputs and shared scheduler contracts only. Native
processes, lifecycle and final publication remain in the family execute route.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C, kinetic_energy_ev
from common.contracts.write_run_manifest import file_record
from common.simion.particle_batching import batch_plan_from_dispatch, plan_single_wave_batches
from integrations.workflows.cooled_frontend import runtime
from integrations.workflows.local_frontend import runtime as shared
from integrations.workflows.local_frontend.analyze import _capture_bounds, _validate_lifetimes, parse_local_logs
from integrations.workflows.local_frontend.prepare import _csv_text, _nominal_extraction_duration


TOPOLOGY="cooled_frontend_one_carrier_six_readonly_responses_v1"


def interpolate_unit_rf(samples: pd.DataFrame,position_mm: list[float]) -> list[float]:
    """Trilinearly interpolate the measured Cartesian stencil without extrapolation."""
    axes=[np.sort(samples[f"{a}_mm"].unique()) for a in "xyz"]
    if len(samples)!=math.prod(len(a) for a in axes) or samples.duplicated([f"{a}_mm" for a in "xyz"]).any():
        raise ValueError("RF samples must be one complete Cartesian stencil")
    brackets=[]
    for value,axis in zip(position_mm,axes,strict=True):
        if not math.isfinite(value) or len(axis)<2 or value<axis[0] or value>axis[-1]:
            raise ValueError("reference equilibrium lies outside the measured RF stencil")
        upper=min(max(int(np.searchsorted(axis,value,side="right")),1),len(axis)-1)
        low,high=float(axis[upper-1]),float(axis[upper])
        brackets.append(((low,(high-value)/(high-low)),(high,(value-low)/(high-low))))
    indexed=samples.set_index([f"{a}_mm" for a in "xyz"])
    result=np.zeros(3)
    for corner in itertools.product(*brackets):
        row=indexed.loc[tuple(v[0] for v in corner)]
        weight=math.prod(v[1] for v in corner)
        result+=weight*row[[f"e{a}_v_per_mm" for a in "xyz"]].to_numpy(dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("nonfinite measured RF interpolation")
    return result.tolist()


def cold_reference_state(design: dict,rf_samples: pd.DataFrame,guide: dict,*,
                         release_start_us: float,mass_amu: float,charge_state: int) -> tuple[dict,dict]:
    """Use a local effective equilibrium and first-order measured micromotion.

    Position is the fitted secular equilibrium, as explicitly requested. The
    omitted first-order displacement is reported; this diagnostic ray is not a
    thermal sample, an RF-periodic orbit proof, or the original mother source.
    """
    well=design["calibrated_closed_well"]
    if design.get("design_status")!="proposal_computed" or well.get("equilibrium_within_sample_bounds") is not True or well.get("locally_positive_effective_curvature") is not True:
        raise ValueError("cold reference requires a positive actual-field equilibrium inside its sampled stencil")
    position=[float(v) for v in well["equilibrium_mr_mm"]]
    bounds=well["fit_sample_bounds_mr_mm"]
    if any(not lo<=v<=hi for v,lo,hi in zip(position,bounds["min_mm"],bounds["max_mm"],strict=True)):
        raise ValueError("reported equilibrium is outside actual fit bounds")
    field=interpolate_unit_rf(rf_samples[rf_samples.name.str.startswith("well_")],position)
    drive=guide["drive"]
    omega=2*math.pi*float(drive["frequency_hz"])
    phase=omega*release_start_us*1e-6+float(drive["phase_rad"])
    scale=charge_state*ELEMENTARY_CHARGE_C*float(drive["rf_amplitude_v"])*1000/(mass_amu*AMU_KG)
    velocity=[scale*e*math.sin(phase)/omega for e in field]
    displacement=[-scale*e*math.cos(phase)/(omega*omega)*1000 for e in field]
    row=dict(particle_id=1,instrument_time_us=release_start_us,mass_amu=mass_amu,charge_state=charge_state,
             **{f"position_{a}_mm":position[i] for i,a in enumerate("xyz")},
             **{f"velocity_{a}_m_s":velocity[i] for i,a in enumerate("xyz")},
             kinetic_energy_eV=kinetic_energy_ev(mass_amu,*velocity))
    evidence=dict(role="measured_field_first_order_cold_reference",unit_rf_e_v_per_mm=field,
        phase_rad=phase,reference_temperature_k=0,secular_velocity_m_s=[0.,0.,0.],
        micromotion_velocity_m_s=velocity,omitted_micromotion_displacement_mm=displacement,
        position_policy="actual fitted secular equilibrium; no instantaneous displacement applied",
        equation="v_micro=q*A*E_unit*sin(omega*t+phase)/(m*omega)",
        qualification="adiabatic first-order diagnostic initial state; native RF flight remains required")
    return row,evidence


def native_arrival_window(events: list[dict], frontend: dict, source_row: dict) -> dict:
    """Use one supported forward OFF branch and the provider's ideal transit time.

    The two times are hypotheses, not an observed exit-residual bracket. Every
    interpolation stays between recorded native states; native pulse trials
    must still bracket the requested exit position before a secant is used.
    """
    bounds=_capture_bounds(frontend)
    target=bounds["y"]["center_mm"]
    rows=[row for row in events if row["event"]=="local_trajectory"]
    crossings=[i for i,(a,b) in enumerate(zip(rows,rows[1:]))
               if a["y_mm"] <= target < b["y_mm"] and a["vy_mm_per_us"]>0 and b["vy_mm_per_us"]>0]
    if len(crossings)!=1:
        raise ValueError("held-OFF reference lacks one unique supported forward OA center crossing")
    index=crossings[0];a,b=rows[index:index+2]
    fraction=(target-a["y_mm"])/(b["y_mm"]-a["y_mm"])
    center=a["instrument_time_us"]+fraction*(b["instrument_time_us"]-a["instrument_time_us"])
    duration=_nominal_extraction_duration(frontend,source_row)
    early=center-duration
    support=[i for i,(a,b) in enumerate(zip(rows,rows[1:]))
             if a["instrument_time_us"]<=early<b["instrument_time_us"]]
    if not math.isfinite(duration) or duration<=0 or len(support)!=1:
        raise ValueError("nominal extraction interval lacks actual held-OFF trajectory support")
    first=support[0]
    posts=[row for row in events if row["event"]=="local_aperture_post" and row["instrument_time_us"]<=early]
    pres=[row for row in events if row["event"]=="local_aperture_pre" and posts and row["instrument_time_us"]<posts[0]["instrument_time_us"]]
    if len(posts)!=1 or len(pres)!=1 or pres[0]["vy_mm_per_us"]<=0 or posts[0]["vy_mm_per_us"]<=0:
        raise ValueError("held-OFF center window requires one ordered native pre/post aperture passage")
    branch=[row for row in rows[:index+2] if row["instrument_time_us"]>=posts[0]["instrument_time_us"]]
    if any(row["vy_mm_per_us"]<=0 for row in branch) or any(
        b["y_mm"]<=a["y_mm"] or b["instrument_time_us"]<=a["instrument_time_us"] for a,b in zip(branch,branch[1:])):
        raise ValueError("held-OFF reference reversed after its native aperture passage")
    branch=rows[first:index+2]
    if first>index or any(row["vy_mm_per_us"]<=0 or any(
        not bounds[axis]["minimum_mm"]<=row[f"{axis}_mm"]<=bounds[axis]["maximum_mm"] for axis in "xyz") for row in branch) or any(
        b["y_mm"]<=a["y_mm"] or b["instrument_time_us"]<=a["instrument_time_us"] for a,b in zip(branch,branch[1:])):
        raise ValueError("candidate pulse interval is not one supported forward in-cavity OFF branch")
    return dict(target_y_mm=target,center_time_us=center,nominal_extraction_duration_us=duration,
        candidate_derivation="native_center_time_minus_provider_nominal_extraction_duration__native_center_time",
        initial_trials=[dict(phase="trial_a",pulse_time_us=early),dict(phase="trial_b",pulse_time_us=center)],
        aperture_pre=pres[0],aperture_post=posts[0],
        center_bracket=rows[index:index+2],early_time_bracket=rows[first:first+2],
        qualification="native OFF arrival support with ideal extraction-time hypotheses; native exit residual bracket still required")


def _retained_record(path: Path,owner: dict,workspace: Path) -> dict:
    record=file_record(path)
    if not any(runtime._same_identity(record,r,workspace) for r in owner.get("outputs",[])):
        raise ValueError("reference theory/probe file is not bound by sealed field owner outputs")
    return record


def prepare_reference(run: Path) -> dict:
    """Freeze one traceable cold reference without modifying the original 100 rows."""
    run=shared._owner(run,"extraction");inputs=run/"inputs";workspace=run.parents[4]
    field_context=runtime.fields(run)
    experiment=shared._load(inputs/"cooled_experiment.json")
    if experiment["pressure_scale"]!=0 or experiment["field_source"] is None or experiment["common_pulse_decision"] is not None:
        raise ValueError("reference preparation requires shared sealed fields, vacuum and no production decision")
    envelope=shared._load(runtime._verified_small_record(experiment["field_source"],workspace))
    manifest_path=runtime._verified_small_record(envelope["source_owner_manifest_record"],workspace)
    owner=shared._load(manifest_path)
    design_path=manifest_path.parent/"results/cooled_field_design/voltage_design.json"
    design_record=_retained_record(design_path,owner,workspace)
    design=shared._load(design_path)
    if file_record(inputs/"cooled_design_targets.json")["sha256"]!=design["target_record"]["sha256"]:
        raise ValueError("reference design targets differ from actual-field voltage design")
    responses={}
    for kind,record in design["native_probe_records"].items():
        path=runtime._verified_small_record(record,workspace)
        if not any(runtime._same_identity(record,r,workspace) for r in owner.get("outputs",[])):
            original = design.get("response_projections", {}).get(kind, {}).get("probe_owner_manifest_record")
            if original is None:
                raise ValueError("reference theory/probe file is not bound by sealed field owner outputs")
            runtime.validate_static_probe_reference(run, kind, record, original, field_context["records"][kind])
        responses[kind]=pd.read_csv(path)
    with (inputs/"release_global.csv").open(encoding="utf-8-sig",newline="") as handle:
        original=list(csv.DictReader(handle))
    if len(original)!=100 or [int(r["particle_id"]) for r in original]!=list(range(1,101)):
        raise ValueError("reference provenance requires the complete ordered N=100 mother source")
    species={(float(r["mass_amu"]),int(r["charge_state"])) for r in original}
    if len(species)!=1:
        raise ValueError("single-species reference required")
    mass,charge=next(iter(species))
    guide=shared._load(inputs/"guide_contract.json");drive=shared._load(inputs/"cooled_drive.json")
    row,micro=cold_reference_state(design,responses["rf_differential_unit"],guide,
        release_start_us=drive["release_start_us"],mass_amu=mass,charge_state=charge)
    calibration=design["voltage_calibration"]
    target=_capture_bounds(shared._load(inputs/"frontend_contract.json"))["y"]["center_mm"]
    value=dict(schema_version=1,role="rf_oatof_cooled_frontend_cold_reference_source",mother_count=100,simulated_count=1,
        mother_population_flight=False,source_rows=[row],voltage_calibration=calibration,micromotion=micro,
        field_stage_receipt_record=field_context["receipt"],
        voltage_design_record=design_record,native_probe_records=design["native_probe_records"],
        original_source_record=file_record(inputs/"release_global.csv"),
        qualification="independent actual-field calibration ray; no mother capture/cooling/throughput claim")
    value.update(metadata_path=str(inputs/"cooled_reference_source.json"),working_points=list(field_context["records"].values()))
    times=sorted(set([0.,drive["entrance_close_us"],drive["release_start_us"],
        (drive["entrance_close_us"]+drive["release_start_us"])/2,
        drive["release_start_us"]+shared._load(inputs/"numerics.json")["maximum_flight_us"]]))
    times_path=inputs/"cooled_reference_shared_times.json"
    shared._json_once(times_path,times)
    value.update(shared_times_path=str(times_path),target_y_mm=target,release_start_us=drive["release_start_us"],
        field_identity=dict(field_stage_receipt_record=field_context["receipt"]))
    shared._json_once(inputs/"cooled_reference_source.json",value)
    shared._write_once(inputs/"cooled_reference_release.csv",_csv_text(shared.GLOBAL_COLUMNS,[row]))
    return value


def _trial(run: Path,phase: str,pulse: float | None,times: list[float]) -> tuple[dict,dict,dict]:
    if re.fullmatch(r"[a-z][a-z0-9_]*",phase) is None:
        raise ValueError("explicit lowercase trial identifier required")
    if not times or times!=sorted(set(times)) or any(not math.isfinite(t) or t<0 for t in times):
        raise ValueError("reference shared times must be finite, nonnegative and increasing")
    data=prepare_reference(run)
    if (phase=="held_off") != (pulse is None):
        raise ValueError("held-OFF discovery has no pulse; native pulse trials require an explicit clock")
    reference_phase=dict(role="cooled_reference_phase",pulse_mode=2 if pulse is None else 1,pulse_time_us=pulse,
        release_start_us=data["source_rows"][0]["instrument_time_us"],voltage_calibration=data["voltage_calibration"],
        field_identity=dict(field_stage_receipt_record=data["field_stage_receipt_record"]))
    ctx=runtime.context(run,reference_phase=reference_phase)
    ctx.update(rows=data["source_rows"],source_record=file_record(run/"inputs/cooled_reference_release.csv"),
               source_identity_record=file_record(run/"inputs/cooled_reference_source.json"))
    phase_input=dict(schema_version=1,role="rf_oatof_cooled_reference_runtime_phase",phase=phase,pulse_time_us=pulse,pulse_mode=reference_phase["pulse_mode"],shared_times_us=times)
    shared._json_once(run/"inputs"/f"cooled_reference_phase__{phase}.json",phase_input)
    return data,ctx,phase_input


def prepare_dispatch_request(run: Path,phase: str,pulse: float | None,times: list[float]) -> dict:
    run=shared._owner(run,"extraction")
    _,ctx,phase_input=_trial(run,phase,pulse,times)
    return shared.prepare_dispatch_request(run,"extraction",context=ctx,workload_topology_id=TOPOLOGY,
        phase_input=phase_input,output_path=run/"inputs"/f"{phase}_dispatch_request.json")


def materialize_batches(run: Path,phase: str,plan: dict,pulse: float | None,times: list[float]) -> dict:
    run=shared._owner(run,"extraction")
    plan=batch_plan_from_dispatch(plan) if plan.get("role")=="simion_repository_dispatch_plan" else plan
    expected=plan_single_wave_batches(1,1)
    if plan.get("particle_count")!=1 or plan.get("batch_count")!=1 or any(plan["batches"][0].get(k)!=v for k,v in expected["batches"][0].items()):
        raise ValueError("diagnostic reference dispatch must cover exactly one ID without rebasing")
    _,ctx,phase_input=_trial(run,phase,pulse,times)
    case=runtime.materialize_reference_case(run,ctx,phase_input)
    role="rf_oatof_cooled_frontend_cold_reference"
    case=dict(index=1,**case)
    result=dict(schema_version=1,role=role,phase=phase,frame_id=ctx["frontend"]["frame_id"],source_count=1,mother_count=100,simulated_count=1,
        mother_population_flight=False,coverage="complete_population",coverage_scope="one explicitly declared diagnostic particle; not the N=100 mother",
        complete_source_particle_ids=[1],scheduled_particle_ids=[1],pending_particle_ids=[],batches=[case],gui_case=case,
        field_records=ctx["fields"]["records"],field_stage_record=ctx["fields"]["receipt"],gui_fly_performed=False,
        saved_default_replay_verification="pending",default_load_iob=case["iob_path"])
    path=run/"results"/f"{phase}_reference_batches.json";result["receipt_path"]=str(path)
    shared._json_once(path,result)
    return result


def collect_trial(run: Path,phase: str) -> dict:
    """Keep complete native logs/terminals; expose one measured exit to root pulse logic."""
    run=shared._owner(run,"extraction")
    materialized=shared._load(run/"results"/f"{phase}_reference_batches.json")
    case=materialized["batches"][0]
    with Path(case["source_record"]["path"]).open(encoding="utf-8-sig",newline="") as handle:
        source={int(r["particle_id"]):r for r in csv.DictReader(handle)}
    events,logs=parse_local_logs([Path(case["stdout"])],source)
    lives=_validate_lifetimes(events,source)
    exits=[e for e in events if e["event"]=="local_accelerator_exit"]
    evidence=dict(source_record=case["source_record"],program_record=case["program_record"],raw_logs=logs,
                  materialization_record=file_record(Path(materialized["receipt_path"])),lifetimes=lives)
    phase_input=shared._load(run/"inputs"/f"cooled_reference_phase__{phase}.json")
    result=dict(schema_version=1,role="cooled_frontend_native_reference_trial",status="exit_observed" if len(exits)==1 else "no_unique_exit",
        phase=phase,pulse_time_us=phase_input["pulse_time_us"],evidence=evidence,mother_population_flight=False)
    if phase=="held_off":
        try:
            frontend=shared._load(run/"inputs/frontend_contract.json")
            window=native_arrival_window(events,frontend,next(iter(source.values())))
            result.update(status="window_observed",arrival_window=window)
        except ValueError as exc:
            result.update(status="no_supported_window",reason=str(exc))
    elif len(exits)==1:
        result.update(exit_y_mm=exits[0]["y_mm"],exit_time_us=exits[0]["instrument_time_us"])
    result_path=run/"results"/f"{phase}_reference_trial.json"
    shared._json_once(result_path,result)
    result["evidence_record"]=file_record(result_path)
    return result


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    for action in ("prepare-reference","collect-trial","prepare-dispatch","materialize-batches"):
        item=sub.add_parser(action);item.add_argument("--run",type=Path,required=True)
        if action!="prepare-reference":
            item.add_argument("--phase",required=True)
        if action in ("prepare-dispatch","materialize-batches"):
            item.add_argument("--pulse-time-us",type=float);item.add_argument("--shared-times-json",type=Path,required=True)
        if action=="materialize-batches":
            item.add_argument("--batch-plan",type=Path,required=True)
    args=parser.parse_args()
    if args.action=="prepare-reference":
        result=prepare_reference(args.run)
    elif args.action=="collect-trial":
        result=collect_trial(args.run,args.phase)
    else:
        times=json.loads(args.shared_times_json.read_text(encoding="utf-8-sig"))
        result=prepare_dispatch_request(args.run,args.phase,args.pulse_time_us,times) if args.action=="prepare-dispatch" else materialize_batches(args.run,args.phase,shared._load(args.batch_plan),args.pulse_time_us,times)
    print(json.dumps(result,allow_nan=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
