"""Derive a transverse accelerator-field reference envelope from systematic samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


METRICS = (
    "ez_profile_relative_rms",
    "potential_profile_relative_rms",
    "transverse_field_relative_rms",
)


def relative_rms(values: np.ndarray, reference_scale: float) -> float:
    return float(np.sqrt(np.mean(np.square(values))) / reference_scale)


def analyze(samples: pd.DataFrame, formal_half_width_mm: float) -> tuple[pd.DataFrame, dict]:
    required = {
        "x_mm", "y_mm", "z_mm", "Ex_V_per_m", "Ey_V_per_m",
        "Ez_V_per_m", "potential_V",
    }
    if not required.issubset(samples.columns):
        raise ValueError(f"field table is missing columns: {sorted(required - set(samples.columns))}")
    axis = samples[np.isclose(samples["y_mm"], 0.0)].sort_values("z_mm")
    if axis.empty:
        raise ValueError("field table has no y=0 accelerator-axis profile")
    z_axis = axis["z_mm"].to_numpy(float)
    ez_axis = axis["Ez_V_per_m"].to_numpy(float)
    potential_axis = axis["potential_V"].to_numpy(float)
    ez_scale = float(np.sqrt(np.mean(np.square(ez_axis))))
    potential_scale = float(np.ptp(potential_axis))
    if ez_scale <= 0.0 or potential_scale <= 0.0:
        raise ValueError("axis field or potential scale is not positive")

    rows: list[dict] = []
    for y_mm, group in samples.groupby("y_mm"):
        profile = group.sort_values("z_mm")
        if not np.allclose(profile["z_mm"].to_numpy(float), z_axis, rtol=0.0, atol=1e-10):
            raise ValueError("transverse profiles do not share identical z samples")
        ex = profile["Ex_V_per_m"].to_numpy(float)
        ey = profile["Ey_V_per_m"].to_numpy(float)
        ez = profile["Ez_V_per_m"].to_numpy(float)
        potential = profile["potential_V"].to_numpy(float)
        rows.append({
            "y_mm": float(y_mm),
            "abs_y_mm": abs(float(y_mm)),
            "ez_profile_relative_rms": relative_rms(ez - ez_axis, ez_scale),
            "potential_profile_relative_rms": relative_rms(
                potential - potential_axis, potential_scale
            ),
            "transverse_field_relative_rms": relative_rms(
                np.sqrt(np.square(ex) + np.square(ey)), ez_scale
            ),
        })
    signed = pd.DataFrame(rows)
    envelope = signed.groupby("abs_y_mm", as_index=False)[list(METRICS)].max()
    reference = envelope[envelope["abs_y_mm"] <= formal_half_width_mm + 1e-12]
    if reference.empty or reference["abs_y_mm"].max() < formal_half_width_mm - 1e-12:
        raise ValueError("field samples do not cover the formal source half-width")
    thresholds = {metric: float(reference[metric].max()) for metric in METRICS}
    tolerance = {metric: max(value * 1e-9, 1e-15) for metric, value in thresholds.items()}
    for metric in METRICS:
        envelope[f"{metric}_pass"] = (
            envelope[metric] <= thresholds[metric] + tolerance[metric]
        )
    envelope["all_metrics_pass"] = envelope[
        [f"{metric}_pass" for metric in METRICS]
    ].all(axis=1)
    contiguous_bound = 0.0
    for row in envelope.sort_values("abs_y_mm").itertuples(index=False):
        if not row.all_metrics_pass:
            break
        contiguous_bound = float(row.abs_y_mm)
    report = {
        "schema_version": 1,
        "role": "oatof_accelerator_transverse_field_uniformity_reference",
        "status": "PASS",
        "source_geometry": "current closed-shield formal oaTOF electrostatic solution",
        "formal_source_half_width_y_mm": formal_half_width_mm,
        "threshold_policy": "For every metric, use the worst value within the already formal 1 mm transverse source width; all metrics combine by logical AND.",
        "thresholds": thresholds,
        "closed_shield_contiguous_half_width_mm": contiguous_bound,
        "closed_shield_contiguous_full_width_mm": 2.0 * contiguous_bound,
        "claim_limit": "Reference threshold and closed-shield L0 only; the opened joint RF-oa geometry must be resampled before selecting a physical port width.",
    }
    return envelope, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    formal_half_width = float(baseline["particle_source"]["size_y_mm"]) / 2.0
    envelope, report = analyze(pd.read_csv(args.input), formal_half_width)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    envelope.to_csv(args.output_dir / "transverse_field_uniformity_curve.csv", index=False)
    (args.output_dir / "transverse_field_uniformity_metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    figure, axes = plt.subplots(3, 1, figsize=(7.2, 8.5), sharex=True)
    for axis, metric in zip(axes, METRICS):
        axis.semilogy(envelope["abs_y_mm"], np.maximum(envelope[metric], 1e-16), "o-")
        axis.axhline(max(report["thresholds"][metric], 1e-16), color="tab:red", linestyle="--")
        axis.axvline(formal_half_width, color="tab:gray", linestyle=":")
        axis.set_ylabel(metric.replace("_relative_rms", ""))
        axis.grid(True, alpha=0.25)
    axes[-1].set_xlabel("Absolute transverse offset |y| [mm]")
    figure.suptitle("oaTOF accelerator transverse field uniformity reference")
    figure.tight_layout()
    figure.savefig(args.output_dir / "transverse_field_uniformity.png", dpi=220)
    plt.close(figure)
    print(
        "ACCELERATOR_TRANSVERSE_FIELD_UNIFORMITY=PASS "
        f"CLOSED_SHIELD_FULL_WIDTH_MM={report['closed_shield_contiguous_full_width_mm']:.12g}"
    )


if __name__ == "__main__":
    main()
