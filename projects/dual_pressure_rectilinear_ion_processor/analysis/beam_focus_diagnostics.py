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


def _sampled_minima(statistics: list[dict], case: str, cohort: str,
                    metrics: tuple[str, ...] = ("sigma_x_mm","sigma_y_mm","sigma_t_ns")) -> list[dict]:
    sets = [set(row["available_ids"]) for row in statistics]
    constant = all(ids==sets[0] for ids in sets[1:])
    eligible = bool(sets[0]) and constant
    covers_cohort = all(row["missing_count"]==0 for row in statistics)
    result = []
    for metric in metrics:
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


def _time_distribution(times_us: np.ndarray | None) -> dict:
    result = dict(mean_t_us=None,sigma_t_ns=None,central68_width_ns=None,central90_width_ns=None)
    if times_us is None or not len(times_us):
        return result
    mean = float(times_us.mean())
    centered_ns = (times_us-mean)*1000
    q05,q16,q84,q95 = np.quantile(centered_ns,[.05,.16,.84,.95],method="linear")
    return dict(mean_t_us=mean,sigma_t_ns=float(centered_ns.std()),
                central68_width_ns=float(q84-q16),central90_width_ns=float(q95-q05))


def _time_observable(row: dict, field: str) -> float | None:
    if field == "inverse_abs_vz":
        value = row.get("vz_mm_us")
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("time correlations require finite supplied values")
        return 1/abs(value) if value != 0 else None
    value = row.get(field)
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("time correlations require finite supplied values")
    return value


def _time_correlations(rows: list[dict]) -> dict:
    result = {}
    for label,field in (("x_mm","x_mm"),("y_mm","y_mm"),("vz","vz_mm_us"),("inverse_abs_vz","inverse_abs_vz"),
                        ("Ex_eV","Ex_eV"),("Ez_eV","Ez_eV"),
                        ("total_energy_eV","total_energy_eV"),("theta_y_deg","theta_y_deg")):
        pairs = []
        for row in rows:
            t,value = _time_observable(row,"t_us"),_time_observable(row,field)
            if t is not None and value is not None:
                pairs.append((t,value))
        rho = None
        if len(pairs)>1:
            array = np.asarray(pairs)
            centered = array-array.mean(axis=0)
            variance = np.mean(centered**2,axis=0)
            if np.all(variance>0):
                rho = float(np.mean(centered[:,0]*centered[:,1])/np.sqrt(variance.prod()))
        result[f"rho_t_{label}"] = rho
        result[f"rho_t_{label}_matched_count"] = len(pairs)
    return result


def _time_drift_rows(rows: list[dict], lengths: list[float]) -> tuple[dict,list[dict]]:
    values = _array(rows,("t_us","vz_mm_us"))
    valid = values is not None and bool(np.all(values[:,1]<0))
    matched = sum(row.get("t_us") is not None and row.get("vz_mm_us") is not None
                  and float(row["vz_mm_us"])<0 for row in rows)
    coefficients = dict(paired_forward_count=matched,paired_complete=valid,
        variance_a_ns2=None,variance_b_ns2_per_mm=None,variance_c_ns2_per_mm2=None,
        unconstrained_L_star_mm=None,downstream_L_star_mm=None,
        downstream_min_sigma_t_ns=None,unique_time_waist=None)
    if valid:
        centered = (values[:,0]-values[:,0].mean())*1000
        inverse_speed = 1000/np.abs(values[:,1])  # ns/mm; vz input is mm/us.
        centered_inverse = inverse_speed-inverse_speed.mean()
        a,b,c = float(centered.var()),float(2*np.mean(centered*centered_inverse)),float(centered_inverse.var())
        length = -b/(2*c) if c>0 else None
        downstream = max(0.,length) if length is not None else 0.
        coefficients.update(variance_a_ns2=a,variance_b_ns2_per_mm=b,variance_c_ns2_per_mm2=c,
            unconstrained_L_star_mm=length,downstream_L_star_mm=downstream,
            downstream_min_sigma_t_ns=float((centered+downstream*centered_inverse).std()),
            unique_time_waist=c>0)
    curves = []
    for length in lengths:
        item = dict(drift_length_mm=length,predicted_sigma_t_ns=None,predicted_central68_width_ns=None,
                    predicted_central90_width_ns=None,quadratic_variance_ns2=None,variance_identity_residual_ns2=None,
                    paired_forward_count=matched,paired_complete=valid)
        if valid:
            centered_prediction = centered+length*centered_inverse
            q05,q16,q84,q95 = np.quantile(centered_prediction,[.05,.16,.84,.95],method="linear")
            variance = a+b*length+c*length**2
            item.update(predicted_sigma_t_ns=float(centered_prediction.std()),
                predicted_central68_width_ns=float(q84-q16),predicted_central90_width_ns=float(q95-q05),
                quadratic_variance_ns2=variance,
                variance_identity_residual_ns2=float(centered_prediction.var()-variance))
        curves.append(item)
    return coefficients,curves


def _time_interval_variances(group: list[dict], lookup: dict) -> list[dict]:
    result = []
    for before,after in zip(group,group[1:]):
        candidate_ids = sorted(set(before["available_ids"]) & set(after["available_ids"]))
        matched = [pid for pid in candidate_ids if lookup[before["plane_z_mm"],pid].get("t_us") is not None
                   and lookup[after["plane_z_mm"],pid].get("t_us") is not None]
        row = dict(case=before["case"],cohort=before["cohort"],before_z_mm=before["plane_z_mm"],after_z_mm=after["plane_z_mm"],
            cohort_count=before["cohort_count"],paired_count=len(matched),matched_ids=matched,
            missing_before_ids=before["missing_ids"],missing_after_ids=after["missing_ids"],
            unpaired_available_ids=sorted((set(before["available_ids"]) | set(after["available_ids"]))-set(matched)),
            complete_declared_cohort=len(matched)==before["cohort_count"],
            var_t_before_ns2=None,var_delta_t_ns2=None,twice_cov_t_before_delta_ns2=None,var_t_after_ns2=None,
            variance_change_ns2=None,closure_residual_ns2=None,mean_delta_t_ns=None)
        if matched:
            a = np.array([lookup[before["plane_z_mm"],pid]["t_us"] for pid in matched])
            b = np.array([lookup[after["plane_z_mm"],pid]["t_us"] for pid in matched])
            if np.any(b<a):
                raise ValueError("paired arrival times contradict downstream plane order")
            delta = (b-a)*1000
            ac,bc,dc = (a-a.mean())*1000,(b-b.mean())*1000,delta-delta.mean()
            va,vd,vb = float(ac.var()),float(dc.var()),float(bc.var())
            cross = float(2*np.mean(ac*dc))
            row.update(var_t_before_ns2=va,var_delta_t_ns2=vd,twice_cov_t_before_delta_ns2=cross,
                var_t_after_ns2=vb,variance_change_ns2=vb-va,closure_residual_ns2=vb-va-vd-cross,
                mean_delta_t_ns=float(delta.mean()))
        result.append(row)
    return result


def prepare_time_focus_diagnostics(spatial_cases: list[dict], planes: list[float],
                                   common_ids: list[int], contract: dict) -> dict:
    """Prepare paired time widths/correlations and declared zero-field drifts.

    Quantile widths retain all IDs (linear empirical quantiles); they are not
    Gaussian conversions. Per-ID predictions are published only at min(planes).
    Per-plane predictions use complete observed t/vz pairs, never silently trim
    a group with missing or non-forward velocity. No real downstream flight.
    """
    import copy
    if not isinstance(contract,dict) or set(contract)!={"drift_lengths_mm"}:
        raise ValueError("time-focus contract requires only drift_lengths_mm")
    lengths = contract.get("drift_lengths_mm") if isinstance(contract,dict) else None
    if not isinstance(lengths,list) or not lengths or any(isinstance(v,bool) or not isinstance(v,(int,float))
            or not math.isfinite(v) or v<0 for v in lengths):
        raise ValueError("explicit finite nonnegative drift_lengths_mm list required")
    if len(set(lengths))!=len(lengths):
        raise ValueError("declared drift lengths must be unique")
    base = prepare_focus_diagnostics(spatial_cases,planes,common_ids)
    cohorts = list(COHORTS[1:])
    statistics, predictions, particles, minima, intervals = [], [], [], [], []
    count_keys = ("case","cohort","plane_z_mm","cohort_count","observed_count","available_ids","missing_ids","missing_count")
    by_case = {case["label"]:case for case in spatial_cases}
    lookups = {case["label"]:{(r["plane_z_mm"],r["particle_id"]):r for r in case["states"]} for case in spatial_cases}
    for label in base["case_order"]:
        for cohort in cohorts:
            group = []
            original = [r for r in base["plane_statistics"] if r["case"]==label and r["cohort"]==cohort]
            for counts in original:
                z = counts["plane_z_mm"]
                rows = [lookups[label][z,pid] for pid in counts["available_ids"]]
                values = _array(rows,("t_us",))
                coefficients,curves = _time_drift_rows(rows,lengths)
                stat = {key:counts[key] for key in count_keys}
                stat.update(_time_distribution(values[:,0] if values is not None else None),
                            **_time_correlations(rows),**coefficients)
                statistics.append(stat);group.append(stat)
                prediction_keys = ("case","cohort","plane_z_mm","cohort_count","observed_count","missing_count")
                predictions.extend(dict(**{key:counts[key] for key in prediction_keys},**curve) for curve in curves)
                if z == base["reference_z_mm"]:
                    ids = sorted(by_case[label]["exits"]) if cohort==COHORTS[1] else sorted(common_ids)
                    available = {row["particle_id"]:row for row in rows}
                    for pid in ids:
                        row = available.get(pid)
                        valid = row is not None and row.get("t_us") is not None and row.get("vz_mm_us") is not None and row["vz_mm_us"]<0
                        for length in lengths:
                            particles.append(dict(case=label,cohort=cohort,particle_id=pid,reference_z_mm=z,
                                drift_length_mm=length,predicted_z_mm=z-length,
                                reference_t_us=row.get("t_us") if row else None,reference_vz_mm_us=row.get("vz_mm_us") if row else None,
                                predicted_t_us=row["t_us"]+length/abs(row["vz_mm_us"]) if valid else None,
                                availability="available" if valid else "missing_reference_state_or_not_forward"))
            minima.extend(_sampled_minima(group,label,cohort,("sigma_t_ns","central68_width_ns","central90_width_ns")))
            intervals.extend(_time_interval_variances(group,lookups[label]))
    return dict(schema_version=1,role="recorded_time_focus_diagnostics",contract=copy.deepcopy(contract),
        case_order=base["case_order"],cohorts=cohorts,common_ids=base["common_ids"],
        display_cohort=COHORTS[2] if common_ids else COHORTS[1],reference_z_mm=base["reference_z_mm"],
        planes_mm=list(planes),drift_lengths_mm=list(lengths),plane_time_statistics=statistics,
        plane_drift_predictions=predictions,
        reference_plane_predictions=[r for r in predictions if r["plane_z_mm"]==base["reference_z_mm"]],
        reference_particle_predictions=particles,sampled_minima=minima,
        time_interval_variance_rows=intervals,source_counts={case["label"]:len(case["sources"]) for case in spatial_cases},
        metadata=dict(moment_definition="Population SD, ddof=0; all observed cohort IDs retained. No tail rejection or Gaussian/FWHM conversion.",
            quantiles="NumPy quantile(method='linear'): central68=q84-q16; central90=q95-q05; all observations participate",
            correlations="Pearson population correlation; constant/empty pair is null; per-observable matched counts declared; missing energy fields remain null, not inferred",
            energy_fields_queried=["Ex_eV","Ez_eV","total_energy_eV"],
            energy_fields_available_by_case={case["label"]:[field for field in ("Ex_eV","Ez_eV","total_energy_eV")
                if any(row.get(field) is not None for row in case["states"])] for case in spatial_cases},
            prediction="Independent counterfactual from each plane: t_i(L)=t_i+L/abs(vz_i); L mm, vz mm/us, t absolute instrument us. No field, collision or aperture.",
            quadratic="Var_t_ns2(L)=A+B*L+C*L^2; A=Var(t_ns), B=2Cov(t_ns,1000/abs(vz)), C=Var(1000/abs(vz)); downstream L*=max(0,-B/(2C))",
            constant_speed="If C=0 there is no unique time waist; downstream_L_star=0 is a representative minimizer, not a focal location",
            reference="Most downstream recorded plane min(planes), explicitly declared; per-ID predictions only from that reference",
            prediction_identity="Join plane/reference drift curves to plane_time_statistics on case/cohort/plane_z_mm for available/missing ID lists; do not duplicate those lists per declared length",
            missing="All declared reference cohort IDs retained even when prediction null; incomplete paired groups produce null predicted widths; paired_forward_count is explicit",
            interval_variance="Same-ID adjacent-plane pairs: Var(t_b)=Var(t_a)+Var(delta_t)+2Cov(t_a,delta_t), ns2. Matched and missing IDs explicit; SDs are never added; this is not independent electrode causal attribution.",
            sampled_scope=base["metadata"]["sampled_scope"],membership_scope=base["metadata"]["membership_scope"],
            claim="Recorded along-path time widths plus zero-field predictions; output sigma_t need not be the minimum; no real downstream focus or resolution qualification"))


def build_time_focus_figure(prepared: dict):
    """Compare recorded widths with explicitly separate zero-field predictions."""
    from matplotlib import pyplot as plt
    colors = ("#0072B2","#E69F00","#009E73","#D55E00")
    markers = ("o","s","^","D")
    lines = ("-","--",":","-.")
    figure,axes = plt.subplots(3,2,figsize=(13,11),constrained_layout=True)
    cohort = prepared["display_cohort"]
    metrics = (("sigma_t_ns","predicted_sigma_t_ns","Population SD (ns)"),
               ("central68_width_ns","predicted_central68_width_ns","Central 68% width (ns)"),
               ("central90_width_ns","predicted_central90_width_ns","Central 90% width (ns)"))
    for index,case in enumerate(prepared["case_order"]):
        real = [r for r in prepared["plane_time_statistics"] if r["case"]==case and r["cohort"]==cohort]
        prediction = sorted((r for r in prepared["reference_plane_predictions"] if r["case"]==case and r["cohort"]==cohort),key=lambda r:r["drift_length_mm"])
        counts = [r["observed_count"] for r in real]
        count_label = str(counts[0]) if min(counts)==max(counts) else f"{min(counts)}-{max(counts)}"
        style = dict(color=colors[index%4],marker=markers[index%4],linestyle=lines[index%4],markersize=3)
        for row,(observed_key,predicted_key,label) in enumerate(metrics):
            axes[row,0].plot([r["plane_z_mm"] for r in real],[np.nan if r[observed_key] is None else r[observed_key] for r in real],**style,label=f"{case} | observed N={count_label}")
            axes[row,1].plot([r["drift_length_mm"] for r in prediction],[np.nan if r[predicted_key] is None else r[predicted_key] for r in prediction],**style)
            axes[row,0].set(xlabel="Recorded plane z (mm); flight toward -z",ylabel=label,
                            xlim=(max(prepared["planes_mm"]),min(prepared["planes_mm"])))
            axes[row,1].set(xlabel="Declared zero-field drift L (mm); forward -z",ylabel=label)
            for ax in axes[row]:
                ax.grid(alpha=.2)
    axes[0,0].set_title("Actual recorded crossings; sampled interval only")
    axes[0,1].set_title(f"Zero-field prediction from z={prepared['reference_z_mm']:g} mm; not real downstream flight")
    handles,labels = axes[0,0].get_legend_handles_labels()
    figure.legend(handles,labels,loc="outside upper center",ncol=2,frameon=False,
        title=f"Time focus and full-tail time widths | {cohort}\nDeclared common N={len(prepared['common_ids'])}; quantile widths use all observations; predicted propagation assumes zero field")
    return figure
