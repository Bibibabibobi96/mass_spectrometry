"""Plan RF whole-batch continuation from explicit, protected owner runs."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import require_completed_terminal_publication
from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def ancestry(predecessor: Path, project: str, mode: str = "resolved_design_transport") -> list[Path]:
    """Follow only manifest-bound direct predecessors; reject cycles and drift."""
    current, chain = predecessor.resolve(strict=True), []
    while True:
        if current in chain:
            raise ValueError("RF continuation ancestry contains a cycle")
        chain.append(current)
        manifest_path = current / "run_manifest.json"
        require_completed_terminal_publication(manifest_path)
        manifest = read(manifest_path)
        if (manifest.get("project") != project or manifest.get("mode") != mode
                or manifest.get("run_id") != current.name or manifest.get("status") not in {"success", "failed", "interrupted"}):
            raise ValueError("RF continuation ancestor is not a terminal owner run")
        inputs = manifest.get("inputs", {})
        plan_record = inputs.get("continuation_plan")
        parent_record = inputs.get("continuation_predecessor_manifest")
        if not plan_record and not parent_record:
            return chain
        if not plan_record or not parent_record:
            raise ValueError("RF continuation provenance is incomplete")
        verify_record("RF continuation plan", plan_record, base_dir=current)
        verify_record("RF continuation parent", parent_record, base_dir=current)
        plan = read(record_path(plan_record, base_dir=current))
        parent = record_path(parent_record, base_dir=current)
        if (parent.name != "run_manifest.json" or plan.get("role") != "simion_whole_unit_replay_plan"
                or plan.get("status") != "ready" or str(parent.parent) != plan["predecessor"]["run_dir"]
                or str(parent_record["sha256"]).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("RF continuation parent binding differs")
        current = parent.parent.resolve(strict=True)


def prepare(run: Path, predecessor: Path, cases: list[str], retention: str, mechanical: bool,
            input_names: list[str] | None = None, output_layout: str = "finite") -> dict:
    run, predecessor = run.resolve(), predecessor.resolve(strict=True)
    if run == predecessor:
        raise ValueError("RF continuation requires a new run")
    current = read(run / "run_config.json")
    chain = ancestry(predecessor, current["project"], current["mode"])
    manifest = read(predecessor / "run_manifest.json")
    verify_record("RF predecessor configuration", manifest["run_config"], base_dir=predecessor)
    previous = read(predecessor / "run_config.json")
    if previous.get("parameters", {}).get("case_set") != current.get("parameters", {}).get("case_set"):
        raise ValueError("RF predecessor case set differs")
    records, inputs = manifest.get("inputs", {}), current.get("inputs", {})
    names = input_names or ["multipole_resolved_design", "particle_source", "solver_numerics", "simion_grid_audit",
             "simion_gem", "simion_fly2", "simion_source_states", "simion_rf_drive_kernel",
             "clock_authority", "instrument_epoch", "simion_layout_template_iob", "simion_layout_template_con"]
    if mechanical:
        names.extend(["mechanical_exit_interface", "mechanical_exit_observation"])
    elif any(name in records for name in ("mechanical_exit_interface", "mechanical_exit_observation")):
        raise ValueError("RF predecessor mechanical exit mode differs")
    for name in names:
        old, new = records.get(name), inputs.get(name)
        if not isinstance(old, dict) or not old.get("exists") or not isinstance(new, str):
            raise ValueError(f"RF predecessor lacks Fly identity: {name}")
        provenance = current.get("provenance", {})
        layout = provenance.get("simion_layout_template", {})
        existing = {"particle_source": provenance.get("particle_source_sha256"),
                    "simion_layout_template_iob": layout.get("iob_sha256"),
                    "simion_layout_template_con": layout.get("con_sha256")}
        digest = existing.get(name) or file_sha256(Path(new))
        if str(digest).upper() != str(old.get("sha256", "")).upper():
            raise ValueError(f"RF predecessor Fly identity differs: {name}")
    def frozen(name: str) -> dict:
        record = records.get(name)
        if not isinstance(record, dict):
            raise ValueError(f"RF predecessor lacks {name}")
        verify_record(name, record, base_dir=predecessor)
        return read(record_path(record, base_dir=predecessor))
    old_basis = frozen("simion_pa_basis_identity") if input_names is None else {}
    new_basis = read(Path(inputs["simion_pa_basis_identity"])) if input_names is None else {}
    # The existing cache key includes the entire runner source. Fly is instead
    # bound to the frozen physical case projection and the native program.
    old_basis.pop("builder_identity", None)
    new_basis.pop("builder_identity", None)
    if old_basis != new_basis:
        raise ValueError("RF predecessor PA basis differs")
    old_fly = frozen("simion_fly_physics")
    new_fly = read(Path(inputs["simion_fly_physics"]))
    for document in (old_fly, new_fly):
        declared_cases = document.get("cases")
        if not isinstance(declared_cases, dict) or any(case not in declared_cases for case in cases):
            raise ValueError("RF predecessor simion_fly_physics case projection differs")
        document["cases"] = {case: declared_cases[case] for case in cases}
    if (old_fly.get("role") != "multipole_simion_fly_physics"
            or json.dumps(old_fly, sort_keys=True, allow_nan=False) != json.dumps(new_fly, sort_keys=True, allow_nan=False)):
        raise ValueError("RF predecessor simion_fly_physics differs")
    old_inventory = frozen("code_inventory") if input_names is None else {"files": []}
    new_inventory = read(Path(inputs["code_inventory"])) if input_names is None else {"files": []}
    source_code = {
        "projects/rf_multipole_ion_optics/runtime/simion_particle_source.py",
        "projects/rf_multipole_ion_optics/runtime/particle_source_preflight.py",
        "projects/rf_multipole_ion_optics/core/interface_geometry.py",
        "common/simion/particle_source.py", "common/contracts/particle_physics.py",
    }
    def simion_code(inventory: dict) -> dict[str, str]:
        return {row["path"]: row["sha256"] for row in inventory["files"]
                if row["path"].startswith("projects/rf_multipole_ion_optics/simion/") or row["path"] in source_code}
    old_code, new_code = simion_code(old_inventory), simion_code(new_inventory)
    if input_names is None and (not source_code <= old_code.keys() or not source_code <= new_code.keys() or old_code != new_code):
        raise ValueError("RF predecessor SIMION physics or batch source code differs")
    partition = frozen("simion_execution_batch_plan")
    batches = partition.get("batches")
    if not isinstance(batches, list) or not batches or partition.get("batch_count") != len(batches):
        raise ValueError("RF predecessor partition differs")
    next_id = 1
    for index, batch in enumerate(batches, 1):
        if (batch.get("index") != index or batch.get("particle_id_min") != next_id
                or batch.get("particle_id_max", 0) < next_id or batch.get("simion_particle_id_offset") != next_id - 1):
            raise ValueError("RF predecessor population partition differs")
        next_id = batch["particle_id_max"] + 1
    if next_id - 1 != partition.get("particle_count"):
        raise ValueError("RF predecessor population does not close")
    inherited = {}
    if records.get("continuation_plan"):
        inherited = {item["key"]: item for item in frozen("continuation_plan")["units"] if item["action"] == "reuse"}
    units = []
    for case in cases:
        for batch in batches:
            index = batch["index"]
            receipt = Path("results") / f"simion_batch_completion__{case}__batch_{index:02d}.json"
            paths = [receipt]
            complete = (predecessor / receipt).is_file()
            if complete:
                fact = read(predecessor / receipt)
                if (fact.get("role") != "multipole_simion_completed_batch" or fact.get("case") != case
                        or fact.get("batch_index") != index or fact.get("particle_id_min") != batch["particle_id_min"]
                        or fact.get("particle_id_max") != batch["particle_id_max"]
                        or fact.get("particle_count") != batch["particle_id_max"] - batch["particle_id_min"] + 1):
                    raise ValueError("RF batch receipt identity differs")
                declared = fact.get("outputs")
                if not isinstance(declared, list):
                    raise ValueError("RF batch receipt outputs differ")
                by_name = {Path(item).name: item for item in declared}
                if len(by_name) != len(declared):
                    raise ValueError("RF batch receipt has duplicate names")
                suffix = "" if len(batches) == 1 else f"__batch_{index:02d}"
                required = (["simion_stdout.txt", f"particle_state{suffix}.csv", f"solver_summary{suffix}.json"]
                            if output_layout == "prepared" else
                            [f"simion_stdout__fly__{case}__batch_{index}.txt", f"particle_states__{case}{suffix}.csv",
                             f"simion_summary__{case}{suffix}.json"])
                if mechanical:
                    required.append(f"mechanical_exit_states__{case}{suffix}.csv")
                if retention != "compact":
                    required.append(f"trajectory_samples{suffix}.csv" if output_layout == "prepared" else
                                    f"trajectory_samples__{case}{suffix}.csv")
                if not set(required) <= set(by_name):
                    complete = False
                else:
                    for name in required:
                        path = Path(by_name[name])
                        if path.is_absolute() or ".." in path.parts:
                            raise ValueError("RF receipt output escapes its owner")
                        paths.append(path)
                    complete = all((predecessor / path).is_file() for path in paths)
            units.append(WholeUnitReplayUnit(f"{case}.batch_{index:02d}", tuple(paths), complete))
    replay = build_whole_unit_replay_plan(predecessor_run_dir=predecessor, output_dir=run / "inputs", units=units)
    with tempfile.TemporaryDirectory(prefix="rf_continuation_") as temp:
        for unit in replay["units"]:
            prior = inherited.get(unit["key"])
            if unit["action"] != "replay" or prior is None:
                continue
            paths = tuple(Path(item["path"]) for item in prior["terminal_outputs"])
            names = {path.name for path in paths}
            if mechanical and not any(name.startswith("mechanical_exit_states__") for name in names):
                continue
            if retention != "compact" and not any(name.startswith("trajectory_samples__") for name in names):
                continue
            owners = {root for root in chain if all(path.is_relative_to(root) for path in paths)}
            if len(owners) != 1:
                raise ValueError("RF inherited batch origin is outside protected ancestry")
            checked = build_whole_unit_replay_plan(predecessor_run_dir=owners.pop(), output_dir=Path(temp),
                                                  units=[WholeUnitReplayUnit(unit["key"], paths, True)])
            if checked["reusable_unit_count"] != 1 or checked["units"][0]["terminal_outputs"] != prior["terminal_outputs"]:
                raise ValueError("RF inherited batch differs")
            unit.update(checked["units"][0])
    replay["reusable_unit_count"] = sum(item["action"] == "reuse" for item in replay["units"])
    replay["replay_unit_count"] = sum(item["action"] == "replay" for item in replay["units"])
    (run / "inputs/simion_whole_unit_replay_plan.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    return {"batch_plan": partition, "replay": replay}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--mode", default="resolved_design_transport")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--case", action="append")
    parser.add_argument("--retention", default="compact")
    parser.add_argument("--mechanical", action="store_true")
    parser.add_argument("--input", action="append", dest="input_names")
    parser.add_argument("--output-layout", choices=("finite", "prepared"), default="finite")
    args = parser.parse_args()
    result = ancestry(args.predecessor, args.project, args.mode) if args.run_dir is None else prepare(
        args.run_dir, args.predecessor, args.case, args.retention, args.mechanical,
        args.input_names, args.output_layout)
    print(json.dumps([str(item) for item in result] if isinstance(result, list) else result))


if __name__ == "__main__":
    main()
