"""Gate deterministic N=100 transport through the physical S1 port and local pulse field."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle


def analyze(events: pd.DataFrame) -> dict:
    if len(events) != 100 or events["particle_id"].nunique() != 100:
        raise ValueError("S1 physical-port result must contain exactly 100 unique particles")
    geometric = events[events["event"] != "geometric_reject"]
    exits = events[events["event"] == "local_joint_exit"]
    pulse_values = events["pulse_time_reached"]
    if pd.api.types.is_bool_dtype(pulse_values):
        pulse_mask = pulse_values
    elif pd.api.types.is_numeric_dtype(pulse_values):
        pulse_mask = pulse_values.astype(float).ne(0.0)
    else:
        pulse_mask = pulse_values.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
    pulse_reached = events[(events["event"] != "geometric_reject") & pulse_mask]
    checks = {
        "complete_particle_census": len(events) == 100,
        "minimum_geometric_acceptance": len(geometric) >= 5,
        "minimum_particles_reaching_pulse_time": len(pulse_reached) >= 5,
        "minimum_local_joint_exit": len(exits) >= 5,
    }
    return {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_physical_port_n100_function_gate",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "particles": len(events),
        "geometric_port_accepted": len(geometric),
        "geometric_port_acceptance": len(geometric) / len(events),
        "particles_reaching_pulse_time": len(pulse_reached),
        "local_joint_exit": len(exits),
        "local_joint_exit_fraction": len(exits) / len(events),
        "checks": checks,
        "downstream_analyzer_required": True,
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
    }


def plot_entry(canonical: pd.DataFrame, events: pd.DataFrame, center_z: float, output: Path) -> None:
    outcome = events.set_index("particle_id")["event"]
    ids = canonical["particle_id"].astype(int)
    accepted = ids.map(outcome).ne("geometric_reject")
    figure, axis = plt.subplots(figsize=(6.4, 5.4))
    axis.scatter(canonical.loc[accepted, "position_y_mm"], canonical.loc[accepted, "position_z_mm"],
                 color="#238b45", label="inside physical port", s=26)
    axis.scatter(canonical.loc[~accepted, "position_y_mm"], canonical.loc[~accepted, "position_z_mm"],
                 color="#d95f0e", marker="x", label="geometric reject", s=32)
    axis.add_patch(Rectangle((-0.5, center_z - 0.45), 1.0, 0.9, fill=False,
                             edgecolor="#54278f", linewidth=2, label="1.0 x 0.9 mm port"))
    axis.set(xlabel="oa transverse y (mm)", ylabel="oa axial z (mm)",
             title="RF exit distribution at the physical oa entry port")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--center-z-mm", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure", type=Path, required=True)
    args = parser.parse_args()
    events = pd.read_csv(args.events)
    result = analyze(events)
    plot_entry(pd.read_csv(args.canonical), events, args.center_z_mm, args.figure)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"S1_PHYSICAL_PORT_PARTICLES={result['status']} "
        f"GEOMETRIC={result['geometric_port_accepted']}/100 LOCAL_EXIT={result['local_joint_exit']}/100"
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
