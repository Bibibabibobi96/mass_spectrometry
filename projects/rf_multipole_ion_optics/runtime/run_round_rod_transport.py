"""Create an L2 transport run from one successful circular-rod field screen."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

from common.contracts.artifact_naming import validate_run_id
from common.contracts.verify_run_manifest import record_path, verified_successful_run_reference, verify_record
from projects.rf_multipole_ion_optics.analysis.analyze_round_rod_screen import analyze
from projects.rf_multipole_ion_optics.runtime._transport_run_artifacts import ARTIFACT_PROJECTS_ROOT, transport_run
from projects.rf_multipole_ion_optics.core.ideal_transport import evaluate_round_rod_contract, write_results
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile


def _validated_selected_samples(rows: list[dict[str, str]], contract: dict, design: dict) -> list[dict[str, str]]:
    """Bind the selected solver samples to the governed rods and frozen sampling grid."""
    geometry = design["geometry_mm"]
    ratio = float(geometry["rod_radius_ratio"])
    r0 = float(geometry["inscribed_radius_r0"])
    sweep = contract["geometry_mm"]["rod_radius_ratio_sweep"]
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9)
    if sum(close(float(value), ratio) for value in sweep) != 1:
        raise ValueError("field-screen sweep must contain the selected rod ratio exactly once")
    rods = geometry["rod_array"]["rods"]
    gaps = [math.hypot(float(a["center_x_mm"]) - float(b["center_x_mm"]),
                       float(a["center_y_mm"]) - float(b["center_y_mm"]))
            - float(a["radius_mm"]) - float(b["radius_mm"])
            for a, b in zip(rods, rods[1:] + rods[:1], strict=True)]
    expected_gap = min(gaps)
    radii = [float(fraction) * r0 for fraction in contract["sampling"]["radius_fraction_of_r0"]]
    count = int(contract["sampling"]["azimuth_samples_per_radius"])
    if count <= 0 or not radii or any(not math.isfinite(r) or r <= 0 for r in radii):
        raise ValueError("invalid field-screen sampling grid")
    seen = set()
    selected = []
    names = ("rod_radius_ratio", "rod_radius_mm", "rod_center_radius_mm", "adjacent_surface_gap_mm",
             "sample_radius_mm", "theta_rad", "x_mm", "y_mm", "potential_V")
    for row in rows:
        try:
            values = {name: float(row[name]) for name in names}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("field-screen sample has missing or invalid values") from exc
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("field-screen sample has nonfinite values")
        if not close(values["rod_radius_ratio"], ratio):
            continue
        if not all(close(values[key], expected) for key, expected in (
            ("rod_radius_mm", float(geometry["rod_radius"])),
            ("rod_center_radius_mm", float(geometry["rod_center_radius"])),
            ("adjacent_surface_gap_mm", expected_gap),
        )):
            raise ValueError("field-screen sample rod geometry differs from resolved design")
        radius_matches = [i for i, radius in enumerate(radii) if close(values["sample_radius_mm"], radius)]
        angle_index = round(values["theta_rad"] * count / (2 * math.pi))
        if (len(radius_matches) != 1 or not 0 <= angle_index < count
                or not close(values["theta_rad"], angle_index * 2 * math.pi / count)
                or not close(values["x_mm"], values["sample_radius_mm"] * math.cos(values["theta_rad"]))
                or not close(values["y_mm"], values["sample_radius_mm"] * math.sin(values["theta_rad"]))):
            raise ValueError("field-screen sample coordinates differ from frozen sampling grid")
        index = (radius_matches[0], angle_index)
        if index in seen:
            raise ValueError("duplicate field-screen sample")
        seen.add(index)
        selected.append(row)
    if len(seen) != len(radii) * count:
        raise ValueError("field-screen selected sample grid is incomplete")
    return selected


def _load_source(project_id: str, source_run_id: str, *, expected_design: dict) -> tuple[Path, dict, list[dict[str, str]]]:
    validate_run_id(source_run_id)
    source_dir = ARTIFACT_PROJECTS_ROOT / project_id / "runs" / source_run_id
    manifest = json.loads((source_dir / "run_manifest.json").read_text(encoding="utf-8-sig"))
    if (manifest.get("status") != "success" or manifest.get("project") != project_id
            or manifest.get("mode") != "round_rod_field_screen" or manifest.get("run_id") != source_run_id):
        raise ValueError("field-screen source manifest is not a successful run for this project")
    config_record = manifest["run_config"]
    if record_path(config_record, base_dir=source_dir) != (source_dir / "run_config.json").resolve():
        raise ValueError("field-screen source run configuration is not locally bound")
    verify_record("field-screen source run configuration", config_record, base_dir=source_dir)
    config = json.loads((source_dir / "run_config.json").read_text(encoding="utf-8-sig"))
    if any(config.get(key) != manifest.get(key) for key in ("run_id", "project", "mode")):
        raise ValueError("field-screen source run configuration identity differs")
    def consumed(relative: str) -> Path:
        return verified_successful_run_reference(source_dir, relative, project=project_id,
                                                 mode="round_rod_field_screen", manifest=manifest)
    source_design = json.loads(consumed("inputs/multipole_resolved_design.json").read_text(encoding="utf-8-sig"))
    if source_design.get("identity") != expected_design["identity"]:
        raise ValueError("field-screen source structural identity differs from selected transport design")
    source_geometry, selected_geometry = source_design["geometry_mm"], expected_design["geometry_mm"]
    for key in ("inscribed_radius_r0", "rod_radius_ratio", "rod_radius", "rod_center_radius", "rod_z_min", "rod_z_max"):
        if not math.isclose(float(source_geometry[key]), float(selected_geometry[key]), rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"field-screen source geometry differs from selected design: {key}")
    if source_geometry["rod_array"] != selected_geometry["rod_array"]:
        raise ValueError("field-screen source rod array differs from selected design")
    if (source_design["coordinate"] != expected_design["coordinate"]
            or not math.isclose(float(expected_design["coordinate"]["orientation_rad"]), 0.0, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("field-screen source requires the actual zero-orientation rod array")
    screen_contract = json.loads(consumed("inputs/round_rod_field_screen.json").read_text(encoding="utf-8-sig"))
    identity = expected_design["identity"]
    if (screen_contract.get("project_id") != project_id or screen_contract.get("role") != "multipole_round_rod_field_screen_contract"
            or screen_contract["multipole"] != {"radial_order_n": identity["radial_order_n"], "electrode_count": identity["electrode_count"]}
            or not math.isclose(float(screen_contract["geometry_mm"]["inscribed_radius_r0"]),
                                float(selected_geometry["inscribed_radius_r0"]), rel_tol=0, abs_tol=1e-12)):
        raise ValueError("field-screen contract geometry differs from selected design")
    with consumed("results/round_rod_potential_samples.csv").open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    return source_dir, screen_contract, _validated_selected_samples(rows, screen_contract, expected_design)


def _verify_frozen_source(frozen: dict[str, Path], source_dir: Path, initial_manifest: dict) -> None:
    manifest = json.loads(frozen["field_screen_manifest"].read_text(encoding="utf-8-sig"))
    if manifest != initial_manifest:
        raise ValueError("field-screen manifest changed while inputs were frozen")
    for name, relative in (("field_screen_design", "inputs/multipole_resolved_design.json"),
                           ("field_screen_contract", "inputs/round_rod_field_screen.json"),
                           ("field_screen_samples", "results/round_rod_potential_samples.csv")):
        expected = (source_dir / relative).resolve()
        records = [record for record in [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
                   if record_path(record, base_dir=source_dir) == expected]
        if len(records) != 1:
            raise ValueError("field-screen frozen input is not uniquely bound")
        verify_record(name, {**records[0], "path": str(frozen[name])})


def execute(project_root: Path, source_run_id: str, run_id: str, *, design_profile_id: str) -> Path:
    validate_run_id(run_id)
    project_id = json.loads((project_root / "config/project.json").read_text(encoding="utf-8"))["project_id"]
    selection = resolve_design_profile(project_root.parents[1], project_id, design_profile_id)
    source_manifest = ARTIFACT_PROJECTS_ROOT / project_id / "runs" / source_run_id / "run_manifest.json"
    initial_manifest = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
    source_dir, screen_contract, screen_rows = _load_source(
        project_id, source_run_id, expected_design=selection["resolved_design"],
    )
    with transport_run(
        project_root, run_id, design_profile_id=design_profile_id, mode="round_rod_no_collision",
        run_config_role="multipole_round_rod_l2_transport_run_config",
        summary_role="multipole_round_rod_l2_transport_summary",
        parameters={"model_level": "L2", "field_dimension": 2, "fringe_field": False},
        identity_inputs={
            "field_screen_manifest": source_dir / "run_manifest.json",
            "field_screen_design": source_dir / "inputs" / "multipole_resolved_design.json",
            "field_screen_contract": source_dir / "inputs" / "round_rod_field_screen.json",
            "field_screen_samples": source_dir / "results" / "round_rod_potential_samples.csv",
            "shared_implementation": Path(__file__).resolve().parents[1] / "core/ideal_transport.py",
            "field_screen_analysis": Path(__file__).resolve().parents[1] / "analysis/analyze_round_rod_screen.py",
        },
        output_names=("round_rod_transport_metrics.json", "particle_events.csv", "transport_comparison.png"),
    ) as run:
        frozen = run.frozen_identity
        _verify_frozen_source(frozen, source_dir, initial_manifest)
        frozen_contract = json.loads(frozen["field_screen_contract"].read_text(encoding="utf-8-sig"))
        with frozen["field_screen_samples"].open(newline="", encoding="utf-8-sig") as stream:
            frozen_rows = _validated_selected_samples(list(csv.DictReader(stream)), frozen_contract, selection["resolved_design"])
        screen_metrics = analyze(frozen_rows, frozen_contract)
        metrics, rows = evaluate_round_rod_contract(run.contract, screen_metrics, selection["resolved_design"],
            minimum_adjacent_gap_mm=float(frozen_contract["selection"]["minimum_adjacent_surface_gap_mm"]))
        write_results(metrics, rows, run.result_dir, run.outputs[0].name)
        if metrics["status"] != "PASS":
            raise RuntimeError("round-rod L2 functional transport gate failed")
        summary = {
            "project_id": project_id,
            "source_field_screen_run_id": source_run_id,
            "selected_rod_radius_ratio": metrics["selected_geometry"]["rod_radius_ratio"],
            "rf_transmission": metrics["cases"]["round_rod_rf_on"]["transmission_fraction"],
            "zero_rf_transmission": metrics["cases"]["zero_rf_control"]["transmission_fraction"],
        }
        run.complete(summary)
    print(
        f"ROUND_ROD_TRANSPORT=PASS PROJECT={project_id} "
        f"RF={summary['rf_transmission']:.6g} ZERO={summary['zero_rf_transmission']:.6g} RUN_ID={run_id}"
    )
    return run.run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--field-screen-run-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--design-profile-id", required=True)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    project_label = project_root.name.replace("_", "-")
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S") + f"__sim__python__{project_label}-round-rod__l2-n100"
    execute(project_root, args.field_screen_run_id, run_id, design_profile_id=args.design_profile_id)


if __name__ == "__main__":
    main()
