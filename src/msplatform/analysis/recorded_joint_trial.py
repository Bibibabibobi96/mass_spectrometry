"""Compare recorded prepared-joint trajectory representations without execution dependencies."""
from __future__ import annotations

import json
from itertools import zip_longest
from pathlib import Path
import re
from typing import Any

from msplatform.analysis.mr_observations import read_scientific_events
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.io.scientific_csv import iter_csv_rows


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def compare_trajectory_representation(preparation_path: Path, log_path: Path,
                                       output_path: Path, *, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    """Require exact event/sample text for the frozen prefix, retaining the whole new wave."""
    preparation = _read(preparation_path)
    reference = preparation["trajectory_equivalence_reference"]
    if not reference:
        raise ValueError("An explicit trajectory equivalence reference is required")
    verify_record("trajectory equivalence baseline", reference["reference_log"])
    verify_record("trajectory equivalence baseline manifest", reference["reference_manifest"])
    identifiers = set(reference["original_particle_ids"])

    def selected_lines(path: Path):
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if line.startswith(("MRTOF_EVENT ", "MRTOF_TRAJECTORY ")):
                    match = re.search(r"\bion=(\d+)", line)
                    if match and int(match[1]) in identifiers:
                        yield line.rstrip("\r\n")

    current_science=_read(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else None
    reference_science=reference.get("scientific_event_output")

    def selected_records(path,science):
        events,_,_=read_scientific_events(path,scientific_event_output=science)
        for event in events:
            if int(event["ion"]) in identifiers:
                yield ("event",event)
        if science is not None:
            columns=("ion","phase","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us")
            if not science.get("trajectory_path"):
                raise ValueError("equivalence requires explicit complete trajectory output")
            samples=iter_csv_rows(Path(science["trajectory_path"]),columns,exact_header=columns,expected_record=science.get("trajectory_record"))
        else:
            def legacy_samples():
                with path.open(encoding="utf-8-sig") as source:
                    for line in source:
                        if line.startswith("MRTOF_TRAJECTORY "):
                            yield dict(token.split("=",1) for token in line.split()[1:])
            samples=legacy_samples()
        for sample in samples:
            if int(sample["ion"]) in identifiers:
                yield ("trajectory",{key:value if key=="phase" else float(value) for key,value in sample.items()})

    structured = current_science is not None or reference_science is not None
    baseline_rows=selected_records(Path(reference["reference_log"]["path"]),reference_science) if structured else selected_lines(Path(reference["reference_log"]["path"]))
    current_rows=selected_records(log_path,current_science) if structured else selected_lines(log_path)
    mismatches, lines = [], 0
    for index, (baseline, current) in enumerate(zip_longest(baseline_rows,current_rows), 1):
        lines = index
        if baseline != current and len(mismatches) < 10:
            mismatches.append(dict(selected_line=index, reference=baseline, current=current))
    result = dict(schema_version=1, role="mrtof_field_consumer_trajectory_equivalence",
                  status="pass" if not mismatches and lines else "fail", compared_line_count=lines,
                  original_particle_ids=reference["original_particle_ids"],
                  scope="complete_event_and_trajectory_fields_of_manifest_bound_completed_prefix" if structured else "complete_event_and_trajectory_text_of_manifest_bound_completed_prefix",
                  physical_matching_qualified=False, numerical_representation_only=True,
                  reference=reference, new_log=file_record(log_path), first_mismatches=mismatches)
    _write(output_path, result)
    if result["status"] != "pass":
        raise ValueError("Memory consumer trajectory representation differs from its full-field reference")
    return result
