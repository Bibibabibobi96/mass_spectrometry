"""Select sealed mass-spectrum records and freeze the existing analysis consumer.

No native model, PA, source resampling or parent publication is performed here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT = "single_reflection_oa_tof_mass_analyzer"
PREFIX = f"projects/{PROJECT}"
ANALYSIS_MODULE = f"projects.{PROJECT}.analysis.mass_spectrum"
CODE_PATHS = (
    f"{PREFIX}/analysis/mass_spectrum_reanalysis.py",
    f"{PREFIX}/analysis/mass_spectrum.py",
    f"{PREFIX}/analysis/reference_analysis.py",
    f"{PREFIX}/analysis/reference_analysis_core.py",
    f"{PREFIX}/analysis/solver_diagnostics.py",
    "common/analysis/peak_metrics.py",
    "common/contracts/file_identity.py",
)

def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def select_source(source: Path, consumer_artifact_root: Path, stopped: Path | None = None) -> dict:
    """Verify only the consumed small-record projection, under the caller's guard."""
    from common.contracts.capacity_ledger import load_capacity_ledger
    from common.contracts.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
    from common.contracts.verify_run_manifest import record_path, verify_record
    from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication

    source = source.resolve(strict=True)
    manifest_path = source / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest_record = file_record(manifest_path)
    stopped_record = file_record(stopped.resolve(strict=True)) if stopped else None
    owner = resolve_consumed_run_capacity_owner(
        manifest_record, consumer_artifact_root=consumer_artifact_root,
        stopped_receipt_record=stopped_record)
    manifest = read_json(manifest_path)
    config = read_json(source / "run_config.json")
    if (manifest.get("project") != PROJECT or manifest.get("mode") != "mass_spectrum_candidate"
            or config.get("role") not in (None, "oa_tof_mass_spectrum_run_config")):
        raise ValueError("Reanalysis requires a mass_spectrum_candidate parent and its original config.")
    root = Path(owner["artifact_root"])
    ledger = load_capacity_ledger(root)
    entries = [] if ledger is None else [
        item for item in ledger["objects"]
        if item.get("path") == source.relative_to(root).as_posix()]
    if (len(entries) != 1 or entries[0].get("status") != "ready"
            or entries[0].get("class") not in ("light_evidence", "rebuildable_payload")):
        raise ValueError("Source writing is not sealed. ACTION=complete_or_seal_with_original_owner")
    # An interrupted preparation marker is not a stopped-writer certificate.
    if manifest["status"] not in ("success", "failed", "checkpoint"):
        raise ValueError("Source lacks sufficient sealed terminal evidence. ACTION=original_owner_finalization")

    def selected_input(name: str) -> dict:
        record = manifest.get("inputs", {}).get(name)
        if not isinstance(record, dict):
            raise ValueError(f"Parent manifest lacks consumed input: {name}")
        path = record_path(record, base_dir=source)
        declared = config.get("inputs", {}).get(name)
        if not isinstance(declared, str):
            raise ValueError(f"Parent config lacks consumed input: {name}")
        declared_path = Path(declared)
        if not declared_path.is_absolute():
            declared_path = source / declared_path
        if declared_path.resolve() != path or not path.is_relative_to(source / "inputs"):
            raise ValueError(f"Parent input binding differs: {name}")
        verify_record(name, record, base_dir=source)
        return {**record, "path": str(path)}

    def selected_output(relative: str) -> dict:
        path = source / relative
        matches = [r for r in manifest.get("outputs", []) if record_path(r, base_dir=source) == path]
        if len(matches) != 1:
            raise ValueError(f"Parent manifest lacks a unique consumed output: {relative}")
        verify_record(relative, matches[0], base_dir=source)
        return {**matches[0], "path": str(path)}

    inputs = {name: selected_input(name) for name in ("mode_config", "resolved_geometry")}
    mode = read_json(Path(inputs["mode_config"]["path"]))
    # Use the actual public mode validator after freezing; reject unsafe path
    # components here before selecting the species' existing native reports.
    if (mode.get("schema_version") != 1 or mode.get("mode") != "mass_spectrum_candidate"
            or mode.get("role") != "oa_tof_candidate_mass_spectrum_mode"):
        raise ValueError("Mass-spectrum mode identity is invalid.")
    species = mode.get("species")
    if not isinstance(species, list) or len(species) < 3:
        raise ValueError("Parent mass-spectrum species are missing.")
    ids = [s.get("species_id") for s in species]
    if (any(not isinstance(s, str) or not s or Path(s).name != s or "/" in s or "\\" in s
            or s in (".", "..") for s in ids) or len(set(ids)) != len(ids)):
        raise ValueError("Parent species identifiers are invalid or duplicated.")
    counts = [s.get("particle_count") for s in species]
    if any(type(n) is not int or n < 1 for n in counts):
        raise ValueError("Parent emitted counts are invalid.")
    exports = {"simion_csv": selected_output("results/simion_particles.csv"),
               "simion_summary": selected_output("results/simion_summary.json")}
    if read_json(Path(exports["simion_summary"]["path"])).get("Hit") != sum(counts):
        raise ValueError("Parent SIMION full-mother detection requirement is not satisfied.")
    for entry in species:
        name, count = entry["species_id"], entry["particle_count"]
        exports[f"comsol_{name}"] = selected_output(f"comsol/{name}.csv")
        report = selected_output(f"logs/{name}.report.txt")
        if f"DETECTED={count}/{count}" not in Path(report["path"]).read_text(encoding="utf-8-sig"):
            raise ValueError(f"Parent COMSOL complete detection evidence is absent: {name}")
        exports[f"report_{name}"] = report
    return {"manifest_record": manifest_record, "config_record": {**manifest["run_config"], "path": str(source / "run_config.json")},
            "stopped_receipt_record": stopped_record, "run_id": config["run_id"],
            "source_directory": str(source), "artifact_root": str(root),
            "inputs": inputs, "exports": exports,
            "execution": config.get("execution", {}),
            "particle_source_provenance": config.get("particle_source_provenance", [])}


def freeze_analysis(repo: Path, destination: Path, selection: dict) -> dict:
    """Freeze just the imported analysis files and the parent's physical resource."""
    from common.contracts.frozen_inputs import freeze_file
    from common.contracts.verify_run_manifest import verify_record

    for name, record in selection["inputs"].items():
        verify_record(name, record)

    paths = set(CODE_PATHS)
    for relative in CODE_PATHS:
        for directory in Path(relative).parents:
            if str(directory) != "." and (repo / directory / "__init__.py").is_file():
                paths.add((directory / "__init__.py").as_posix())
    inventory = []
    for relative in sorted(paths):
        (destination / relative).parent.mkdir(parents=True, exist_ok=True)
        inventory.append({"path": relative,
                          "sha256": freeze_file(repo / relative, destination / relative)["sha256"]})
    resolved = Path(selection["inputs"]["resolved_geometry"]["path"])
    (destination / PREFIX / "config").mkdir(parents=True, exist_ok=True)
    inventory.append({"path": f"{PREFIX}/config/resolved_geometry.json",
                      "sha256": freeze_file(resolved, destination / PREFIX / "config/resolved_geometry.json")["sha256"]})
    mode = destination.parent / "mass_spectrum.json"
    freeze_file(Path(selection["inputs"]["mode_config"]["path"]), mode)
    return {"schema_version": 1, "role": "frozen_code_inventory", "files": inventory}


def run_analysis(selection_path: Path, code_root: Path, output: Path) -> dict:
    """The sole scientific consumer is the existing mass-spectrum analyzer."""
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum import analyze_mass_spectrum

    selection = read_json(selection_path)
    # Referenced CSVs are protected by the owning PS capacity SourceReferences.
    # There is no model reload, PA materialization or synthetic source data.
    result = analyze_mass_spectrum(
        code_root.parent / "mass_spectrum.json",
        Path(selection["source_directory"]) / "comsol",
        Path(selection["exports"]["simion_csv"]["path"]), output)
    # Reuse the analyzer's existing identities; do not reread the CSV payload.
    expected = {"mode_config": selection["inputs"]["mode_config"]["sha256"],
                "simion_csv": selection["exports"]["simion_csv"]["sha256"]}
    expected.update({name: record["sha256"] for name, record in selection["exports"].items()
                     if name.startswith("comsol_")})
    if any(str(result["inputs"].get(name, "")).lower() != identity.lower()
           for name, identity in expected.items()):
        raise ValueError("Consumed mass-spectrum record differs from its frozen source selection.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    select = commands.add_parser("select")
    select.add_argument("--source", type=Path, required=True)
    select.add_argument("--artifact-root", type=Path, required=True)
    select.add_argument("--stopped-receipt", type=Path)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--repo", type=Path, required=True)
    freeze.add_argument("--destination", type=Path, required=True)
    freeze.add_argument("--selection", type=Path, required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--selection", type=Path, required=True)
    analyze.add_argument("--code-root", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "select":
        result = select_source(args.source, args.artifact_root, args.stopped_receipt)
    elif args.action == "freeze":
        result = freeze_analysis(args.repo, args.destination, read_json(args.selection))
    else:
        result = run_analysis(args.selection, args.code_root, args.output)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
