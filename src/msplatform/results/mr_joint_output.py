"""Write recorded joint diagnostics and associated figure records."""
import csv
import json
from pathlib import Path
from typing import Any
from matplotlib import pyplot as plt
from msplatform.io.figure_export import export_figures

def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

def _write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def record_birth_clock_projection(output: Path, lifetimes: dict, authority: dict, *, record_file) -> dict:
    rows = [dict(particle_id=particle, raw_birth_time_us=value["raw_birth_time_us"],
                 canonical_birth_time_us=value["birth"], raw_minus_canonical_us=value["raw_birth_time_us"]-value["birth"],
                 birth_clock_projected=value["birth_clock_projected"], semantics=value["birth_clock_semantics"],
                 six_dimensional_state_exact=value["six_dimensional_state_exact"],
                 first_subsequent_time_us=value["first_subsequent_time_us"],
                 subsequent_sample_count=value["subsequent_sample_count"], all_subsequent_times_at_or_after_canonical_birth=True)
            for particle, value in sorted(lifetimes.items())]
    _write_rows(output / "birth_clock_projection.csv", rows, list(rows[0]))
    result = dict(schema_version=1, role="mrtof_initialize_birth_clock_projection", authority=authority,
                  particle_count=len(rows), projected_particle_ids=[r["particle_id"] for r in rows if r["birth_clock_projected"]],
                  maximum_absolute_raw_clock_difference_us=max(abs(r["raw_minus_canonical_us"]) for r in rows),
                  raw_trajectory_csv_modified=False, six_dimensional_state_changed=False,
                  interpretation="Initialize callback may report engine elapsed zero before SIMION applies per-ion TOB. Canonical handoff birth is used only in derived lifetime/snapshot views; all subsequent recorded times and raw rows remain unchanged.",
                  numerical_tolerance_added=False, rows_record=record_file(output / "birth_clock_projection.csv"))
    _write(output / "birth_clock_projection.json", result)
    return result


def save_figure(figure, path: Path, metadata: dict, *, record_file) -> None:
    try:
        records = export_figures({path.with_suffix(""): figure}, formats=("png", "svg"), dpi=180, facecolor="white")
        outputs = {record["format"]: record_file(Path(record["path"])) for record in records}
        _write(path.with_suffix(".metadata.json"), dict(metadata, figure_role=path.name,
               figure_size_inches=list(figure.get_size_inches()), dpi=180, outputs=outputs))
    finally:
        plt.close(figure)
