"""Actual local-field crossing diagnostics, with independent virtual apertures.

Instrument times are us, velocities mm/us. No ballistic extrapolation, tail
removal, cooling claim or whole-instrument resolving power is inferred.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_transport_snapshots as lifecycle


def _vector(row: dict, velocity: bool = False) -> np.ndarray:
    return np.array([row[f"v{a}_mm_us" if velocity else f"{a}_mm"] for a in "xyz"], dtype=float)


def normal_crossing(track: list[dict], plane: dict, maximum_gap_us: float) -> dict | None:
    """First forward intersection within actual adjacent saved-state support."""
    origin, normal = np.array(plane["origin_mm"]), np.array(plane["normal"])
    for first, second in zip(track, track[1:]):
        gap = second["t_us"] - first["t_us"]
        serial = 8 * np.finfo(float).eps * max(abs(first["t_us"]), abs(second["t_us"]))
        if gap <= 0 or gap > maximum_gap_us + serial:
            continue
        a, b = float((_vector(first) - origin) @ normal), float((_vector(second) - origin) @ normal)
        if not a <= 0 <= b or b <= a:
            continue
        fraction = -a / (b - a)
        row = {key: float(first[key] + fraction * (second[key] - first[key])) for key in local.STATE_FIELDS}
        if float(_vector(row, True) @ normal) <= 0:
            continue
        row.update(particle_id=first["particle_id"], interpolation_fraction=fraction,
                   bracket_gap_us=gap, lower_raw_line=first.get("raw_line_number"),
                   upper_raw_line=second.get("raw_line_number"), lower_raw_path=first.get("raw_path"),
                   upper_raw_path=second.get("raw_path"), lower_raw_sha256=first.get("raw_sha256"),
                   upper_raw_sha256=second.get("raw_sha256"))
        return row
    return None


def time_variance_budget(first: dict[int, dict], second: dict[int, dict], declared_ids: set[int]) -> dict:
    """Var(tb)=Var(ta)+Var(tb-ta)+2Cov(ta,tb-ta), population ns²."""
    ids = sorted(declared_ids & first.keys() & second.keys())
    a = np.array([first[i]["t_us"] for i in ids]) * 1000
    b = np.array([second[i]["t_us"] for i in ids]) * 1000
    if not ids:
        return dict(matched_count=0, available_ids=[], missing_ids=sorted(declared_ids),
                    variance_a_ns2=None, variance_increment_ns2=None, twice_covariance_ns2=None,
                    variance_b_ns2=None, closure_residual_ns2=None)
    delta = b - a
    va, vd, vb = float(np.var(a)), float(np.var(delta)), float(np.var(b))
    cov2 = float(2 * np.mean((a - a.mean()) * (delta - delta.mean())))
    return dict(matched_count=len(ids), available_ids=ids, missing_ids=sorted(declared_ids - set(ids)),
                variance_a_ns2=va, variance_increment_ns2=vd, twice_covariance_ns2=cov2,
                variance_b_ns2=vb, closure_residual_ns2=vb - va - vd - cov2)


def aperture_accepts(x: float, y: float, width: float, shape: str, x_half_width: float | None) -> bool:
    """Closed geometric aperture boundary; width is radius or y half-width."""
    if shape == "circle":
        return x*x + y*y <= width*width
    if shape == "y_slit":
        return abs(y) <= width and (x_half_width is None or abs(x) <= x_half_width)
    raise ValueError("Unknown aperture shape")


def _aperture_frame(contract: dict) -> str:
    """Read frozen schema1 normals and explicitly framed schema2/3 selectors."""
    version = contract["schema_version"]
    aperture = contract["aperture_comparison"]
    if version == 1:
        return "reference_normal"
    if version not in {2, 3, 4, 5} or aperture.get("frame") not in {"global_z", "reference_normal"}:
        raise ValueError("Contour aperture comparison requires explicit global_z/reference_normal frame")
    return aperture["frame"]


def _selector_plane(reference: dict, aperture: dict, frame: str) -> tuple[dict, np.ndarray]:
    """Return one shared plane/basis and the declared world-center projection."""
    plane = reference if frame == "reference_normal" else dict(reference, origin_mm=[0., 0., reference["global_z_mm"]],
                                                               normal=[0., 0., -1.], e_x=[1., 0., 0.], e_y=[0., 1., 0.])
    center = np.array([aperture["center_x_mm"], aperture["center_y_mm"], reference["global_z_mm"]], dtype=float)
    normal = np.array(plane["normal"])
    center -= np.dot(center-np.array(plane["origin_mm"]), normal)*normal
    return plane, center


def _statistics(rows: list[dict], mass: float, frame: dict | None = None) -> dict:
    result = local.compute_plane_statistics(rows, mass)
    time = np.array([r["t_us"] for r in rows])
    for name, low, high in (("central68_ns", .16, .84), ("central90_ns", .05, .95)):
        result[name] = float(np.diff(np.quantile(time, [low, high]))[0]*1000) if len(time) else None
    if frame:
        n, ex, ey, origin = (np.array(frame[key]) for key in ("normal", "e_x", "e_y", "origin_mm"))
        for axis, direction in (("x", ex), ("y", ey)):
            position = np.array([float((_vector(r)-origin) @ direction) for r in rows])
            angle = np.array([math.degrees(math.atan2(float(_vector(r, True) @ direction), float(_vector(r, True) @ n))) for r in rows])
            result[f"sigma_local_{axis}_mm"] = float(np.std(position)) if rows else None
            result[f"sigma_local_theta_{axis}_deg"] = float(np.std(angle)) if rows else None
    return result


def _sampled_minima(rows: list[dict], planes: list[dict], case_id: str, frame: str, cohort: str,
                    *, metric: str = "time_sigma_ns") -> list[dict]:
    """Separate survivor observations from minima on contiguous complete support."""
    if metric not in {"time_sigma_ns", "sigma_x_mm", "sigma_y_mm", "sigma_local_x_mm", "sigma_local_y_mm"}:
        raise ValueError("Unsupported sampled focus metric")
    by_name = {r["plane"]: r for r in rows}
    ordered = [by_name[p["name"]] for p in planes]
    complete = [r["count"] >= 2 and not r["missing_ids"] and r[metric] is not None for r in ordered]
    segments: list[list[int]] = []
    for index, eligible in enumerate(complete):
        if eligible:
            if index == 0 or not complete[index-1]:
                segments.append([])
            segments[-1].append(index)
    intervals = [dict(first_plane=planes[s[0]]["name"], last_plane=planes[s[-1]]["name"],
                      first_z_mm=planes[s[0]]["z_mm"], last_z_mm=planes[s[-1]]["z_mm"],
                      plane_count=len(s)) for s in segments]
    uncovered = [planes[i]["name"] for i, eligible in enumerate(complete) if not eligible]
    spacings = [abs(a["z_mm"]-b["z_mm"]) for a, b in zip(planes, planes[1:])]
    base = dict(case_id=case_id, frame=frame, cohort=cohort, metric=metric,
                metric_unit="ns" if metric == "time_sigma_ns" else "mm",
                declared_count=ordered[0]["declared_count"] if ordered else 0,
                complete_intervals=intervals, incomplete_or_insufficient_planes=uncovered,
                complete_cohort_covers_full_scan=bool(complete) and all(complete),
                scan_plane_spacings_mm=spacings,
                position_limit="Sampled-plane minimum only; spacing is not focal-position accuracy or numerical convergence; no extrapolation")

    def record(index: int | None, kind: str, interval: list[int] | None = None) -> dict:
        row = ordered[index] if index is not None else None
        eligible = kind == "fixed_complete_cohort_segment_minimum" and row is not None
        local_spacings = ([spacings[index-1]] if index is not None and index > 0 else []) + ([spacings[index]] if index is not None and index < len(spacings) else [])
        return dict(base, minimum_kind=kind, available=row is not None,
                    plane=row["plane"] if row else None, z_mm=planes[index]["z_mm"] if row else None,
                    minimum_value=row[metric] if row else None,
                    sigma_t_ns=row["time_sigma_ns"] if row else None,
                    central68_ns=row["central68_ns"] if row else None,
                    central90_ns=row["central90_ns"] if row else None,
                    count=row["count"] if row else 0, missing_ids=row["missing_ids"] if row else None,
                    at_scan_boundary=index in (0, len(planes)-1) if index is not None else None,
                    at_complete_interval_boundary=index in (interval[0], interval[-1]) if interval else None,
                    at_boundary=index in (interval[0], interval[-1]) if interval else None,
                    neighboring_plane_spacings_mm=local_spacings,
                    eligible_complete_cohort=eligible,
                    interpretation=("Observed available-arrival minimum; changing membership/singletons do not establish a focus"
                                    if kind == "available_arrivals_observed_minimum" else
                                    "Fixed complete-cohort sampled minimum within stated contiguous interval; boundary minimum does not locate an internal focus"))

    observed = [i for i, r in enumerate(ordered) if r[metric] is not None and r["count"] > 0]
    result = [record(min(observed, key=lambda i: ordered[i][metric]) if observed else None,
                     "available_arrivals_observed_minimum")]
    if not segments:
        result.append(record(None, "fixed_complete_cohort_segment_minimum"))
    else:
        best_indices = [min(s, key=lambda i: ordered[i][metric]) for s in segments]
        primary = min(best_indices, key=lambda i: ordered[i][metric])
        for segment, best in zip(segments, best_indices):
            result.append(dict(record(best, "fixed_complete_cohort_segment_minimum", segment),
                               primary_complete_minimum=best == primary,
                               interval_first_plane=planes[segment[0]]["name"],
                               interval_last_plane=planes[segment[-1]]["name"]))
    return result


def _load_case_events(run: Path, spec: dict, planes: list[dict]) -> dict:
    """Validate the complete source/event cohort without reading dense samples."""
    directory = run / spec["directory"]
    events = local._load_rows(directory / "events.csv", states=True)
    births = local._unique([r for r in events if r["event"] == "birth"], "births")
    terminals = local._unique([r for r in events if r["event"] == "terminal"], "terminals")
    census = local._unique(local._load_rows(run / spec["source_census_csv"]), "mother census")
    source = local._unique(local._load_rows(run / spec["source_csv"]), "component source")
    if len(census) != spec["mother_count"] or len(births) != spec["source_count"] or births.keys() != terminals.keys() or births.keys() != source.keys() or not births.keys() <= census.keys():
        raise ValueError("Source/birth/terminal/mother census mismatch")
    local._validate_source([dict(births=births, case=spec)], source, spec["mass_u"])
    names = {p["name"] for p in planes}
    if any(r["event"] not in {"birth", "plane", "terminal"} or (r["event"] == "plane" and r["reason"] not in names) for r in events):
        raise ValueError("Unknown event or observation plane")
    by_plane = {p["name"]: local._unique([r for r in events if r["event"] == "plane" and r["reason"] == p["name"]], p["name"]) for p in planes}
    for p in planes:
        for row in by_plane[p["name"]].values():
            serial = 8*np.finfo(float).eps*max(1., abs(p["z_mm"]))
            if row["vz_mm_us"] >= 0 or abs(row["z_mm"]-p["z_mm"]) > serial:
                raise ValueError("Global plane coordinate/direction mismatch")
    if any(r["reason"] not in {"reached_exit", "solver_stop", "timeout"} for r in terminals.values()):
        raise ValueError("Unknown terminal reason")
    if set(by_plane["p1_exit"]) != {i for i, r in terminals.items() if r["reason"] == "reached_exit"}:
        raise ValueError("Exit/terminal disagreement")
    for row in events:
        pid = row["particle_id"]
        if pid not in births or not births[pid]["t_us"] <= row["t_us"] <= terminals[pid]["t_us"]:
            raise ValueError("Event outside canonical particle lifetime")
    return dict(case=spec, births=births, terminals=terminals, planes=by_plane, census=census, events=events)


def _load_case(run: Path, spec: dict, planes: list[dict]) -> dict:
    cohort = _load_case_events(run, spec, planes)
    births, terminals, by_plane, census = (cohort[k] for k in ("births", "terminals", "planes", "census"))
    directory = run / spec["directory"]
    events = cohort["events"]
    samples = local._load_rows(directory / "samples.csv", states=True)
    tracks, raw_tracks, overshoots = {}, {}, []
    for pid, birth in births.items():
        terminal = terminals[pid]
        observations = [r for r in samples if r["particle_id"] == pid]
        if any(r["t_us"] < birth["t_us"] for r in observations):
            raise ValueError("Sample before birth")
        late = [r for r in observations if r["t_us"] > terminal["t_us"]]
        for row in late:
            serial = 8*np.finfo(float).eps*max(abs(row["t_us"]), abs(terminal["t_us"]))
            delta = row["t_us"]-terminal["t_us"]
            bounded = (len(late) == 1 and terminal["reason"] == "reached_exit"
                       and row is observations[-1] and row["vz_mm_us"] < 0
                       and row["z_mm"] < terminal["z_mm"]
                       and delta <= spec["maximum_step_us"]+serial)
            overshoots.append(dict(row, case_id=spec["case_id"], terminal_t_us=terminal["t_us"],
                                   delta_after_terminal_us=delta, maximum_step_us=spec["maximum_step_us"],
                                   serialization_bound_us=serial, bounded_interpolation_halo=bounded,
                                   qualification="actual observation retained; excluded from canonical lifetime and normal crossings"))
        raw_tracks[pid] = sorted([birth, *observations, terminal], key=lambda r: r["t_us"])
        lifetime = [birth, *[r for r in observations if r["t_us"] <= terminal["t_us"]], terminal]
        lifetime.sort(key=lambda r: r["t_us"])
        tracks[pid] = list({r["t_us"]: r for r in lifetime}.values())
    for row in events:
        pid = row["particle_id"]
        if pid not in births or not births[pid]["t_us"] <= row["t_us"] <= terminals[pid]["t_us"]:
            raise ValueError("Event outside canonical particle lifetime")
    if any(r["particle_id"] not in births for r in samples):
        raise ValueError("Sample with unknown particle ID")
    return dict(case=spec, births=births, terminals=terminals, planes=by_plane, tracks=tracks,
                census=census, raw_tracks=raw_tracks, overshoots=overshoots)


def _reference_planes(reference: dict, planes: list[dict]) -> list[dict]:
    result = []
    for p in planes:
        rows = list(reference["planes"][p["name"]].values())
        if not rows:
            raise ValueError("Reference case has no arrivals at a declared plane")
        origin = np.mean([_vector(r) for r in rows], axis=0)
        n = np.mean([_vector(r, True) for r in rows], axis=0)
        n /= np.linalg.norm(n)
        ex = np.array([1., 0., 0.]) - n[0]*n
        if np.linalg.norm(ex) == 0:
            raise ValueError("Reference velocity parallel to transverse-x axis")
        ex /= np.linalg.norm(ex)
        ey = np.cross(ex, n)  # +y for n=-z, ex=+x.
        result.append(dict(plane=p["name"], global_z_mm=p["z_mm"], origin_mm=origin.tolist(),
                           normal=n.tolist(), e_x=ex.tolist(), e_y=ey.tolist(),
                           reference_case_id=reference["case"]["case_id"], reference_count=len(rows)))
    return result


def _numerical_label(spec: dict) -> str:
    return f"h={','.join(f'{p:g}' for p in spec['pitch_mm'])} mm; dt <= {spec['maximum_step_us']*1000:g} ns"


def contour_projection_paths(resolved: dict) -> dict[str, Path]:
    """Locate the compiler's frozen per-source held-voltage projections.

    The producer assigns source_01 etc by first source_run occurrence. Absolute
    case directories retain the original producer's simion/case_XX location in
    recorded analysis. Paths locate evidence; their spelling is not physics.
    """
    source_order = list(dict.fromkeys(case["source_run"] for case in resolved["cases"]))
    paths = {}
    for index, source in enumerate(source_order, 1):
        roots = set()
        for case in resolved["cases"]:
            if case["source_run"] != source:
                continue
            directory = Path(case["directory"])
            if not directory.is_absolute() or directory.parent.name != "simion":
                raise ValueError("contour case directory must identify the absolute producer simion/case location")
            roots.add(directory.parent.parent)
        if len(roots) != 1:
            raise ValueError("one original contour producer required per frozen source")
        paths[source] = roots.pop()/"inputs/native_sources"/f"source_{index:02d}"/"provider_voltage_projection.json"
    return paths


def _comparison_identity(run: Path, resolved: dict, spec: dict) -> dict:
    """Compare actual frozen physics/source/pose, never labels or field paths.

    Historical frozen nine-case inputs predate the optional physical-aperture
    field; absence denotes no added plate and is independently represented by
    the actual CSG. No absent file or hash is replaced with a synthetic identity.
    """
    prepared = json.loads((run/Path(spec["directory"])/"geometry.json").read_text(encoding="utf-8-sig"))
    geometry = copy.deepcopy(prepared["geometry"])
    for aperture in geometry.get("aperture_electrodes", []):
        aperture.pop("grid_representation", None)
        # The longer axial GEM cutting tool removes coincident endcaps; it is
        # compiler metadata, not a change to the finite physical CSG hole.
        aperture.pop("gem_subtraction", None)
    projection = json.loads(contour_projection_paths(resolved)[spec["source_run"]].read_text(encoding="utf-8-sig"))
    identity = {key: spec[key] for key in ("distance_mm", "exit_z_mm", "delta_z_mm", "gap_mm",
        "source_epoch_us", "pulse_time_us", "mass_u", "charge_state", "source_count", "mother_count")}
    identity.update(source_sha256=file_sha256(run/Path(spec["source_csv"])),
                    census_sha256=file_sha256(run/Path(spec["source_census_csv"])),
                    source_registration=resolved["contract"]["source_registration"],
                    physical_aperture=spec.get("physical_aperture"), geometry=geometry,
                    prism_voltage_v=resolved["prism_voltage_v"],
                    held_ip_voltage={key: projection[key] for key in ("values_v15", "evaluation_time_us", "basis")})
    return identity


def _numerical_case_pairs(run: Path, resolved: dict, cases: list[dict]) -> list[tuple[dict, dict]]:
    identities = [_comparison_identity(run, resolved, case["case"]) for case in cases]
    return [(first, second) for i, first in enumerate(cases) for j, second in enumerate(cases[i+1:], i+1)
            if identities[i] == identities[j]]


def numerical_comparison_rows(pairs: list[tuple[dict, dict]], planes: list[dict]) -> list[dict]:
    """Return existing same-ID event differences for physics-qualified case pairs.

    Preserve pair/plane order and sorted common IDs; missing arrivals remain in
    each input case for the caller's census/loss tables, never synthesized here.
    """
    comparisons = []
    for first, second in pairs:
        for p in planes:
            a, b = first["planes"][p["name"]], second["planes"][p["name"]]
            for pid in sorted(a.keys() & b.keys()):
                comparisons.append(dict(case_a=first["case"]["case_id"], case_b=second["case"]["case_id"], plane=p["name"], particle_id=pid,
                                        pitch_a_mm=first["case"]["pitch_mm"], pitch_b_mm=second["case"]["pitch_mm"],
                                        maximum_step_a_us=first["case"]["maximum_step_us"], maximum_step_b_us=second["case"]["maximum_step_us"],
                                        delta_t_ns=(b[pid]["t_us"]-a[pid]["t_us"])*1000,
                                        **{f"delta_{k}": b[pid][k]-a[pid][k] for k in local.STATE_FIELDS[1:]}))
    return comparisons


def _zero_field_tables(cases: list[dict], planes: list[dict], common: set[int]) -> dict:
    """Keep counterfactual free propagation and actual survivor pairing separate."""
    statistics, particles, decisions, minima, paired, deltas = [], [], [], [], [], []
    for case in cases:
        spec = case["case"]
        own = set(case["births"])
        for plane in planes:
            result = local.project_field_free_births([case["births"][pid] for pid in sorted(own)], plane["z_mm"])
            reference = {r["particle_id"]: r for r in result["crossings"]}
            actual = case["planes"][plane["name"]]
            base = dict(case_id=spec["case_id"], label=spec["label"], frame="global_z",
                        plane=plane["name"], z_mm=plane["z_mm"], mother_count=len(case["census"]))
            by_id = {r["particle_id"]: r for r in result["particle_decisions"]}
            for pid in sorted(case["census"]):
                decision = by_id.get(pid, dict(particle_id=pid, status="upstream_not_handed_off",
                                              reason="no_actual_birth_reference_unavailable"))
                decisions.append(dict(base, **decision, propagation_model="zero_field_reference",
                                      own_extracted_id=pid in own, common_extracted_id=pid in common))
            for pid, row in reference.items():
                particles.append(dict(row, **base, propagation_model="zero_field_reference",
                                      own_extracted_id=pid in own, common_extracted_id=pid in common))
            for cohort, ids in (("own_extracted_ids", own), ("common_extracted_ids", common)):
                available = ids & reference.keys()
                statistics.append(dict(base, cohort=cohort, propagation_model="zero_field_reference",
                    declared_count=len(ids), available_ids=sorted(available), missing_ids=sorted(ids-available),
                    **_statistics([reference[i] for i in sorted(available)], spec["mass_u"])))
                matched = ids & actual.keys() & reference.keys()
                counts = dict(base, cohort=cohort, declared_count=len(ids),
                    available_ids=sorted(matched), missing_ids=sorted(ids-matched),
                    actual_available_count=len(ids & actual.keys()), reference_available_count=len(available),
                    actual_missing_ids=sorted(ids-actual.keys()), reference_missing_ids=sorted(ids-reference.keys()),
                    paired_count=len(matched))
                for model, rows in (("actual_local_field", actual), ("zero_field_reference", reference)):
                    paired.append(dict(counts, propagation_model=model,
                        **_statistics([rows[i] for i in sorted(matched)], spec["mass_u"])))
            for pid in sorted(own & actual.keys() & reference.keys()):
                a, b = actual[pid], reference[pid]
                values = {f"{name}_{key}": row[key] for name, row in (("actual", a), ("zero_field", b))
                          for key in local.STATE_FIELDS if key != "potential_v"}
                deltas.append(dict(base, particle_id=pid, own_extracted_id=True, common_extracted_id=pid in common,
                    delta_t_ns=(a["t_us"]-b["t_us"])*1000,
                    **{f"delta_{axis}_mm": a[f"{axis}_mm"]-b[f"{axis}_mm"] for axis in "xyz"}, **values))
        for cohort in ("own_extracted_ids", "common_extracted_ids"):
            subset = [r for r in statistics if r["case_id"] == spec["case_id"] and r["cohort"] == cohort]
            minima.extend(dict(row, propagation_model="zero_field_reference",
                scope="Analytic counterfactual from fixed actual births; no conductors, collisions or electrode survival; not an actual local-field focus")
                for row in _sampled_minima(subset, planes, spec["case_id"], "global_z", cohort))
    return dict(zero_field_plane_statistics=statistics, zero_field_plane_particles=particles,
                zero_field_plane_decisions=decisions, zero_field_minima=minima,
                actual_zero_field_paired_statistics=paired, actual_zero_field_paired_particles=deltas)


def _zero_field_figure(output: Path, cases: list[dict], paired: list[dict]) -> str:
    """Compare identical per-plane common IDs and expose missing-arrival counts."""
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(len(cases), 3, figsize=(15, 3.1*len(cases)+1), squeeze=False, layout="constrained")
    for case, row_axes in zip(cases, axes):
        case_id = case["case"]["case_id"]
        selected = [r for r in paired if r["case_id"] == case_id and r["cohort"] == "common_extracted_ids"]
        for model, color, line, label in (("actual_local_field", "#0072B2", "-", "Actual local field"),
                                         ("zero_field_reference", "#D55E00", "--", "Zero-field reference")):
            rows = [r for r in selected if r["propagation_model"] == model]
            for ax, key, ylabel in zip(row_axes[:2], ("time_sigma_ns", "central90_ns"), ("Time SD on paired IDs (ns)", "Central 90% on paired IDs (ns)")):
                ax.plot([-r["z_mm"] for r in rows], [r[key] if r[key] is not None and r["paired_count"] >= 2 else np.nan for r in rows],
                        color=color, linestyle=line, label=label)
                ax.set(xlabel="Global -z (mm)", ylabel=ylabel)
        actual = [r for r in selected if r["propagation_model"] == "actual_local_field"]
        for key, color, style, label in (("actual_available_count", "#0072B2", "-", "Actual arrivals"),
                                         ("reference_available_count", "#D55E00", "--", "Reference reachable"),
                                         ("paired_count", "black", ":", "Paired at this plane")):
            row_axes[2].plot([-r["z_mm"] for r in actual], [r[key] for r in actual], color=color, linestyle=style, label=label)
        row_axes[2].set(xlabel="Global -z (mm)", ylabel="Common-cohort ID count", ylim=(0, max([r["declared_count"] for r in actual], default=0)+1))
        row_axes[0].set_title(case_id, loc="left")
        for ax in row_axes:
            ax.grid(alpha=.2)
        row_axes[1].legend(fontsize=7)
        row_axes[2].legend(fontsize=7)
    fig.suptitle("Actual versus zero-field time widths | same per-plane IDs from fixed common upstream cohort\n"
                 "Counterfactual from exact births/clocks; no electrode/collision survival. Width curves omitted for paired N < 2; counts remain visible.\nMissing IDs and full reference minima are separate CSV tables.", fontsize=11)
    local._save_figure(fig, output/"zero_field_reference_comparison")
    return "zero_field_reference_comparison"


def _virtual_aperture_figures(output: Path, aperture: list[dict], cases: list[dict]) -> list[str]:
    """Facet existing selector moments by case and plane; never mix locations."""
    from matplotlib import pyplot as plt

    metrics = (("sigma_local_theta_x_deg", "Plane-local x angle SD (deg)"),
               ("sigma_local_theta_y_deg", "Plane-local y angle SD (deg)"),
               ("sigma_local_x_mm", "Plane-local x position SD (mm)"),
               ("sigma_local_y_mm", "Plane-local y position SD (mm)"),
               ("time_sigma_ns", "Absolute arrival-time SD (ns)"),
               ("sigma_kinetic_energy_ev", "Total kinetic-energy SD (eV)"))
    names = []
    for case in cases:
        case_id = case["case"]["case_id"]
        selected = [r for r in aperture if r["case_id"] == case_id]
        for plane in dict.fromkeys(r["plane"] for r in selected):
            rows = [r for r in selected if r["plane"] == plane]
            reference = next(r for r in rows if r["shape"] == "unfiltered")
            fig, axes = plt.subplots(2, 3, figsize=(15, 10), layout="constrained")
            for shape, color, marker, style, label in (("circle", "#0072B2", "o", "-", "Circle (R)"),
                    ("y_slit", "#D55E00", "^", "--", "y slit (half-y width)")):
                points = sorted((r for r in rows if r["shape"] == shape), key=lambda r: r["half_width_mm"])
                for ax, (metric, ylabel) in zip(axes.flat, metrics):
                    ax.plot([100*r["transmission_mother"] for r in points],
                            [r[metric] if r[metric] is not None else np.nan for r in points],
                            color=color, marker=marker, linestyle=style, linewidth=1, markersize=4, label=label)
                    ax.set(xlabel="Accepted / original mother population (%)", ylabel=ylabel, xlim=(0, 100))
            for ax, (metric, _) in zip(axes.flat, metrics):
                if reference[metric] is not None:
                    ax.plot([100*reference["transmission_mother"]], [reference[metric]], marker="D",
                            markerfacecolor="none", markeredgecolor="black", linestyle="none", label="Unfiltered arrivals")
                ax.grid(alpha=.2)
            axes[0, 0].legend(fontsize=8)
            widths = ", ".join(f"{r['half_width_mm']:g}" for r in rows if r["shape"] == "circle")
            x_limit = "unlimited" if reference["slit_x_half_width_mm"] is None else f"{reference['slit_x_half_width_mm']:g} mm"
            center = ", ".join(f"{reference[f'selector_center_{a}_mm']:.6g}" for a in "xyz")
            fig.suptitle(f"{case_id} | {plane}: reference global z={reference['z_mm']:g} mm | frame={reference['frame']}\n"
                f"Declared world center x/y=({reference['center_x_mm']:g}, {reference['center_y_mm']:g}) mm; plane center xyz=({center}) mm\n"
                f"Circle R / y-slit half-y widths: [{widths}] mm; slit half-x={x_limit}; mother / IP exit / plane arrivals={reference['mother_count']}/{reference['exit_count']}/{reference['arrival_count']}\n"
                "Independent virtual selectors; unchanged velocities/energy per ion. All counts in virtual_aperture_summary.csv; N<2 widths undefined.", fontsize=10)
            name = f"virtual_aperture__{case_id}__{plane}"
            local._save_figure(fig, output/name)
            names.append(name)
    return names


def _figures(output: Path, stats: list[dict], aperture: list[dict], cases: list[dict], paired_stats: list[dict]) -> list[str]:
    from matplotlib import pyplot as plt

    colors = {"B": "#0072B2", "C": "#D55E00", "D": "#009E73"}
    groups = list(dict.fromkeys(c["case"]["label"] for c in cases))
    styles = ("-", "--", "-.", ":")
    fig, axes = plt.subplots(len(groups), 3, figsize=(15, 3.4*len(groups)+1), squeeze=False, sharex="col", sharey="col", layout="constrained")
    for case in cases:
        spec = case["case"]
        group = groups.index(spec["label"])
        siblings = [c for c in cases if c["case"]["label"] == spec["label"]]
        style = styles[siblings.index(case) % len(styles)]
        rows = [r for r in stats if r["case_id"] == spec["case_id"] and r["cohort"] == "own_extracted_ids" and r["frame"] == "global_z"]
        color = colors.get(spec["label"][:1], "#555555")
        for ax, metric, label in zip(axes[group], ("time_sigma_ns", "central68_ns", "central90_ns"), ("Population SD t (ns)", "Central 68% width (ns)", "Central 90% width (ns)")):
            ax.plot([-r["z_mm"] for r in rows],
                    [r[metric] if r[metric] is not None and r["count"] >= 2 and not r["missing_ids"] else np.nan for r in rows],
                    label=f"{spec['case_id']} | {_numerical_label(spec)}", color=color, linestyle=style)
            ax.set(xlabel="Global -z (mm); actual sampled crossings", ylabel=label)
        axes[group, 0].set_title(spec["label"], loc="left")
    for row in axes:
        row[-1].legend(fontsize=7, loc="center left", bbox_to_anchor=(1.02, .5))
    fig.suptitle("Actual local-field time widths | complete fixed IP exit cohort only\nGaps mark missing IDs or N < 2; all available-arrival widths and sampled minima remain in CSV")
    local._save_figure(fig, output / "time_focus")
    columns = min(3, len(cases))
    fig, axes = plt.subplots(math.ceil(len(cases)/columns), columns, figsize=(5*columns, 3.6*math.ceil(len(cases)/columns)+1), squeeze=False, layout="constrained")
    for case, ax in zip(cases, axes.flat):
        spec = case["case"]
        for frame, style in (("global_z", "-"), ("reference_normal", "--")):
            rows = [r for r in paired_stats if r["case_id"] == spec["case_id"] and r["cohort"] == "own_extracted_ids" and r["frame"] == frame]
            ax.plot([-r["z_mm"] for r in rows], [r["time_sigma_ns"] if r["time_sigma_ns"] is not None else np.nan for r in rows], style, color=colors.get(spec["label"][:1], "#555555"), label=frame)
        ax.set(xlabel="Reference global -z (mm)", ylabel="Population SD t (ns)", title=spec["case_id"]+"\n"+_numerical_label(spec))
    for ax in list(axes.flat)[len(cases):]:
        ax.set_visible(False)
    fig.legend(*axes.flat[0].get_legend_handles_labels(), loc="outside upper center", ncol=2,
               title="Actual crossing planes | same IDs paired at each plane; missing IDs in CSV")
    local._save_figure(fig, output / "normal_comparison")
    return ["time_focus", "normal_comparison", *_virtual_aperture_figures(output, aperture, cases)]


def _transport_figures(output: Path, cases: list[dict], stats: list[dict], snapshots: list[dict], epoch: float) -> list[str]:
    """Reuse canonical actual-state plots and display existing along-plane moments."""
    from matplotlib import pyplot as plt

    names = []
    # The established renderers use one case per row, never superpose nine clouds.
    for mass in sorted({c["case"]["mass_u"] for c in cases}):
        subset = [c for c in cases if c["case"]["mass_u"] == mass]
        suffix = "" if len(subset) == len(cases) else f"_mass_{mass:g}"
        for name, builder in (("exit_phase_space", lambda: local.build_exit_phase_space_figure(subset, mass)),
                              ("exit_time_energy", lambda: local.build_time_energy_figure(subset, mass, epoch))):
            local._save_figure(builder(), output/(name+suffix))
            names.append(name+suffix)
    for axis in ("y", "x"):
        name = f"packet_spatial_evolution_{axis}z"
        local._save_figure(local.build_spatial_snapshots_figure(cases, snapshots, epoch, axis), output/name)
        names.append(name)
    groups = list(dict.fromkeys(c["case"]["label"] for c in cases))
    fig, axes = plt.subplots(len(groups), 6, figsize=(23, 3.2*len(groups)+1), squeeze=False, sharex="col", sharey="col", layout="constrained")
    metrics = (("sigma_x_mm", "x position SD (mm)"), ("sigma_y_mm", "y position SD (mm)"),
               ("sigma_theta_x_deg", "xz angle SD (deg)"), ("sigma_theta_y_deg", "yz angle SD (deg)"),
               ("sigma_kinetic_energy_ev", "Total K SD (eV)"), ("count", "Arriving / fixed source IDs"))
    colors = {"B": "#0072B2", "C": "#D55E00", "D": "#009E73"}
    for group, label in enumerate(groups):
        for index, case in enumerate(c for c in cases if c["case"]["label"] == label):
            spec = case["case"]
            rows = [r for r in stats if r["case_id"] == spec["case_id"] and r["cohort"] == "own_extracted_ids" and r["frame"] == "global_z"]
            for ax, (key, ylabel) in zip(axes[group], metrics):
                ax.plot([-r["z_mm"] for r in rows], [r[key] if r[key] is not None else np.nan for r in rows],
                        linestyle=("-", "--", "-.", ":")[index % 4], color=colors.get(label[:1], "#555555"),
                        label=spec["case_id"]+" | "+_numerical_label(spec))
                ax.set(xlabel="Global -z (mm)", ylabel=ylabel)
        axes[group, 0].set_title(label, loc="left")
        axes[group, -1].legend(fontsize=6, loc="center left", bbox_to_anchor=(1.02, .5))
    fig.suptitle("Actual local-field transport | projected global angles, population SD, all available IDs; arrival counts expose loss selection")
    local._save_figure(fig, output/"transport_widths")
    return [*names, "transport_widths"]


def analyze_focus_study(run: Path) -> dict:
    """Export actual global/normal-plane widths, full census and virtual cuts."""
    run = Path(run)
    resolved = json.loads((run / "inputs/resolved_study.json").read_text(encoding="utf-8-sig"))
    if resolved["role"] != "resolved_ip_prism_contour_focus_study":
        raise ValueError("Unsupported focus study")
    contract = resolved["contract"]
    planes, aperture = contract["observation_planes"], contract["aperture_comparison"]
    aperture_frame = _aperture_frame(contract)
    cases = [_load_case(run, spec, planes) for spec in resolved["cases"]]
    if not cases or len({c["case"]["case_id"] for c in cases}) != len(cases):
        raise ValueError("Nonempty distinct cases required")
    common = set.intersection(*(set(c["births"]) for c in cases))
    reference = next((c for c in cases if c["case"]["case_id"] == aperture["reference_case_id"]), None)
    if reference is None:
        raise ValueError("Explicit reference case not found")
    normal_planes = _reference_planes(reference, planes)
    stats, particles, budgets, census_rows, cuts, cut_particles, minima, paired_stats = [], [], [], [], [], [], [], []
    spatial_minima = []
    output = run / "results/local_focus_diagnostics"
    output.mkdir(parents=True, exist_ok=True)
    for case in cases:
        spec, pid_exit = case["case"], set(case["births"])
        case_id, mass = spec["case_id"], spec["mass_u"]
        # Cadence is tested after a real solver step, so its overshoot is bounded
        # by one maximum step, not by max(cadence, step).
        normal = {p["plane"]: {pid: row for pid, track in case["tracks"].items() if (row := normal_crossing(track, p, spec["sample_interval_us"]+spec["maximum_step_us"])) is not None} for p in normal_planes}
        for index, p in enumerate(planes):
            for cohort, ids in (("own_extracted_ids", pid_exit), ("common_extracted_ids", common)):
                paired_ids = ids & normal[p["name"]].keys() & case["planes"][p["name"]].keys()
                for frame, crossings in (("global_z", case["planes"]), ("reference_normal", normal)):
                    paired_stats.append(dict(case_id=case_id, plane=p["name"], z_mm=p["z_mm"], frame=frame, cohort=cohort,
                                             available_ids=sorted(paired_ids), missing_ids=sorted(ids-paired_ids),
                                             **_statistics([crossings[p["name"]][i] for i in sorted(paired_ids)], mass,
                                                           normal_planes[index] if frame == "reference_normal" else None)))
        for pid, original in case["census"].items():
            terminal = case["terminals"].get(pid)
            census_rows.append(dict(original, case_id=case_id, outcome=terminal["reason"] if terminal else "upstream_not_handed_off", **{f"terminal_{k}": v for k, v in (terminal or {}).items()}))
        for frame, crossings in (("global_z", case["planes"]), ("reference_normal", normal)):
            for cohort, ids in (("own_extracted_ids", pid_exit), ("common_extracted_ids", common)):
                for index, p in enumerate(planes):
                    available = ids & crossings[p["name"]].keys()
                    rows = [crossings[p["name"]][i] for i in sorted(available)]
                    record = dict(case_id=case_id, label=spec["label"], frame=frame, cohort=cohort,
                                  plane=p["name"], z_mm=p["z_mm"], declared_count=len(ids),
                                  available_ids=sorted(available), missing_ids=sorted(ids-available),
                                  **_statistics(rows, mass, normal_planes[index] if frame == "reference_normal" else None))
                    stats.append(record)
                    if index:
                        budgets.append(dict(case_id=case_id, frame=frame, cohort=cohort,
                                            plane_a=planes[index-1]["name"], plane_b=p["name"],
                                            **time_variance_budget(crossings[planes[index-1]["name"]], crossings[p["name"]], ids)))
                subset = [r for r in stats if r["case_id"] == case_id and r["frame"] == frame and r["cohort"] == cohort]
                minima.extend(_sampled_minima(subset, planes, case_id, frame, cohort))
                spatial_metrics = ("sigma_x_mm", "sigma_y_mm") if frame == "global_z" else ("sigma_local_x_mm", "sigma_local_y_mm")
                for metric in spatial_metrics:
                    spatial_minima.extend(_sampled_minima(subset, planes, case_id, frame, cohort, metric=metric))
            for p in planes:
                for pid, row in crossings[p["name"]].items():
                    particles.append(dict(row, case_id=case_id, frame=frame, plane=p["name"], common_extracted_id=pid in common, own_extracted_id=pid in pid_exit))
        for p in normal_planes:
            if p["plane"] not in aperture["plane_names"]:
                continue
            available = (normal if aperture_frame == "reference_normal" else case["planes"])[p["plane"]]
            selector_plane, center = _selector_plane(p, aperture, aperture_frame)
            for shape, width in [("unfiltered", None), *[(s, w) for s in ("circle", "y_slit") for w in aperture["half_widths_mm"]]]:
                accepted = []
                for pid in sorted(case["census"]):
                    row = available.get(pid)
                    xi = float((_vector(row)-center) @ np.array(selector_plane["e_x"])) if row else None
                    eta = float((_vector(row)-center) @ np.array(selector_plane["e_y"])) if row else None
                    keep = row is not None and (shape == "unfiltered" or aperture_accepts(xi, eta, width, shape, aperture["slit_x_half_width_mm"]))
                    if keep:
                        accepted.append(row)
                    cut_particles.append(dict(case_id=case_id, plane=p["plane"], frame=aperture_frame, shape=shape, half_width_mm=width,
                                              particle_id=pid, xi_mm=xi, eta_mm=eta,
                                              status="accepted" if keep else "aperture_rejected" if row else "local_plane_not_reached" if pid in case["births"] else "upstream_not_handed_off"))
                widths = _statistics(accepted, mass, selector_plane)
                # A single ion does not define a measured packet width.
                if len(accepted) < 2:
                    widths = {k: None if k != "count" else v for k, v in widths.items()}
                cuts.append(dict(case_id=case_id, plane=p["plane"], z_mm=p["global_z_mm"],
                                 center_x_mm=aperture["center_x_mm"], center_y_mm=aperture["center_y_mm"],
                                 **{f"selector_center_{a}_mm": float(center[i]) for i, a in enumerate("xyz")},
                                 frame=aperture_frame, shape=shape, half_width_mm=width,
                                 mother_count=len(case["census"]), exit_count=len(pid_exit), arrival_count=len(available),
                                 local_p1_exit_count=len(case["planes"]["p1_exit"]),
                                 accepted_count=len(accepted), transmission_mother=len(accepted)/len(case["census"]),
                                 transmission_exit=len(accepted)/len(pid_exit) if pid_exit else None,
                                 slit_x_half_width_mm=aperture["slit_x_half_width_mm"], **widths))
    comparisons = numerical_comparison_rows(_numerical_case_pairs(run, resolved, cases), planes)
    snapshots = local.prepare_common_time_snapshots(cases)
    energy = [r for c in cases for r in local._energy_drift_rows([c], c["case"]["mass_u"], c["case"]["charge_state"])]
    tables = dict(plane_statistics=stats, plane_particles=particles, time_interval_variance=budgets,
                  mother_census=census_rows, all_losses=[r for r in census_rows if r["outcome"] != "reached_exit"],
                  virtual_aperture_summary=cuts, virtual_aperture_particles=cut_particles,
                  numerical_comparisons=comparisons, reference_planes=normal_planes, sampled_minima=minima,
                  sampled_spatial_minima=spatial_minima,
                  simultaneous_positions=snapshots, hamiltonian_drift=energy, normal_global_paired_statistics=paired_stats,
                  observation_overshoot=[row for c in cases for row in c["overshoots"]])
    reference_tables = _zero_field_tables(cases, planes, common)
    tables.update(reference_tables)
    for name, rows in tables.items():
        local._write_csv(output / f"{name}.csv", rows)
    standard_figures = _figures(output, stats, cuts, cases, paired_stats)
    display_epoch = min(c["case"].get("pulse_time_us", c["case"]["source_epoch_us"]) for c in cases)
    transport_figures = _transport_figures(output, cases, stats, snapshots, display_epoch)
    reference_figure = _zero_field_figure(output, cases, reference_tables["actual_zero_field_paired_statistics"])
    lifecycle_snapshots = lifecycle.export_transport_snapshots(output, cases, display_epoch)
    physical_cases = [c["case"]["case_id"] for c in cases if c["case"].get("physical_aperture") is not None]
    physical_scope = ("Includes actual physical-aperture field cases, with independent additional virtual selectors"
                      if physical_cases else "No physical-aperture field case; independent virtual selectors only")
    summary = dict(schema_version=1, role="actual_local_field_focus_diagnostics", common_extracted_ids=sorted(common),
                   common_count=len(common), reference_case_id=aperture["reference_case_id"],
                   observation_overshoot_count=sum(len(c["overshoots"]) for c in cases),
                   unbounded_post_terminal_observation_count=sum(not r["bounded_interpolation_halo"] for c in cases for r in c["overshoots"]),
                   case_counts=[dict(case_id=c["case"]["case_id"], source_count=len(c["births"]), mother_count=len(c["census"]), exit_count=len(c["planes"]["p1_exit"])) for c in cases],
                   physical_aperture_case_ids=physical_cases,
                   aperture_frame=aperture_frame,
                   figure_names=[*standard_figures, *transport_figures, reference_figure, *lifecycle_snapshots["figure_names"]],
                   transport_snapshot_times_us=lifecycle_snapshots["times_us"],
                   actual_minima_table="sampled_minima.csv", zero_field_minima_table="zero_field_minima.csv",
                   actual_spatial_minima_table="sampled_spatial_minima.csv",
                   zero_field_scope="Analytic constant-velocity counterfactual from actual births/absolute clocks; no fields, conductors, collisions or actual survival; not actual local focus or MR performance",
                   scope="Actual bounded saved-state crossings; "+physical_scope+"; no MR resolving-power claim")
    metadata = dict(summary, source_contract_sha256=file_sha256(run / "inputs/resolved_study.json"),
                    code_sha256=file_sha256(Path(__file__)),
                    normal_planes="One explicit reference case; mean actual arrival positions and velocities; common fixed geometric planes, no case recentering; paired statistics use identical IDs in both plane definitions",
                    cohort_definition="Own extracted IDs are fixed upstream IP exit/birth IDs; common is their fixed intersection, never reselected by downstream survival; transmission_exit denominator is upstream IP exit count",
                    normal_terminal_support="No extrapolation past terminal, including terminal exit plane: tilted exit plane may have missing crossings",
                    interpolation_bound="Adjacent saved-state gap <= sample_interval_us + maximum_step_us + 8*float64_epsilon*max(abs(endpoint_times)); cadence is tested after each actual step",
                    widths="Population SD and direct quantiles; no Gaussian FWHM; complete tails",
                    sampled_minima="Available-arrival observation minimum separated from >=2-ion fixed complete-cohort contiguous-interval minima; no survival-based focus claim; interval and scan boundaries and plane spacings explicit",
                    aperture_center=("Declared world x/y at fixed global z; actual global-z event state, fixed x/y basis"
                                     if aperture_frame == "global_z" else "Declared world x/y at reference global z, orthogonally projected onto fixed normal plane"),
                    virtual_apertures="Independent alternative thin position selectors; velocities/energy unchanged; slit unlimited x iff null",
                    numerical_comparisons="Same frozen source/census content, species/counts, absolute clocks, registration, physical CSG/aperture, pose, held IP values_v15/evaluation_time_us/basis and prism voltage; labels, source/field paths, grid and dt do not define physics identity. Derived aperture grid_representation and GEM subtraction-tool metadata are removed; physical solids/cutouts/specification remain. Same-ID differences are numerical sensitivity, not convergence qualification.",
                    numerical_comparison_projection_paths=[str(path) for path in contour_projection_paths(resolved).values()])
    metadata["static_field_scope"] = "Fixed measured exit states in held post-extraction RF-zero local electrostatic field; does not test remote HP/guide RF or upstream extraction feedback"
    metadata["raw_observations"] = "All real samples, including post-terminal halo, retained in raw Hamiltonian scope and observation_overshoot table; canonical interpolation never uses observations after terminal; out-of-bound observations explicitly counted, never silently deleted"
    metadata["transport_figures"] = "Actual exit clouds/time-energy, along-plane spatial/angular/energy widths and five common all-active time snapshots; case rows or design small multiples; no survival-based source redefinition"
    metadata["full_transport_snapshots"] = lifecycle_snapshots
    metadata["display_time_origin_us"] = display_epoch
    metadata["physical_aperture_scope"] = physical_scope
    metadata["virtual_aperture_figures"] = "One six-panel figure per case and selector plane, using only existing cut statistics: frame-local x/y angles and positions, absolute time SD and kinetic-energy SD. Circle/y-slit differ by marker, line and color; unfiltered arrivals retained. Plane, center, widths, source/arrival counts and per-width count CSV explicit. No different planes are superposed."
    metadata["zero_field_reference"] = "Separate zero_field_* tables project all fixed exit/birth IDs onto the same declared global-z scan. Upstream non-handoffs and unreachable references remain decisions; analytic references are not actual trajectory extrapolation or physical survival. No waist optimization is performed."
    metadata["actual_zero_field_pairing"] = "Widths compare identical IDs at each plane, for fixed own/common upstream cohorts; actual/reference available counts, paired counts and all missing IDs explicit. Paired minima are not used to redefine actual sampled_minima. Delta t/xyz = actual minus analytic reference; all instrument clocks retained. Figure uses the fixed common upstream cohort, with per-plane intersection exposed by count panel; width curves omit paired N<2 while CSV population moments and counts remain."
    for name, value in (("summary", summary), ("metadata", metadata)):
        (output / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return summary
