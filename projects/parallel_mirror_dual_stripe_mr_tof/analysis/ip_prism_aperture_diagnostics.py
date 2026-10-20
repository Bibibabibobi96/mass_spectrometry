"""Compare immutable local aperture flights with baseline thin-plane selectors.

No PA reads, solver invocation, trajectory extrapolation or MR qualification.
Coordinates are world mm, velocity mm/us, and clocks remain instrument us.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import numpy as np

from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import verified_reference
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_focus_diagnostics as focus
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_diagnostics as local


ROLE = "ip_prism_recorded_aperture_comparison"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value) and all(c.isascii() and (c.isalnum() or c in "_-") for c in value)


def validate_aperture_contract(contract: dict) -> None:
    """Fail closed on unknown author fields and ambiguous case selections."""
    required = {"schema_version", "role", "comparisons", "committed_new_bytes", "claim"}
    if (set(contract) != required or type(contract["schema_version"]) is not int
            or contract["schema_version"] != 1 or contract["role"] != ROLE):
        raise ValueError("unsupported recorded aperture comparison contract")
    if (type(contract["committed_new_bytes"]) is not int or contract["committed_new_bytes"] <= 0
            or not isinstance(contract["claim"], str) or not contract["claim"]):
        raise ValueError("positive capacity commitment and explicit claim required")
    rows = contract["comparisons"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty comparisons required")
    seen = set()
    for row in rows:
        if set(row) != {"comparison_id", "baseline_case", "physical_case", "virtual_thin_plane", "downstream_plane_name"}:
            raise ValueError("complete aperture comparison fields required")
        name = row["comparison_id"]
        if not _identifier(name) or name in seen:
            raise ValueError("distinct path-safe comparison IDs required")
        seen.add(name)
        if row["virtual_thin_plane"] not in {"front", "center", "back"} or not _identifier(row["downstream_plane_name"]):
            raise ValueError("explicit thin plane and downstream observation required")
        for key in ("baseline_case", "physical_case"):
            case = row[key]
            if (not isinstance(case, dict) or set(case) != {"producer_run", "case_id"}
                    or not isinstance(case["producer_run"], str) or not case["producer_run"] or not _identifier(case["case_id"])):
                raise ValueError("explicit producer and case identity required")


def _freeze_file(source: Path, target: Path, records: list) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    before = file_record(source)
    shutil.copyfile(source, target)
    frozen = file_record(target)
    if any(before[k] != frozen[k] for k in ("sha256", "bytes")):
        raise ValueError("private observation copy differs from producer")
    records.append(dict(source=before, frozen=frozen))


def _locate_case(selection: dict) -> tuple[Path, dict, dict, dict]:
    """Locate one original producer case without merging source ordinals."""
    owner = Path(selection["producer_run"]).resolve()
    require_completed_terminal_publication(owner/"run_manifest.json")
    source = verified_reference(owner, "inputs/resolved_study.json")
    resolved = _read(source)
    if resolved["role"] != "resolved_ip_prism_contour_focus_study":
        raise ValueError("recorded contour producer required")
    matches = [s for s in resolved["cases"] if s["case_id"] == selection["case_id"]]
    if len(matches) != 1:
        raise ValueError("selected producer case missing or duplicated")
    spec = copy.deepcopy(matches[0])
    projection = focus.contour_projection_paths(resolved)[spec["source_run"]]
    paths = {name: Path(spec["directory"])/name for name in ("events.csv", "samples.csv", "geometry.json")}
    paths.update({"source.csv": Path(spec["source_csv"]), "source_census.csv": Path(spec["source_census_csv"]),
                  "provider_voltage_projection.json": projection})
    manifest = _read(owner/"run_manifest.json")
    paths.update(producer_resolved_study_json=source, producer_manifest_json=owner/"run_manifest.json",
                 producer_run_config_json=record_path(manifest["run_config"], base_dir=owner))
    return owner, resolved, spec, paths


def _freeze_case(selection: dict, destination: Path) -> dict:
    """Verify every consumed producer record before copying private observations."""
    owner, resolved, spec, paths = _locate_case(selection)
    records = []
    for name, path in paths.items():
        path = owner/path
        if name == "producer_run_config_json":
            verify_record("producer run config", _read(owner/"run_manifest.json")["run_config"], base_dir=owner)
        elif name != "producer_manifest_json":
            verified_reference(owner, path.relative_to(owner).as_posix())
        target = {"producer_manifest_json": "producer_manifest.json", "producer_resolved_study_json": "producer_resolved_study.json",
                  "producer_run_config_json": "producer_run_config.json"}.get(name, name)
        _freeze_file(path, destination/target, records)
    identity = focus._comparison_identity(owner, resolved, spec)
    spec.update(directory=str(destination), source_csv=str(destination/"source.csv"), source_census_csv=str(destination/"source_census.csv"))
    geometry = _read(destination/"geometry.json")["geometry"]
    return dict(spec=spec, identity=identity, numerics=resolved["numerics"], planes=resolved["contract"]["observation_planes"],
                geometry=geometry, records=records, producer_run=str(owner))


def _validate_pair(baseline: dict, physical: dict, selection: dict) -> dict:
    """Require identical frozen source/physics/numerics except the added plate."""
    if baseline["spec"].get("physical_aperture") is not None or baseline["geometry"].get("aperture_electrodes"):
        raise ValueError("baseline must have no physical aperture")
    plates = physical["geometry"].get("aperture_electrodes", [])
    if len(plates) != 1 or physical["spec"].get("physical_aperture") is None:
        raise ValueError("one explicit physical aperture required")
    aperture = plates[0]["specification"]
    if aperture != physical["spec"]["physical_aperture"]:
        raise ValueError("physical case declaration and frozen aperture differ")
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_geometry import _aperture_specification
    _aperture_specification(aperture, physical["geometry"]["frame_id"])
    identities = []
    for case in (baseline, physical):
        identity = copy.deepcopy(case["identity"])
        identity.pop("physical_aperture")
        identity["geometry"].pop("aperture_electrodes", None)
        identity["numerics"] = case["numerics"]
        identity["case_numerics"] = {k: case["spec"][k] for k in ("pitch_mm", "maximum_step_us", "sample_interval_us")}
        identities.append(identity)
    if identities[0] != identities[1]:
        raise ValueError("baseline and physical source/clock/physics/numerics differ beyond aperture")
    name = selection["downstream_plane_name"]
    downstream = []
    for case in (baseline, physical):
        matches = [p for p in case["planes"] if p["name"] == name]
        if len(matches) != 1:
            raise ValueError("common downstream observation missing")
        downstream.append(matches[0]["z_mm"])
    center, thickness = aperture["center_mm"][2], aperture["thickness_mm"]
    planes = dict(front=center+thickness/2, center=center, back=center-thickness/2)
    if downstream[0] != downstream[1] or downstream[0] >= planes["back"]:
        raise ValueError("report plane must match and lie downstream of complete aperture")
    planes["downstream"] = downstream[0]
    return dict(aperture=aperture, planes=planes, matched_identity=identities[0])


def prepare_aperture_comparison(run: Path, contract_path: Path) -> dict:
    """Privately freeze manifest-bound small records; caller freezes code/config."""
    run = run.resolve()
    contract = _read(contract_path)
    validate_aperture_contract(contract)
    selections = {}
    for row in contract["comparisons"]:
        for side in ("baseline_case", "physical_case"):
            case = row[side]
            selections.setdefault((str(Path(case["producer_run"]).resolve()), case["case_id"]), case)
    # Samples can be large. Charge each actual private producer/case copy once;
    # stat is for admission, while manifest byte/hash checks own file identity.
    source_bytes = sum(path.stat().st_size for selection in selections.values()
                       for path in _locate_case(selection)[3].values())
    if source_bytes+contract_path.stat().st_size > contract["committed_new_bytes"]:
        raise ValueError("private observation copies exceed committed_new_bytes before copying")
    inputs = run/"inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    frozen_contract = inputs/"experiment_contract.json"
    if contract_path.resolve() != frozen_contract:
        shutil.copyfile(contract_path, frozen_contract)
    comparisons, cache = [], {}
    for row in contract["comparisons"]:
        cases = {}
        for side in ("baseline", "physical"):
            selection = row[side+"_case"]
            key = (str(Path(selection["producer_run"]).resolve()), selection["case_id"])
            if key not in cache:
                cache[key] = _freeze_case(selection, inputs/"sources"/f"source_{len(cache)+1:02d}")
            cases[side] = cache[key]
        comparison = _validate_pair(cases["baseline"], cases["physical"], row)
        comparisons.append(dict(selection=row, **cases, **comparison))
    result = dict(schema_version=1, role="resolved_"+ROLE, contract=contract, comparisons=comparisons,
                  committed_new_bytes=contract["committed_new_bytes"], gui_executed=False, new_solver_execution=False)
    serialized_bytes = len((json.dumps(result, indent=2, allow_nan=False)+"\n").encode("utf-8"))
    if sum(p.stat().st_size for p in inputs.rglob("*") if p.is_file())+serialized_bytes > contract["committed_new_bytes"]:
        raise ValueError("private inputs and resolved evidence exceed committed_new_bytes")
    _write(inputs/"resolved_study.json", result)
    return result


def _crossings(case: dict, planes: dict) -> dict:
    result = {}
    known = {p["z_mm"]: p["name"] for p in case["declared_planes"]}
    maximum_gap = case["case"]["sample_interval_us"]+case["case"]["maximum_step_us"]
    for name, z in planes.items():
        if z in known:
            result[name] = case["planes"][known[z]]
        else:
            plane = dict(origin_mm=[0, 0, z], normal=[0, 0, -1])
            result[name] = {pid: row for pid, track in case["tracks"].items()
                            if (row := focus.normal_crossing(track, plane, maximum_gap)) is not None}
    return result


def _stats(rows: list, mass: float) -> dict:
    values = focus._statistics(rows, mass)
    if len(rows) < 2:
        # Means and observed count remain defined, packet widths do not.
        values = {k: None if k.startswith(("sigma_", "emittance_", "central")) or k in {"time_sigma_ns", "time_range_ns"} else v
                  for k, v in values.items()}
    return values


def _selected_ids(rows: dict, aperture: dict) -> set[int]:
    cx, cy = aperture["center_mm"][:2]
    shape = aperture["shape"]
    width = aperture["radius_mm"] if shape == "circle" else aperture["half_widths_mm"][1]
    half_x = None if shape == "circle" else aperture["half_widths_mm"][0]
    return {pid for pid, row in rows.items() if focus.aperture_accepts(row["x_mm"]-cx, row["y_mm"]-cy, width, shape, half_x)}


def _comparison_tables(item: dict, run: Path) -> dict:
    cases, crossings = {}, {}
    for key in ("baseline", "physical"):
        frozen = item[key]
        for record in frozen["records"]:
            verify_record("frozen aperture comparison input", record["frozen"])
        case = focus._load_case(run, frozen["spec"], frozen["planes"])
        if any(not row["bounded_interpolation_halo"] for row in case["overshoots"]):
            raise ValueError("unbounded observation beyond terminal")
        case["declared_planes"] = frozen["planes"]
        cases[key], crossings[key] = case, _crossings(case, item["planes"])
    base, actual = cases["baseline"], cases["physical"]
    if base["census"].keys() != actual["census"].keys() or base["births"].keys() != actual["births"].keys():
        raise ValueError("paired mother and handed-off identities differ")
    selection = item["selection"]
    selected = _selected_ids(crossings["baseline"][selection["virtual_thin_plane"]], item["aperture"])
    paired = selected & crossings["baseline"]["downstream"].keys() & crossings["physical"]["downstream"].keys()
    tables = {key: [] for key in ("population_statistics", "paired_statistics", "paired_particle_deltas", "mother_decisions", "plane_particles")}
    common = dict(comparison_id=selection["comparison_id"], mother_count=len(base["census"]), exit_count=len(base["births"]),
                  virtual_thin_plane=selection["virtual_thin_plane"], selector_z_mm=item["planes"][selection["virtual_thin_plane"]],
                  aperture_shape=item["aperture"]["shape"], aperture_thickness_mm=item["aperture"]["thickness_mm"],
                  **{f"aperture_center_{axis}_mm": item["aperture"]["center_mm"][i] for i, axis in enumerate("xyz")},
                  aperture_radius_mm=item["aperture"].get("radius_mm"),
                  slit_half_x_mm=item["aperture"].get("half_widths_mm", [None, None])[0],
                  slit_half_y_mm=item["aperture"].get("half_widths_mm", [None, None])[1])
    for plane, z in item["planes"].items():
        populations = {"baseline_unfiltered": crossings["baseline"][plane],
                       "baseline_virtual": {i:r for i,r in crossings["baseline"][plane].items() if i in selected},
                       "physical_actual": crossings["physical"][plane]}
        for channel, rows in populations.items():
            count = len(rows)
            tables["population_statistics"].append(dict(common, plane=plane, z_mm=z, channel=channel,
                available_ids=sorted(rows), missing_ids=sorted(base["births"].keys()-rows.keys()),
                transmission_mother=count/common["mother_count"], transmission_exit=count/common["exit_count"],
                **_stats(list(rows.values()), base["case"]["mass_u"])))
        plane_paired = paired & populations["baseline_virtual"].keys() & populations["physical_actual"].keys()
        for channel in ("baseline_virtual", "physical_actual"):
            rows = populations[channel]
            tables["paired_statistics"].append(dict(common, plane=plane, z_mm=z, channel=channel,
                paired_downstream_ids=sorted(paired), available_ids=sorted(plane_paired), missing_ids=sorted(paired-plane_paired),
                side_available_ids=sorted(paired & rows.keys()), side_missing_ids=sorted(paired-rows.keys()),
                transmission_mother=len(plane_paired)/common["mother_count"], transmission_exit=len(plane_paired)/common["exit_count"],
                **_stats([rows[i] for i in sorted(plane_paired)], base["case"]["mass_u"])))
        for side, rows in ((key, crossings[key][plane]) for key in cases):
            tables["plane_particles"].extend(dict(row, comparison_id=common["comparison_id"], side=side, plane=plane,
                virtual_selected=pid in selected, paired_downstream=pid in paired) for pid, row in rows.items())
        for pid in sorted(paired & crossings["baseline"][plane].keys() & crossings["physical"][plane].keys()):
            a, b = crossings["baseline"][plane][pid], crossings["physical"][plane][pid]
            qa, qb = (local._quantities([r], base["case"]["mass_u"]) for r in (a, b))
            tables["paired_particle_deltas"].append(dict(comparison_id=common["comparison_id"], plane=plane, particle_id=pid,
                delta_t_ns=(b["t_us"]-a["t_us"])*1000,
                **{f"delta_{k}": b[k]-a[k] for k in local.STATE_FIELDS if k != "t_us"},
                **{f"delta_{k}": float(qb[k][0]-qa[k][0]) for k in ("theta_x_deg", "theta_y_deg", "kinetic_energy_ev", "kx_ev", "ky_ev", "kz_ev")}))
    for pid in sorted(base["census"]):
        row = dict(common, particle_id=pid, virtual_selected=pid in selected, paired_downstream=pid in paired)
        for side, case in cases.items():
            row.update({f"{side}_census_{k}":v for k,v in case["census"][pid].items()})
            terminal = case["terminals"].get(pid)
            row.update({f"{side}_terminal_{k}":v for k,v in (terminal or {}).items()})
            row[f"{side}_outcome"] = terminal["reason"] if terminal else "upstream_not_handed_off"
            for plane in item["planes"]:
                row[f"{side}_{plane}_reached"] = pid in crossings[side][plane]
        row["virtual_decision"] = ("upstream_not_handed_off" if pid not in base["births"] else
            "selector_not_reached" if pid not in crossings["baseline"][selection["virtual_thin_plane"]] else
            "aperture_rejected" if pid not in selected else
            "accepted_report_reached" if pid in crossings["baseline"]["downstream"] else "accepted_report_not_reached")
        tables["mother_decisions"].append(row)
    return tables


def build_aperture_comparison_figure(rows: list, comparison_id: str):
    """Render prepared population widths and explicit collection counts, English."""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = Figure(figsize=(10, 8.5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 3)
    metrics = [("sigma_theta_x_deg", "xz angle SD (deg)"), ("sigma_theta_y_deg", "yz angle SD (deg)"),
               ("time_sigma_ns", "Time SD (ns)"), ("sigma_x_mm", "x SD (mm)"), ("sigma_y_mm", "y SD (mm)"),
               ("sigma_kinetic_energy_ev", "Total K SD (eV)"), ("central68_ns", "Central 68% time (ns)"),
               ("central90_ns", "Central 90% time (ns)"), ("transmission_mother", "Collection / mother (%)")]
    for channel, color, marker, line in (("baseline_unfiltered", "black", "D", "-"),
            ("baseline_virtual", "#0072B2", "o", "--"), ("physical_actual", "#D55E00", "s", "-.") ):
        selected = [r for r in rows if r["comparison_id"] == comparison_id and r["channel"] == channel]
        for axis, (metric, label) in zip(axes.flat, metrics):
            scale = 100 if metric == "transmission_mother" else 1
            axis.plot(range(len(selected)), [scale*r[metric] if r[metric] is not None else np.nan for r in selected],
                      marker=marker, linestyle=line, color=color, label=channel.replace("_", " "))
            axis.set(ylabel=label, xticks=range(len(selected)), xticklabels=[r["plane"] for r in selected])
            axis.tick_params(axis="x", labelsize=8, rotation=20)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncol=3, fontsize=8)
    first = next(r for r in rows if r["comparison_id"] == comparison_id)
    opening = (f"circle R={first['aperture_radius_mm']:g} mm" if first["aperture_shape"] == "circle" else
               f"y-slit half x/y={first['slit_half_x_mm']:g}/{first['slit_half_y_mm']:g} mm")
    figure.suptitle(f"{comparison_id}: {opening}; thin {first['virtual_thin_plane']} at z={first['selector_z_mm']:g} mm\n"
        f"Center x/y/z={first['aperture_center_x_mm']:g}/{first['aperture_center_y_mm']:g}/{first['aperture_center_z_mm']:g} mm; plate thickness={first['aperture_thickness_mm']:g} mm\n"
        f"Downstream z={next(r['z_mm'] for r in rows if r['comparison_id'] == comparison_id and r['plane'] == 'downstream'):g} mm; mother / IP exit={first['mother_count']}/{first['exit_count']}\n"
        "Discrete planes; full tails; population SD; no MR qualification", fontsize=10)
    return figure, axes


def analyze_aperture_comparison(run: Path) -> dict:
    """Analyze only private frozen records and export complete comparison evidence."""
    run = run.resolve()
    resolved = _read(run/"inputs/resolved_study.json")
    if (set(resolved) != {"schema_version", "role", "contract", "comparisons", "committed_new_bytes", "gui_executed", "new_solver_execution"}
            or resolved.get("role") != "resolved_"+ROLE or type(resolved.get("schema_version")) is not int or resolved["schema_version"] != 1):
        raise ValueError("unsupported resolved aperture comparison")
    validate_aperture_contract(resolved["contract"])
    if [i["selection"] for i in resolved["comparisons"]] != resolved["contract"]["comparisons"]:
        raise ValueError("resolved comparison selections differ from author")
    tables = {}
    for item in resolved["comparisons"]:
        derived = _validate_pair(item["baseline"], item["physical"], item["selection"])
        if any(item[key] != value for key, value in derived.items()):
            raise ValueError("resolved comparison derivation differs")
        for key, rows in _comparison_tables(item, run).items():
            tables.setdefault(key, []).extend(rows)
    output = run/"results/aperture_comparison"
    output.mkdir(parents=True, exist_ok=True)
    for key, rows in tables.items():
        local._write_csv(output/(key+".csv"), rows)
    figures = []
    for item in resolved["comparisons"]:
        name = item["selection"]["comparison_id"]
        figure, _ = build_aperture_comparison_figure(tables["population_statistics"], name)
        for extension in ("png", "svg"):
            path = output/("comparison__"+name+"."+extension)
            figure.savefig(path, format=extension, dpi=180, facecolor="white")
            figures.append(path.name)
        figure.clear()
    summary = dict(schema_version=1, role=ROLE+"_summary", status="success", new_solver_execution=False,
        comparisons=[i["selection"]["comparison_id"] for i in resolved["comparisons"]], figure_names=figures,
        downstream_statistics=[r for r in tables["population_statistics"] if r["plane"] == "downstream"],
        mother_decision_count=len(tables["mother_decisions"]), scope="Recorded bounded local transport; no MR performance qualification")
    metadata = dict(summary, producer=file_record(Path(__file__)), run_config=file_record(run/"run_config.json"),
        resolved_input=file_record(run/"inputs/resolved_study.json"),
        units="world mm, velocity mm/us, canonical absolute instrument us; time widths ns", formats=["png", "svg"], dpi=180,
        size_inches=[10, 8.5], statistics="Population SD; direct q84-q16 / q95-q05; N<2 packet widths null; no filtering of tails",
        selector="Thin-plane membership determined once in baseline; fixed IDs read at all report planes, never reselected downstream",
        pairing="Fixed intersection at downstream, then per-plane intersection shared by both statistics; side-specific support/missing IDs retained; original mother/exit denominators retained",
        crossing="Original global-z event if present; otherwise bounded adjacent canonical saved-state interpolation; no extrapolation",
        comparison="Finite plate and its altered field together differ from thin counterfactual; not an isolated edge-field causal attribution",
        collection="Counts at each plane, not guaranteed final collection; final report uses downstream plane; upstream losses retained separately",
        plotting="Categorical plane order; connecting segments are guides, not continuous interpolation. Black diamonds unfiltered; blue dashed circles virtual; vermilion dash-dot squares physical",
        uncertainty="Finite-cohort descriptive statistics only; no confidence interval or Gaussian FWHM assumption",
        source_bindings=[dict(selection=i["selection"], baseline=i["baseline"]["records"], physical=i["physical"]["records"],
                             aperture=i["aperture"], planes=i["planes"]) for i in resolved["comparisons"]])
    _write(output/"summary.json", summary)
    _write(output/"metadata.json", metadata)
    return summary
