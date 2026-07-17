"""Split a SIMION vector-field CSV into COMSOL interpolation-function inputs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result_dir = args.workspace / "artifacts/projects/rf_quadrupole_collision_cooling/results/simion"
    source = result_dir / "unit_rf_field_pa_grid.csv"
    outputs = {
        "Ex_V_per_m": result_dir / "unit_rf_field_ex.csv",
        "Ey_V_per_m": result_dir / "unit_rf_field_ey.csv",
        "Ez_V_per_m": result_dir / "unit_rf_field_ez.csv",
    }
    handles = {component: path.open("w", encoding="utf-8", newline="") for component, path in outputs.items()}
    try:
        writers = {component: csv.writer(handle, delimiter=" ", lineterminator="\n") for component, handle in handles.items()}
        with source.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                coordinates = [row["x_mm"], row["y_mm"], row["z_mm"]]
                for component, writer in writers.items():
                    writer.writerow([*coordinates, row[component]])
    finally:
        for handle in handles.values():
            handle.close()
    print("STATUS=PASS OUTPUTS=" + ";".join(str(path) for path in outputs.values()))


if __name__ == "__main__":
    main()
