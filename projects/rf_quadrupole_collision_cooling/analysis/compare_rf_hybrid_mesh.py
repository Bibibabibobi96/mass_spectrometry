"""Evaluate paired RF hybrid-mesh field runs and partition continuity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


KEYS = ["sample_z_mm", "sample_radius_mm", "theta_rad"]
FIELDS = ["Ex_V_per_m", "Ey_V_per_m", "Ez_V_per_m"]


def relative_rms(candidate: np.ndarray, reference: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(candidate - reference))) / np.sqrt(np.mean(np.square(reference))))


def compare(coarse: pd.DataFrame, fine: pd.DataFrame, contract: dict) -> dict:
    left=coarse.sort_values(KEYS).reset_index(drop=True);right=fine.sort_values(KEYS).reset_index(drop=True)
    if len(left)!=len(right):raise ValueError("hybrid field tables have different row counts")
    for column in KEYS:
        if not np.allclose(left[column],right[column],rtol=0.0,atol=1e-12):raise ValueError(f"hybrid field tables do not share {column}")
    radius_limit=float(contract["field_sampling"]["hard_field_convergence_radius_max_mm"]);threshold=float(contract["acceptance"]["maximum_relative_vector_rms_last_two_end_meshes_r_le_3_mm"])
    by_z={}
    for z_value,indices in right.groupby("sample_z_mm",sort=True).groups.items():
        indices=[index for index in indices if right.loc[index,"sample_radius_mm"]<=radius_limit]
        by_z[f"{float(z_value):.12g}"]=relative_rms(left.loc[indices,FIELDS].to_numpy(float),right.loc[indices,FIELDS].to_numpy(float))
    partition={}
    for lower,upper in ((9.799,9.801),(81.399,81.401)):
        a=right[np.isclose(right.sample_z_mm,lower)&(right.sample_radius_mm<=radius_limit)].sort_values(["sample_radius_mm","theta_rad"])
        b=right[np.isclose(right.sample_z_mm,upper)&(right.sample_radius_mm<=radius_limit)].sort_values(["sample_radius_mm","theta_rad"])
        partition[f"{lower:.3f}_to_{upper:.3f}"]=relative_rms(a[FIELDS].to_numpy(float),b[FIELDS].to_numpy(float))
    checks={"every_core_z_group_converged":max(by_z.values())<=threshold,"partition_pairs_continuous":max(partition.values())<=float(contract["acceptance"]["maximum_relative_vector_rms_at_partition_pairs_r_le_3_mm"])}
    field_status="PASS" if all(checks.values()) else "FAIL"
    return {"schema_version":1,"role":"rf_full_device_hybrid_mesh_paired_field_comparison","status":field_status,"relative_vector_rms_by_z_mm_r_le_3_mm":by_z,"partition_pair_relative_vector_rms_r_le_3_mm":partition,"maximum_core_z_group_relative_vector_rms":max(by_z.values()),"checks":checks,"paired_particle_diagnostic_allowed":True,"particle_acceptance_allowed":False,"interpretation":"Local field ratios remain diagnostic. A problem-free pair proceeds to paired N=100 functional arbitration; only a decision-relevant particle difference authorizes further refinement.","claim_limit":"Field characterization only; no particle acceptance, shield-radius or connector claim."}


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--coarse",required=True,type=Path);parser.add_argument("--fine",required=True,type=Path);parser.add_argument("--contract",required=True,type=Path);parser.add_argument("--output",required=True,type=Path);args=parser.parse_args();report=compare(pd.read_csv(args.coarse),pd.read_csv(args.fine),json.loads(args.contract.read_text(encoding="utf-8")));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(f"RF_HYBRID_MESH_COMPARISON={report['status']} PAIRED_PARTICLE_DIAGNOSTIC_ALLOWED=true")


if __name__=="__main__":main()
