"""Diagnose recorded envelopes, linear angle correlations and zero-field waists.

All moments are population moments. Removing a fitted position correlation is
an algebraic regression residual, never measured cooling or a thermal velocity.
No solver, trajectory correction, files, extrapolated real focus or FWHM.
"""
from __future__ import annotations

import math

import numpy as np

COHORTS = ("all_available_alive", "own_extracted_ids", "common_extracted_ids")


def _array(rows: list[dict], fields: tuple[str, ...]) -> np.ndarray | None:
    if not rows or any(row.get(key) is None for row in rows for key in fields):
        return None
    values = np.array([[row[key] for key in fields] for row in rows], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("focus diagnostics require finite supplied states")
    return values


def _decomposition(rows: list[dict], axis: str) -> dict:
    result = dict(axis=axis,count=len(rows),sigma_total_deg=None,sigma_linear_correlated_deg=None,
                  sigma_residual_deg=None,beta_deg_per_mm=None,rho=None,epsilon_mm_mrad=None)
    values = _array(rows,(f"{axis}_mm",f"v{axis}_mm_us","vz_mm_us"))
    if values is None or np.any(values[:,2] == 0):
        return dict(result,reason="empty_or_missing_state_or_zero_vz")
    position = values[:,0]-values[:,0].mean()
    angles = np.degrees(np.arctan2(values[:,1],np.abs(values[:,2])))
    angles -= angles.mean()
    variance, angle_variance = float(position.var()),float(angles.var())
    covariance = float(np.mean(position*angles))
    beta = covariance/variance if variance>0 else None
    correlated = np.zeros(len(rows)) if beta is None else beta*position
    residual = angles-correlated
    result.update(sigma_total_deg=math.sqrt(angle_variance),sigma_linear_correlated_deg=float(correlated.std()),
                  sigma_residual_deg=float(residual.std()),beta_deg_per_mm=beta,
                  rho=covariance/math.sqrt(variance*angle_variance) if variance>0 and angle_variance>0 else None,
                  epsilon_mm_mrad=float(position.std()*np.radians(residual.std())*1000),
                  variance_identity_residual_deg2=float(angle_variance-correlated.var()-residual.var()),
                  reason="constant_position_no_unique_slope" if beta is None else "available")
    return result


def _free_prediction(rows: list[dict], coordinate: str, reference_z_mm: float) -> dict:
    units = "ns" if coordinate == "time" else "mm"
    result = dict(coordinate=coordinate,count=len(rows),reference_z_mm=reference_z_mm,
                  L_star_mm=None,z_focus_mm=None,sigma_at_reference=None,sigma_at_prediction=None,
                  downstream_allowed_best_L_mm=None,downstream_best_sigma=None,sigma_unit=units)
    fields = ("t_us","vz_mm_us") if coordinate == "time" else (f"{coordinate}_mm",f"v{coordinate}_mm_us","vz_mm_us")
    values = _array(rows,fields)
    if values is None or np.any(values[:,-1]>=0):
        return dict(result,reason="empty_or_missing_state_or_not_all_forward_minus_z")
    position = values[:,0]-values[:,0].mean()
    slope = 1/np.abs(values[:,-1]) if coordinate == "time" else values[:,1]/np.abs(values[:,-1])
    slope -= slope.mean()
    scale = 1000 if coordinate == "time" else 1
    result["sigma_at_reference"] = float(position.std()*scale)
    variance = float(slope.var())
    if variance == 0:
        return dict(result,reason="constant_slope_no_unique_waist")
    length = -float(np.mean(position*slope))/variance
    downstream = max(0.,length)
    result.update(L_star_mm=length,z_focus_mm=reference_z_mm-length,
                  sigma_at_prediction=float((position+length*slope).std()*scale),
                  downstream_allowed_best_L_mm=downstream,
                  downstream_best_sigma=float((position+downstream*slope).std()*scale),reason="available")
    return result


def _sampled_minima(statistics: list[dict], case: str, cohort: str) -> list[dict]:
    sets = [set(row["available_ids"]) for row in statistics]
    constant = all(ids==sets[0] for ids in sets[1:])
    eligible = bool(sets[0]) and constant
    covers_cohort = all(row["missing_count"]==0 for row in statistics)
    result = []
    for metric in ("sigma_x_mm","sigma_y_mm","sigma_t_ns"):
        valid = [row for row in statistics if row[metric] is not None]
        minimum = min((row[metric] for row in valid),default=None)
        indices = [i for i,row in enumerate(statistics) if minimum is not None and row[metric]==minimum]
        result.append(dict(case=case,cohort=cohort,metric=metric,value=minimum,
            plane_z_mm=statistics[indices[0]]["plane_z_mm"] if indices else None,
            equal_minimum_planes_z_mm=[statistics[i]["plane_z_mm"] for i in indices],
            boundary_minimum=any(i in (0,len(statistics)-1) for i in indices) if indices else None,
            observed_count=statistics[indices[0]]["observed_count"] if indices else 0,
            available_ids=statistics[indices[0]]["available_ids"] if indices else [],
            cohort_membership_constant=constant,eligible_for_envelope_comparison=eligible and covers_cohort and len(valid)==len(statistics),
            metric_complete_all_planes=len(valid)==len(statistics),
            covers_declared_cohort=covers_cohort,
            interpretation="Sampled minimum only; changing membership cannot identify a focus. No sub-grid fit or downstream extrapolation."))
    return result


def prepare_focus_diagnostics(spatial_cases: list[dict], planes: list[float], common_ids: list[int]) -> dict:
    """Return source-preserving moments and bounded sampled-envelope diagnostics.

    Inputs are existing spatial-crossing cases, mm/us states and ordered planes
    in mm. Missing values produce null moments rather than a trimmed ensemble;
    duplicate identities, unknown IDs and nonfinite supplied values fail.
    """
    if not spatial_cases or not planes or len(set(planes))!=len(planes):
        raise ValueError("nonempty cases and unique ordered observation planes required")
    if any(isinstance(z,bool) or not math.isfinite(z) for z in planes) or planes!=sorted(planes,reverse=True):
        raise ValueError("observation planes must be finite and descending")
    labels = [case["label"] for case in spatial_cases]
    if len(set(labels))!=len(labels) or len(set(common_ids))!=len(common_ids):
        raise ValueError("duplicate case or common identity")
    common = set(common_ids)
    statistics, decompositions, predictions, minima = [], [], [], []
    reference = min(planes)
    for case in spatial_cases:
        mother = set(case["sources"])
        if not set(case["exits"])<=mother or not common<=set(case["exits"]):
            raise ValueError("exit/common IDs do not belong to every source/extracted cohort")
        lookup = {}
        for row in case["states"]:
            z,pid = row["plane_z_mm"],row["particle_id"]
            if z not in planes or pid not in mother or (z,pid) in lookup:
                raise ValueError("spatial state has unknown or duplicate plane/particle identity")
            lookup[z,pid] = row
        for cohort,ids in ((COHORTS[0],mother),(COHORTS[1],set(case["exits"])),(COHORTS[2],common)):
            group_statistics = []
            reference_rows = []
            for z in planes:
                rows = [lookup[z,pid] for pid in sorted(ids) if (z,pid) in lookup and lookup[z,pid]["status"] in {"alive","extracted"}]
                available = [row["particle_id"] for row in rows]
                stat = dict(case=case["label"],cohort=cohort,plane_z_mm=z,cohort_count=len(ids),observed_count=len(rows),
                            available_ids=available,missing_ids=sorted(ids-set(available)),missing_count=len(ids)-len(rows))
                for key,field,scale in (("sigma_x_mm","x_mm",1),("sigma_y_mm","y_mm",1),("sigma_t_ns","t_us",1000)):
                    array = _array(rows,(field,))
                    stat[key] = float(array[:,0].std()*scale) if array is not None else None
                for axis in "xy":
                    angular = _decomposition(rows,axis)
                    stat[f"sigma_theta_{axis}_deg"] = angular["sigma_total_deg"]
                    stat[f"epsilon_{axis}_mm_mrad"] = angular["epsilon_mm_mrad"]
                statistics.append(stat);group_statistics.append(stat)
                if z == reference:
                    reference_rows = rows
            for axis in "xy":
                decompositions.append(dict(case=case["label"],cohort=cohort,reference_z_mm=reference,**_decomposition(reference_rows,axis)))
            for coordinate in ("x","y","time"):
                predictions.append(dict(case=case["label"],cohort=cohort,**_free_prediction(reference_rows,coordinate,reference)))
            minima.extend(_sampled_minima(group_statistics,case["label"],cohort))
    return dict(schema_version=1,role="recorded_beam_focus_diagnostics",case_order=labels,cohorts=list(COHORTS),
        display_cohort=COHORTS[2] if common else COHORTS[0],planes_mm=list(planes),reference_z_mm=reference,
        common_ids=sorted(common),plane_statistics=statistics,exit_angle_decomposition=decompositions,
        field_free_predictions=predictions,sampled_minima=minima,
        metadata=dict(moment_definition="Population SD/covariance (ddof=0); no clipping, tail rejection, fitting of focus or FWHM",
            angle_definition="atan2(vx or vy, abs(vz)); degree; linear correlated part beta*(position-mean), beta=Cov(position,angle)/Var(position)",
            residual_definition="Centered angle minus its fitted linear position dependence; regression residual, not cooling or temperature",
            free_drift_definition="Positive L along -z; x(L)=x0+L*vx/abs(vz), y analogous; t(L)=t0+L/abs(vz). L*=-Cov(value,slope)/Var(slope), z*=reference_z-L*",
            free_drift_scope="Counterfactual field-free straight trajectories with unchanged velocity, no collisions or apertures; never an actual future or upstream focus in nonzero fields",
            sampled_scope="Minima among supplied bounded-interpolation planes only; plane spacing is not focus accuracy or numerical convergence",
            membership_scope="All available alive may change IDs between planes; compare envelopes as a fixed ensemble only when membership is constant; missing and available IDs remain explicit",
            null_policy="Empty/missing states and unidentifiable slopes/correlations are null; measured constant SD=0 is retained"))


def build_focus_figure(prepared: dict):
    """Render prepared diagnostic quantities; one figure-level header/legend only."""
    from matplotlib import pyplot as plt
    colors = ("#0072B2","#E69F00","#009E73","#D55E00")
    markers = ("o","s","^","D")
    lines = ("-","--",":","-.")
    figure,axes = plt.subplots(3,2,figsize=(13,11),constrained_layout=True)
    cohort = prepared["display_cohort"]
    for index,case in enumerate(prepared["case_order"]):
        style = dict(color=colors[index%4],marker=markers[index%4],linestyle=lines[index%4],markersize=3)
        rows = [r for r in prepared["plane_statistics"] if r["case"]==case and r["cohort"]==cohort]
        counts = [row["observed_count"] for row in rows]
        count_label = str(counts[0]) if min(counts)==max(counts) else f"{min(counts)}-{max(counts)}"
        for ax,metric,label in zip(axes[:,0],("sigma_x_mm","sigma_y_mm","sigma_t_ns"),("SD x (mm)","SD y (mm)","Arrival-time SD (ns)"),strict=True):
            ax.plot([r["plane_z_mm"] for r in rows],[np.nan if r[metric] is None else r[metric] for r in rows],**style,label=f"{case} | valid N={count_label}")
            ax.set(xlabel="Recorded observation z (mm); flight toward -z",ylabel=label)
            ax.set_xlim(max(prepared["planes_mm"]),min(prepared["planes_mm"]));ax.grid(alpha=.2)
        for row_index,axis in enumerate("xy"):
            row = next(r for r in prepared["exit_angle_decomposition"] if r["case"]==case and r["cohort"]==cohort and r["axis"]==axis)
            values = [row[key] for key in ("sigma_total_deg","sigma_linear_correlated_deg","sigma_residual_deg")]
            axes[row_index,1].plot(range(3),[np.nan if v is None else v for v in values],**style)
            axes[row_index,1].set(xticks=range(3),xticklabels=["Total","Linear correlated","Regression residual"],ylabel=f"SD {axis}z angle (deg)",title=f"Reference z={prepared['reference_z_mm']:g} mm: {axis}-angle decomposition")
            axes[row_index,1].grid(alpha=.2)
        predictions = [next(r for r in prepared["field_free_predictions"] if r["case"]==case and r["cohort"]==cohort and r["coordinate"]==key) for key in ("x","y","time")]
        axes[2,1].plot(range(3),[np.nan if r["L_star_mm"] is None else r["L_star_mm"] for r in predictions],**style)
    axes[2,1].axhline(0,color="gray",linewidth=.7)
    axes[2,1].set(xticks=range(3),xticklabels=["x waist","y waist","Time waist"],ylabel="Counterfactual L* (mm); positive along -z",title="Zero-field straight-path prediction; not a real focus")
    axes[2,1].grid(alpha=.2)
    handles,labels = axes[0,0].get_legend_handles_labels()
    figure.legend(handles,labels,loc="outside upper center",ncol=2,frameon=False,
        title=f"Recorded envelopes and linear phase-space diagnostics | {cohort}\nDeclared common exit N={len(prepared['common_ids'])}; missing IDs in tables; residual is not cooling; predictions assume zero field")
    return figure
