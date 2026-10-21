"""Verify saved-default local Fly against complete scheduled mother evidence.

No solver is launched here. The caller owns public admission and the fresh
process. Original controls and raw logs stay untouched; only parity evidence
is written. Physical parsing, clocks and loss census reuse the local analyzer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.contracts.write_run_manifest import file_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.local_frontend.analyze import (
    _FLOATS, _close, _csv, _source_rows, _validate_lifetimes, parse_local_logs,
)


def _write(path: Path, value: Any) -> None:
    if path.exists():
        raise ValueError(f"refuse to overwrite replay evidence: {path}")
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def prepare_default_replay(run_directory: Path, gui_case: dict, *, evidence_directory: Path | None = None) -> dict:
    """Freeze small GUI controls and return an override-free fresh-Fly spec.

    ``evidence_directory`` lets an independently managed audit consume a sealed
    source without writing that source. No PA is read, copied or rehashed.
    """
    run = Path(run_directory).resolve(strict=True)
    source = _source_rows(run/"inputs/release_global.csv")
    if gui_case["count"] != len(source) or gui_case["expected_particle_ids"] != list(source):
        raise ValueError("default replay requires the complete original GUI population")
    if gui_case["merge_offset"] != 0 or gui_case["simion_particle_id_offset"] != 0:
        raise ValueError("default replay must retain original particle IDs")
    directory = Path(gui_case["working_directory"]).resolve(strict=True)
    if not directory.is_relative_to(run):
        raise ValueError("GUI case escapes its source owner")
    controls = []
    for key in ("iob_path", "program_path", "particle_input"):
        path = Path(gui_case[key]).resolve(strict=True)
        if path.parent != directory or path.stem != "local":
            raise ValueError("default replay requires associated local IOB/Lua/FLY2 controls")
        controls.append(file_record(path))
    if [Path(row["path"]).suffix for row in controls] != [".iob", ".lua", ".fly2"]:
        raise ValueError("default replay control extensions differ")
    output = Path(evidence_directory).resolve() if evidence_directory is not None else run/"results/default_replay"
    output.mkdir(parents=True, exist_ok=False)
    specification = dict(schema_version=1, role="local_frontend_saved_default_replay", source_run=str(run),
        working_directory=str(directory), argument_list=["--nogui", "--noprompt", "fly", "local.iob"],
        environment={"OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET": "0"},
        environment_policy="neutral_ID_offset_zero_matches_Program_default_when_environment_absent",
        stdout=str(output/"native.stdout.log"), stderr=str(output/"native.stderr.log"),
        usage_path=str(output/"resource_usage.json"), evidence_directory=str(output),
        expected_particle_ids=list(source), control_records=controls,
        source_record=file_record(run/"inputs/release_global.csv"),
        claim="saved-default fresh-process Fly only; no manual GUI review")
    _write(output/"specification.json", specification)
    return specification


def compare_default_replay(run_directory: Path, scheduled_log_paths: list[Path], replay_log_path: Path,
                           *, evidence_directory: Path | None = None) -> dict:
    """Compare every per-ID event and terminal, excluding only batch-local ion/log identity.

    The existing 32-ULP binary64 serialization allowance is reused. It is not
    a physical trajectory tolerance; larger differences fail and remain saved.
    Missing/duplicate mother births or terminals fail the existing census.
    """
    run = Path(run_directory).resolve(strict=True)
    output = Path(evidence_directory).resolve() if evidence_directory is not None else run/"results/default_replay"
    spec = json.loads((output/"specification.json").read_text(encoding="utf-8"))
    if spec["source_run"] != str(run) or spec["argument_list"] != ["--nogui", "--noprompt", "fly", "local.iob"]:
        raise ValueError("saved-default replay specification differs")
    if Path(replay_log_path).resolve() != Path(spec["stdout"]).resolve():
        raise ValueError("replay log is not the declared fresh-process output")
    controls = [file_record(Path(row["path"])) for row in spec["control_records"]]
    controls_unchanged = controls == spec["control_records"]
    source = _source_rows(run/"inputs/release_global.csv")
    if file_record(run/"inputs/release_global.csv") != spec["source_record"]:
        raise ValueError("complete source changed during default replay")
    baseline, baseline_logs = parse_local_logs(scheduled_log_paths, source)
    replay, replay_logs = parse_local_logs([Path(replay_log_path)], source)
    before = _validate_lifetimes(baseline, source)
    after = _validate_lifetimes(replay, source)
    sequences = [{pid: [] for pid in source} for _ in range(2)]
    for rows, by_id in zip((baseline, replay), sequences):
        for row in rows:
            by_id[row["particle_id"]].append(row)
    differences, terminals = [], []
    maxima = {name: 0. for name in _FLOATS}
    exact = True
    for pid in source:
        left, right = (by_id[pid] for by_id in sequences)
        if len(left) != len(right):
            differences.append(dict(particle_id=pid, event_index=-1, field="event_count",
                                    scheduled=str(len(left)), replay=str(len(right)), absolute_difference=None))
            exact = False
        for index, (a, b) in enumerate(zip(left, right)):
            for key in ("event", "source_instance", *_FLOATS):
                if a[key] == b[key]:
                    continue
                exact = False
                delta = abs(a[key]-b[key]) if key in _FLOATS else None
                if delta is not None:
                    maxima[key] = max(maxima[key], delta)
                if delta is None or not _close(a[key], b[key]):
                    differences.append(dict(particle_id=pid, event_index=index, field=key,
                                            scheduled=str(a[key]), replay=str(b[key]), absolute_difference=delta))
        a, b = before[pid]["terminal"], after[pid]["terminal"]
        row = dict(particle_id=pid, scheduled_terminal=a["event"], replay_terminal=b["event"],
                   scheduled_exit=before[pid]["exit"] is not None, replay_exit=after[pid]["exit"] is not None)
        for field in _FLOATS:
            row["scheduled_"+field] = a[field]
            row["replay_"+field] = b[field]
            row["delta_"+field] = b[field]-a[field]
        terminals.append(row)
    for name in ("terminal_state_comparison.csv", "event_differences.csv", "comparison.json"):
        if (output/name).exists():
            raise ValueError("refuse to overwrite an existing replay comparison")
    _csv(output/"terminal_state_comparison.csv", terminals)
    _csv(output/"event_differences.csv", differences,
         ["particle_id", "event_index", "field", "scheduled", "replay", "absolute_difference"])
    result = dict(schema_version=1, role="local_frontend_saved_default_comparison",
        passed=controls_unchanged and not differences, mother_count=len(source),
        scheduled_event_count=len(baseline), replay_event_count=len(replay), exact_canonical_values=exact,
        controls_unchanged=controls_unchanged, control_records_after=controls,
        differing_field_count=len(differences), maximum_absolute_difference=maxima,
        scheduled_exit_ids=[pid for pid in source if before[pid]["exit"]],
        replay_exit_ids=[pid for pid in source if after[pid]["exit"]],
        scheduled_loss_ids=[pid for pid in source if not before[pid]["exit"]],
        replay_loss_ids=[pid for pid in source if not after[pid]["exit"]],
        scheduled_logs=baseline_logs, replay_logs=replay_logs,
        excluded_comparison_fields=["ion", "raw_line", "raw_line_number", "raw_log_path"],
        comparison_order="per original particle ID, native event sequence within that ID",
        numerical_allowance="existing analyzer _close: 32 ULP at max(1,abs(a),abs(b)); serialization only",
        gui_executed=False, qualification="default-file replay parity only; no manual GUI or physical qualification")
    _write(output/"comparison.json", result)
    return result
