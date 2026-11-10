"""Infer two voltage controls from measured assembled Laplace responses.

This local quadratic design is a proposal, not a capture or flight result.
The independent terminal-inner and HP-common responses avoid conflating well
curvature, gate height and released energy in one arbitrary voltage scan.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from msplatform.execution.retention import file_record
from msplatform.components.dual_pressure_rectilinear_ion_processor import cooled_field_design








def analyze_field_run(run: Path) -> dict:
    """Analyze an unsealed caller-owned native field stage before publication."""
    run = Path(run).resolve(strict=True)
    def read(name):
        return json.loads((run/"inputs"/name).read_text(encoding="utf-8-sig"))
    manifest_path = run/"run_manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8-sig")).get("status") != "checkpoint":
        raise ValueError("field analysis must precede immutable owner publication")
    targets = read("cooled_design_targets.json")
    conditioner, guide = read("conditioner_contract.json"), read("guide_contract.json")
    source = pd.read_csv(run/"inputs/release_global.csv")
    if len(source[["mass_amu","charge_state"]].drop_duplicates()) != 1:
        raise ValueError("single-species curvature design required")
    # Native probes sample the actual immutable source member.  A proven
    # Laplace rescaling is a scientific projection, never a rewritten CSV.
    from .runtime import KINDS, static_probe_analysis_records
    stage = read("cooled_frontend_field_stage_receipt.json")
    rows = stage["working_points"]
    actual_probes = static_probe_analysis_records(run, rows)
    probe_records = actual_probes["native_probe_records"]
    paths = {kind: Path(record["path"]) for kind, record in probe_records.items()}
    if tuple(row["kind"] for row in rows) != KINDS or set(paths) != set(KINDS):
        raise ValueError("complete ordered field member evidence required")
    responses = {}
    projections = {}
    for row in rows:
        kind = row["kind"]
        scale = row["field_scale"]
        responses[kind] = cooled_field_design.project_member_samples(pd.read_csv(paths[kind]), kind, scale)
        projections[kind] = dict(scale=scale, source_member=row,
                                raw_probe_record=probe_records[kind])
        if kind in actual_probes["probe_owner_manifest_records"]:
            projections[kind]["probe_owner_manifest_record"] = actual_probes["probe_owner_manifest_records"][kind]
    output = run/"results/cooled_field_design"
    output.mkdir(exist_ok=False)
    try:
        result = cooled_field_design.design_voltage_controls(responses,
            center_mr_mm=conditioner["geometry"]["trap_center_mr_mm"],
            mass_amu=float(source.mass_amu.iloc[0]), charge_state=int(source.charge_state.iloc[0]),
            temperature_k=conditioner["gas"]["parameters"]["temperature_k"],
            rf_frequency_hz=guide["drive"]["frequency_hz"],
            guide_rf_amplitude_v=guide["drive"]["rf_amplitude_v"],
            target_thermal_sigma_y_mm=targets["thermal_sigma_y_mm"],
            target_static_energy_gain_ev=targets["static_release_energy_gain_ev"],
            release_reference_name="well_62",oa_entry_reference_name="oa_side_entry")
        result["design_status"] = ("proposal_computed" if result["calibrated_closed_well"]["equilibrium_within_sample_bounds"]
                                    else "additional_actual_field_samples_required")
    except ValueError as error:
        result = dict(schema_version=1,role="cooled_frontend_actual_field_voltage_design",
                      design_status="target_not_identifiable_or_feasible",reason=str(error),
                      qualification="Native fields remain evidence; failed theory target does not qualify capture or focusing")
    result["native_probe_records"] = probe_records
    result["response_projections"] = projections
    result["target_record"] = file_record(run/"inputs/cooled_design_targets.json")
    (output/"voltage_design.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    result = analyze_field_run(parser.parse_args().run)
    print(json.dumps(dict(role=result["role"],design_status=result["design_status"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
