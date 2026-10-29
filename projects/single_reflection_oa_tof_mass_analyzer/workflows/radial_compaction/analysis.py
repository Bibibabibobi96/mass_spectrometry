"""Analyze completed radial SIMION flight logs without executing native work."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from common.analysis.peak_metrics import compute_peak_metrics
from common.contracts.recorded_file_removal import write_json_atomic
from projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics import analyze_simion_log


def canonical_metrics(particle_csv: Path) -> dict[str, Any]:
    """Compute the existing 524 Da peak metric from recorded detector hits."""
    tof = []
    with particle_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if str(row["Hit"]).lower() == "true":
                tof.append(float(row["TofUs"]))
    metrics, _ = compute_peak_metrics(np.asarray(tof), 524.0)
    return metrics


def analyze_flight(case: dict[str, Any], mode: str, log: Path, ion: Path, particle_count: int,
                   elapsed: float | None, reused: bool, resource_profile: dict[str, Any]) -> dict[str, Any]:
    """Publish diagnostics for a completed or reused native flight."""
    results = case["case_root"] / "results"
    particle_csv = results / f"{mode}_particles.csv"
    particles, diagnostics = analyze_simion_log(
        log, ion, mode=mode, distribution=f"fixedN{particle_count}",
        detector_radius_mm=40, allow_incomplete_census=True,
    )
    particles.to_csv(particle_csv, index=False)
    diagnostics = json.loads(json.dumps(diagnostics, allow_nan=False))
    summary = {
        "schema_version": 1, "role": "oatof_radial_compaction_case_result", "status": "success",
        "case_id": case["case_id"], "mode": mode, "run_id": case["run_id"],
        "context_sha256": case["context_sha256"], "flight_seconds": elapsed,
        "flight_reused_from_interrupted_run": reused, "resource_profile": resource_profile,
        "diagnostics": diagnostics, "canonical_peak_metrics": canonical_metrics(particle_csv),
    }
    write_json_atomic(results / f"{mode}_summary.json", summary)
    return summary
