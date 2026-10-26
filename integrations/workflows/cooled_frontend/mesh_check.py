"""Prepare and analyze local same-CSG Dirichlet mesh evidence; never Fly."""
from __future__ import annotations

import copy
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common.contracts.write_run_manifest import require_completed_terminal_publication
from .geometry import compile_cooled_frontend, compile_field_plan
from .prepare import prepare_cooled_frontend
from .runtime import _verified_small_record, fields


ROLE = "rf_oatof_cooled_frontend_mesh_check_request"


def validate_request(request: dict) -> None:
    if set(request) != {"schema_version", "role", "source_request_record", "field_source_record",
                         "patch_bounds_mm", "cell_mm_xyz", "refine_convergence_v", "native_sampling"}:
        raise ValueError("mesh check requires the explicit source, domain and native sampling contract")
    if request["schema_version"] != 1 or request["role"] != ROLE:
        raise ValueError("unsupported cooled mesh-check request")
    bounds, cells = request["patch_bounds_mm"], request["cell_mm_xyz"]
    if set(bounds) != {f"{a}_{s}" for a in "xyz" for s in ("min", "max")} or set(cells) != set("xyz"):
        raise ValueError("six MR bounds and three explicit cell sizes required")
    for a in "xyz":
        values = [bounds[f"{a}_min"], bounds[f"{a}_max"], cells[a]]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("finite mesh values required")
        if values[0] >= values[1] or values[2] <= 0:
            raise ValueError("ordered bounds and positive cells required")
        for value in values[:2]:
            ratio = value / cells[a]
            if abs(ratio-round(ratio)) > 32*math.ulp(max(1., abs(ratio))):
                raise ValueError("explicit crop faces must align with the requested native grid")
    convergence = request["refine_convergence_v"]
    if isinstance(convergence, bool) or not isinstance(convergence, (int, float)) or not math.isfinite(convergence) or convergence <= 0:
        raise ValueError("positive explicit convergence required")
    sampling = request["native_sampling"]
    if set(sampling) != {"axis_step_mm", "stencil_offsets_mm", "stencil_centers_y_mm"}:
        raise ValueError("axis step, stencil offsets and independent MR-y centers required")
    if not isinstance(sampling["axis_step_mm"], (int, float)) or isinstance(sampling["axis_step_mm"], bool) or not math.isfinite(sampling["axis_step_mm"]) or sampling["axis_step_mm"] <= 0:
        raise ValueError("positive native axial sampling step required")
    offsets, centers = sampling["stencil_offsets_mm"], sampling["stencil_centers_y_mm"]
    if not isinstance(offsets, list) or len(offsets) < 3 or offsets != sorted(set(offsets)) or not min(offsets) < 0 < max(offsets):
        raise ValueError("ordered two-sided explicit stencil offsets required")
    if not isinstance(centers, list) or not centers or len(centers) != len(set(centers)):
        raise ValueError("distinct explicit stencil centers required")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in [*offsets, *centers]):
        raise ValueError("finite stencil coordinates required")


def prepare_mesh_check(request_path: Path, output: Path | None, repo: Path, workspace: Path, *, run_id: str | None = None) -> dict:
    """Freeze the unchanged original source then compile only a numerical crop."""
    request_path, repo, workspace = (Path(p).resolve(strict=True) for p in (request_path, repo, workspace))
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    validate_request(request)
    source = _verified_small_record(request["source_request_record"], workspace)
    envelope = _verified_small_record(request["field_source_record"], workspace)
    source_record = dict(path=str(source), exists=True, bytes=request["source_request_record"]["bytes"],
                         sha256=request["source_request_record"]["sha256"])
    envelope_record = dict(path=str(envelope), exists=True, bytes=request["field_source_record"]["bytes"],
                           sha256=request["field_source_record"]["sha256"])
    published = json.loads(envelope.read_text(encoding="utf-8-sig"))
    if published.get("schema_version") != 1 or published.get("role") != "rf_oatof_cooled_frontend_field_source":
        raise ValueError("sealed field-source envelope required for numerical comparison")
    owner_manifest = _verified_small_record(published["source_owner_manifest_record"], workspace)
    require_completed_terminal_publication(owner_manifest)
    owner = json.loads(owner_manifest.read_text(encoding="utf-8-sig"))
    if owner["status"] not in ("success", "failed"):
        raise ValueError("mesh field owner must be terminal with published fields")
    original = json.loads(source.read_text(encoding="utf-8-sig"))
    result = prepare_cooled_frontend(source, output, repo, workspace, run_id=run_id)
    stage_path = _verified_small_record(published["field_stage_receipt_record"], workspace)
    stage = json.loads(stage_path.read_text(encoding="utf-8-sig"))
    geometry_sha = hashlib.sha256(result["geometry_gem"].encode("utf-8")).hexdigest().upper()
    plan_sha = hashlib.sha256((json.dumps(result["field_plan"], indent=2, allow_nan=False)+"\n").encode("utf-8")).hexdigest().upper()
    if geometry_sha != stage["geometry_record"]["sha256"] or plan_sha != stage["field_plan_record"]["sha256"]:
        raise ValueError("mesh author changed actual geometry or seven-response field plan from the field owner")
    coarse_front = result["frontend"]
    for a in "xyz":
        for side in ("min", "max"):
            x, parent = request["patch_bounds_mm"][f"{a}_{side}"], coarse_front["instance_bounds_mm"][f"{a}_{side}"]
            if (side == "min" and x <= parent) or (side == "max" and x >= parent):
                raise ValueError("local patch faces must lie strictly inside the actual parent PA")
    connection = dict(spatial_registration=coarse_front["guide_registration"])
    guide = json.loads((Path(output)/"inputs/guide_contract.json").read_text()) if output else None
    if guide is None:
        # ValidateOnly has no filesystem side effects or second source sampler.
        return dict(role=ROLE, status="validated", particle_count=result["particle_count"],
                    source_request_record=source_record, field_source_record=envelope_record, fly_executed=False)
    run = Path(output).resolve(strict=True)
    inputs = run/"inputs"
    shutil.copyfile(owner_manifest, inputs/"cooled_field_source_manifest.json")
    producer_config = _verified_small_record(owner["run_config"], workspace)
    shutil.copyfile(producer_config, inputs/"cooled_field_source_run_config.json")
    experiment = json.loads((inputs/"cooled_experiment.json").read_text())
    experiment["field_source"] = envelope_record
    (inputs/"cooled_experiment.json").write_text(json.dumps(experiment, indent=2)+"\n", encoding="utf-8")
    parent_fields = fields(run)  # Exact published parent; downstream analysis may have failed.
    parent_records = parent_fields["records"]
    gem, front = compile_cooled_frontend(guide, connection, coarse_front["accelerator_component"], result["conditioner"],
        cell_mm_xyz=request["cell_mm_xyz"], exit_gap_mm=result["assembly_plan"]["connection_checks"][0]["gap_mm"],
        numerical_bounds_mm=request["patch_bounds_mm"], source_geometry_cell_mm_xyz=coarse_front["cell_mm_xyz"])
    plan = compile_field_plan(front, guide, original["drive"],
        hp_rf_peak_amplitude_v=result["conditioner"]["drive"]["rf_amplitude_v"], refine_convergence_v=request["refine_convergence_v"])
    plan.update(role="cooled_frontend_local_dirichlet_mesh_check_plan",
                boundary_policy="same_kind_actual_parent_potential_on_six_crop_faces__static_only",
                dirichlet_parent=dict(origin_mm=coarse_front["instance_origin_mm"],
                    field_source_record=envelope_record, receipt_record=parent_fields["receipt"]))
    for point in plan["working_points"]:
        point["source_pa_record"] = parent_records[point["kind"]]
    numerical = copy.deepcopy(original["numerics"])
    numerical.update(cell_mm_xyz=request["cell_mm_xyz"], refine_convergence_v=request["refine_convergence_v"])
    points = sample_points(request, result["conditioner"])
    docs = {"frontend_contract.json": front, "cooled_field_plan.json": plan, "numerics.json": numerical,
            "mesh_check_request.json": request,
            "cooled_probe_plan.json": dict(sampler_repository_path="integrations/workflows/cooled_frontend/sample_mesh.lua"),
            "mesh_parent_identity.json": dict(source_request_record=source_record, field_source_record=envelope_record,
                parent_frontend_contract=coarse_front, working_points=list(parent_records.values()),
                source_mother_count=result["particle_count"], fly_executed=False)}
    for name, value in docs.items():
        (inputs/name).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    (inputs/"frontend.gem").write_text(gem, encoding="utf-8", newline="\n")
    with (inputs/"cooled_probe_points.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["name", "x_mm", "y_mm", "z_mm"])
        writer.writeheader(); writer.writerows(points)
    return dict(role=ROLE, status="prepared", particle_count=result["particle_count"], fly_executed=False,
                sample_count=len(points), parent_working_points=list(parent_records.values()),
                potential_payload_per_array_bytes=front["field_storage_forecast"]["potential_bytes_per_array"])


def sample_points(request: dict, conditioner: dict) -> list[dict]:
    """Axis and independent end stencils, plus native transverse mask sections."""
    bounds, cells, sampling = request["patch_bounds_mm"], request["cell_mm_xyz"], request["native_sampling"]
    center = conditioner["geometry"]["trap_center_mr_mm"]
    low, high = bounds["y_min"]+2*cells["y"], bounds["y_max"]-2*cells["y"]
    count = int(math.ceil((high-low)/sampling["axis_step_mm"]))
    points = [dict(name=f"axis_{i}", x_mm=center[0], y_mm=low+(high-low)*i/count, z_mm=center[2]) for i in range(count+1)]
    for i, y in enumerate(sampling["stencil_centers_y_mm"]):
        for j, delta in enumerate(itertools.product(sampling["stencil_offsets_mm"], repeat=3)):
            points.append(dict(name=f"end_{i}_{j}", x_mm=center[0]+delta[0], y_mm=y+delta[1], z_mm=center[2]+delta[2]))
        xs = np.arange(bounds["x_min"]+cells["x"], bounds["x_max"], cells["x"])
        zs = np.arange(bounds["z_min"]+cells["z"], bounds["z_max"], cells["z"])
        points += [dict(name=f"mask_{i}_{j}", x_mm=float(x), y_mm=y, z_mm=float(z)) for j,(x,z) in enumerate(itertools.product(xs,zs))]
    for point in points:
        if any(not bounds[f"{a}_min"] < point[f"{a}_mm"] < bounds[f"{a}_max"] for a in "xyz"):
            raise ValueError("every explicit stencil/mask point must be strictly inside the crop")
    return points


def analyze_mesh_check(run: Path) -> dict:
    """Report paired same-coordinate fields and mask differences without a pass threshold."""
    run = Path(run).resolve(strict=True)
    plan = json.loads((run/"inputs/cooled_field_plan.json").read_text())
    output = run/"results/mesh_check"
    output.mkdir(parents=True, exist_ok=False)
    raw = pd.read_csv(run/"results/cooled_field_probe/raw_physical_mask.csv").set_index("name", verify_integrity=True)
    metrics = []
    fig, axes = plt.subplots(7, 2, figsize=(13, 20), constrained_layout=True)
    for i, point in enumerate(plan["working_points"]):
        kind = point["kind"]
        fine = pd.read_csv(run/f"results/cooled_field_probe/{kind}.csv").set_index("name", verify_integrity=True)
        coarse = pd.read_csv(run/f"results/cooled_parent_probe/{kind}.csv").set_index("name", verify_integrity=True)
        if list(fine.index) != list(coarse.index) or not np.array_equal(fine[[f"{a}_mm" for a in "xyz"]], coarse[[f"{a}_mm" for a in "xyz"]]):
            raise ValueError("mesh probes are not exact same-coordinate pairs")
        paired = fine.add_prefix("fine_").join(coarse.add_prefix("coarse_"))
        if list(raw.index) != list(fine.index) or not np.array_equal(raw.nearest_electrode_flag, fine.nearest_electrode_flag):
            raise ValueError("interior refined nearest-node collision mask differs from the actual fine raw CSG")
        paired["raw_physical_bracket_electrode_count"] = raw.bracket_electrode_count
        paired["synthetic_boundary_bracket_count"] = fine.bracket_electrode_count-raw.bracket_electrode_count
        common_vacuum = (fine.bracket_electrode_count == 0) & (coarse.bracket_electrode_count == 0)
        row = dict(kind=kind, sample_count=len(fine), nearest_mask_mismatch_count=int((fine.nearest_electrode_flag != coarse.nearest_electrode_flag).sum()))
        row.update(common_vacuum_bracket_count=int(common_vacuum.sum()), fine_nearest_raw_mask_mismatch_count=0,
                   samples_touching_synthetic_crop_boundary=int((paired.synthetic_boundary_bracket_count != 0).sum()))
        for column in ("potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm"):
            delta = fine[column]-coarse[column]
            paired[f"fine_minus_coarse_{column}"] = delta
            row[f"max_abs_delta_{column}"] = float(delta.abs().max())
            row[f"common_vacuum_max_abs_delta_{column}"] = float(delta[common_vacuum].abs().max()) if common_vacuum.any() else None
        paired.to_csv(output/f"{kind}__paired.csv")
        metrics.append(row)
        axis = fine.index.str.startswith("axis_")
        for frame, label in ((coarse, "Coarse parent"), (fine, "Fine local patch")):
            axes[i, 0].plot(frame.loc[axis, "y_mm"], frame.loc[axis, "potential_v"], label=label)
            axes[i, 1].plot(frame.loc[axis, "y_mm"], frame.loc[axis, "ey_v_per_mm"], label=label)
        axes[i, 0].set_ylabel(f"{kind}\nPotential (V)")
        axes[i, 1].set_ylabel("Ey (V/mm)")
        for ax in axes[i]: ax.set_xlabel("MR y (mm)"); ax.grid(alpha=.2)
    axes[0, 0].legend()
    fig.suptitle("Same CSG, local mesh comparison — coarse parent Dirichlet boundary retained")
    for ext in ("png", "svg"): fig.savefig(output/f"mesh_comparison.{ext}", dpi=160)
    plt.close(fig)
    pd.DataFrame(metrics).to_csv(output/"field_differences.csv", index=False)
    summary = dict(schema_version=1, role="cooled_frontend_local_mesh_check", status="analysis_complete",
        metrics=metrics, fly_executed=False, simulated_mother_count=0,
        limitations="Local fine solution inherits the actual coarse parent boundary; no global convergence, capture, cooling, or flight claim. Synthetic crop faces are numerical boundaries, not physical metal. Nearest-node mask differences reflect sampling/voxelization, not changed analytic CSG.")
    (output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return summary
