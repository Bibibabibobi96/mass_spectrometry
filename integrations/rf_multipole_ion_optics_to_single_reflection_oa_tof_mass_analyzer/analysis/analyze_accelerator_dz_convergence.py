"""Manifest-bound paired accelerator-overlay dz convergence analysis."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.peak_metrics import compute_peak_metrics

EVENTS=("accelerator_grid1_forward","local_accelerator_exit","accelerator_focus_forward","reflectron_entrance_forward","reflectron_midgrid_forward","reflectron_turning_point","reflectron_exit_return","detector_crossing")

def analyze(baseline:Path, refined:Path, baseline_manifest:Path, refined_manifest:Path, source:Path, pulse:Path, geometry:Path, output:Path)->dict:
    frames={"dz005":pd.read_csv(baseline),"dz0025":pd.read_csv(refined)}
    expected=set(range(1,1001))
    if any(set(f.particle_id.astype(int))!=expected for f in frames.values()): raise ValueError("paired IDs must be exactly 1..1000")
    manifests={"dz005":json.loads(baseline_manifest.read_text(encoding="utf-8-sig")),"dz0025":json.loads(refined_manifest.read_text(encoding="utf-8-sig"))}
    if manifests["dz0025"].get("status")!="success": raise ValueError("refined child manifest must be success")
    rows=[]; arm=[]
    for event in EVENTS:
        series={}
        for name,frame in frames.items():
            part=frame.loc[frame.event.eq(event),["particle_id","instrument_time_us"]].copy(); part.particle_id=part.particle_id.astype(int); part=part.set_index("particle_id").sort_index()
            if len(part)!=1000: raise ValueError(f"event population differs: {event}")
            series[name]=part.instrument_time_us.astype(float).to_numpy()*1000
            arm.append({"event":event,"arm":name,"mean_time_ns":float(np.mean(series[name])),"sample_sigma_ns":float(np.std(series[name],ddof=1))})
        delta=series["dz0025"]-series["dz005"]
        rows.append({"event":event,"sample_count":1000,"mean_shift_ns":float(np.mean(delta)),"sample_sigma_shift_ns":float(np.std(delta,ddof=1)),"standard_error_ns":float(np.std(delta,ddof=1)/np.sqrt(1000)),"descriptive_normal_95pct_low_ns":float(np.mean(delta)-1.96*np.std(delta,ddof=1)/np.sqrt(1000)),"descriptive_normal_95pct_high_ns":float(np.mean(delta)+1.96*np.std(delta,ddof=1)/np.sqrt(1000)),"rms_shift_ns":float(np.sqrt(np.mean(delta**2)))})
    peaks={}
    for name,frame in frames.items():
        t=frame.loc[frame.event.eq("detector_crossing"),"instrument_time_us"].astype(float).to_numpy(); peak,_=compute_peak_metrics(t,100.0)
        peaks[name]={key:peak[key] for key in ("mean_tof_us","std_tof_ns","direct_fwhm_tof_ns","mass_resolution","significant_kde_modes")}
    focus=next(x for x in rows if x["event"]=="accelerator_focus_forward"); threshold=0.03378871363500548; strong=0.01689435681750274
    decision={"threshold_ns":threshold,"strong_threshold_ns":strong,"mean_shift_pass":abs(focus["mean_shift_ns"])<=threshold,"paired_sigma_pass":focus["sample_sigma_shift_ns"]<=threshold,"strong_mean_shift_pass":abs(focus["mean_shift_ns"])<=strong,"strong_paired_sigma_pass":focus["sample_sigma_shift_ns"]<=strong}
    decision["primary_convergence_pass"]=decision["mean_shift_pass"] and decision["paired_sigma_pass"]
    output.mkdir(parents=True,exist_ok=False); pd.DataFrame(rows).to_csv(output/"checkpoint_paired_convergence.csv",index=False); pd.DataFrame(arm).to_csv(output/"checkpoint_arm_spreads.csv",index=False)
    fig,ax=plt.subplots(1,2,figsize=(12,4.5),constrained_layout=True); x=np.arange(len(EVENTS)); means=np.array([r["mean_shift_ns"] for r in rows]); sig=np.array([r["sample_sigma_shift_ns"] for r in rows]); ax[0].plot(x,means,"o-",label="paired mean"); ax[0].fill_between(x,-threshold,threshold,alpha=.15,label="primary threshold"); ax[0].set(xticks=x,xticklabels=EVENTS,ylabel="dz0025-dz005 (ns)",title="Paired mean shift"); ax[0].tick_params(axis="x",rotation=70); ax[0].legend(); ax[1].plot(x,sig,"o-",label="paired sample sigma"); ax[1].axhline(threshold,color="C1",ls="--",label="primary threshold"); ax[1].set(xticks=x,xticklabels=EVENTS,ylabel="sample sigma (ns)",title="Paired shift dispersion"); ax[1].tick_params(axis="x",rotation=70); ax[1].legend(); fig.savefig(output/"accelerator_dz_convergence.png",dpi=180); plt.close(fig)
    result={"schema_version":1,"role":"rf_oatof_accelerator_dz_paired_numerical_convergence","status":"success","paired_particle_count":1000,"ordered_particle_id_sha256":hashlib.sha256("\n".join(map(str,range(1,1001))).encode()).hexdigest().upper(),"identity_gate":{"source_sha256":file_sha256(source),"pulse_sha256":file_sha256(pulse),"geometry_sha256":file_sha256(geometry),"only_intended_difference":"frontend overlay profile/PA dz 0.05 vs 0.025"},"sources":{"dz005":{"manifest_sha256":file_sha256(baseline_manifest),"checkpoint_sha256":file_sha256(baseline),"manifest_status":manifests["dz005"].get("status")},"dz0025":{"manifest_sha256":file_sha256(refined_manifest),"checkpoint_sha256":file_sha256(refined),"manifest_status":"success"}},"checkpoint_paired_statistics":rows,"focus_decision":decision,"detector_peak_metrics":peaks,"resolution_decision_rule":"R/FWHM/modes are secondary diagnostics and do not determine convergence alone","confidence_interval":"descriptive normal paired-mean interval; no new bootstrap implementation"}
    (output/"accelerator_dz_convergence.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8"); return result

def main():
    p=argparse.ArgumentParser();
    for name in ("baseline","refined","baseline-manifest","refined-manifest","source","pulse","geometry","output"): p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args(); r=analyze(a.baseline,a.refined,a.baseline_manifest,a.refined_manifest,a.source,a.pulse,a.geometry,a.output); print(f"DZ_CONVERGENCE=PASS PRIMARY={r['focus_decision']['primary_convergence_pass']}")
if __name__=="__main__": main()
