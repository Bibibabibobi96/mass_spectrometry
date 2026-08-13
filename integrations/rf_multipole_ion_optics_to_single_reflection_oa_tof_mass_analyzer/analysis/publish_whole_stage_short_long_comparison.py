"""Publish a manifest-bound comparison of short- and long-focus pulse winners."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import _peak_summary
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import publish_manifest

PROJECT = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "whole_stage_short_long_postselection_comparison"


def _load(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _cohorts(path: Path) -> tuple[list[int], dict[int, float], list[float]]:
    rows = _load(path)
    eligible = sorted({int(row["particle_id"]) for row in rows if row["event"] == "pre_pulse_state" and row["pulse_eligibility"] == "eligible"})
    detector = {int(row["particle_id"]): float(row["pulse_effective_elapsed_us"]) for row in rows if row["event"] == "detector_crossing"}
    return eligible, detector, list(detector.values())


def _id_sha(ids: list[int]) -> str:
    return hashlib.sha256(("\n".join(map(str, ids)) + "\n").encode()).hexdigest().upper()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--long-checkpoints", required=True, type=Path); p.add_argument("--short-checkpoints", required=True, type=Path)
    p.add_argument("--long-report", required=True, type=Path); p.add_argument("--short-report", required=True, type=Path)
    p.add_argument("--run-dir", required=True, type=Path); p.add_argument("--run-id", required=True); p.add_argument("--repo-root", required=True, type=Path)
    a = p.parse_args(); out = a.run_dir / "results"; out.mkdir(parents=True, exist_ok=True)
    long_ids, long_detector, long_all = _cohorts(a.long_checkpoints); short_ids, short_detector, short_all = _cohorts(a.short_checkpoints)
    same_ids = long_ids == short_ids
    if len(long_ids) != 695 or len(short_ids) != 695 or not same_ids:
        raise ValueError("eligible cohorts are not the required identical N=695 set")
    paired_ids = sorted(set(long_ids) & set(long_detector) & set(short_detector))
    if len(paired_ids) != 695:
        raise ValueError("eligible paired detector cohort is incomplete")
    delta_ns = np.asarray([1000.0 * (short_detector[i] - long_detector[i]) for i in paired_ids])
    long_report = json.loads(a.long_report.read_text(encoding="utf-8-sig")); short_report = json.loads(a.short_report.read_text(encoding="utf-8-sig"))
    report = {"schema_version":1,"role":"whole_stage_short_long_postselection_comparison","status":"success","common_mother_sha256":"302C03DC29737CE9D46EB1A8D258DB2A8D3C0F8B6A53F7702A33B1ECF9D5320D","eligible_ids":{"count":695,"exact_same":same_ids,"sha256":_id_sha(long_ids)},"detector_counts":{"long":len(long_all),"short":len(short_all)},"paired_detector_tof":{"count":len(paired_ids),"short_minus_long_mean_ns":float(np.mean(delta_ns)),"short_minus_long_std_ns":float(np.std(delta_ns,ddof=1)),"short_minus_long_min_ns":float(np.min(delta_ns)),"short_minus_long_max_ns":float(np.max(delta_ns))},"peaks":{"long_eligible":long_report["eligible_canonical_peak"],"long_all":long_report.get("all_detector_canonical_peak"),"short_eligible":short_report["eligible_canonical_peak"],"short_all":short_report["all_detector_canonical_peak"]},"architecture_bundle":{"only_intended_difference":"layout architecture bundle","long":{"layout_profile_id":"symmetric_10ev_source_z22_finite_interval_theory","architecture_generation_id":"finite_interval_2p2mm_matched_voltage_v1"},"short":{"layout_profile_id":"theory_source_z10_d1_3","architecture_generation_id":"short_focus_1mm_theory_v1"},"frozen":["mother source and ordered IDs","upstream manifest/handoff identity","canonical clock","native one-row grids","real accelerator and reflectron fields","frontend overlay z=0.05 mm","Formal oaTOF numerical profile","RF steps and trajectory quality","pulse offset +0.0625 RF"]},"claim_limit":"Layout-specific detector-blind selection followed by canonical post-selection comparison; diagnostic only."}
    report_path=out/"short_long_comparison.json"; csv_path=out/"short_long_comparison.csv"; png_path=out/"short_long_paired_tof.png"
    report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    with csv_path.open("w",encoding="utf-8",newline="") as h:
        w=csv.writer(h,lineterminator="\n"); w.writerow(("particle_id","long_tof_us","short_tof_us","short_minus_long_ns")); w.writerows((i,long_detector[i],short_detector[i],1000*(short_detector[i]-long_detector[i])) for i in paired_ids)
    with plt.rc_context({"font.size":8}):
        fig,ax=plt.subplots(figsize=(160/25.4,90/25.4),layout="constrained"); ax.hist(delta_ns,bins=50,color="#D55E00",alpha=.8); ax.set(xlabel="Short − long pulse-effective TOF (ns)",ylabel="Particles",title="Paired whole-stage eligible cohort (N=695)"); fig.savefig(png_path,dpi=300,facecolor="white"); plt.close(fig)
    config={"schema_version":2,"run_id":a.run_id,"project":PROJECT,"mode":MODE,"project_root":str(a.repo_root.resolve()),"inputs":{"long_checkpoints":str(a.long_checkpoints.resolve()),"short_checkpoints":str(a.short_checkpoints.resolve()),"long_report":str(a.long_report.resolve()),"short_report":str(a.short_report.resolve())},"parameters":{"eligible_count":695,"paired_by_particle_id":True},"artifact_retention":{"policy_version":1,"class":"compact","reason":None}}
    config_path=a.run_dir/"run_config.json"; config_path.write_text(json.dumps(config,indent=2)+"\n",encoding="utf-8")
    publish_manifest(repo_root=a.repo_root,run_config=config_path,manifest_path=a.run_dir/"run_manifest.json",status="success",outputs=[report_path,csv_path,png_path],project=PROJECT,mode=MODE,label="whole-stage short-long comparison")
    print(f"WHOLE_STAGE_SHORT_LONG_COMPARISON=PASS REPORT={report_path}"); return 0

if __name__ == "__main__": raise SystemExit(main())
