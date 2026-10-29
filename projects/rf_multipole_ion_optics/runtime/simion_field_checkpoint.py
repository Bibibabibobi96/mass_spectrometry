"""Bind an original producer's fractional PA family through its run manifest.

This is a project adapter for the existing producer-owned checkpoint pattern.
It never publishes a cache family, copies PA payloads, or opens them in SIMION.
The PowerShell owner protects the returned original payload records before use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import sys
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.strict_json import load_json_object, require_exact_keys, require_number
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import require_completed_terminal_publication

PROJECT = "rf_multipole_ion_optics"
CHECKPOINT_NAME = "simion_field_checkpoint.json"
ROLE = "multipole_simion_field_checkpoint"


def _confirmed_native(record: dict[str, Any]) -> bool:
    observation = record.get("observation", {})
    if observation.get("exit_confirmed") is not True or type(observation.get("returncode")) is not int or observation["returncode"] != 0:
        return False
    for key in ("process_id", "process_started_at_utc_ticks"):
        if type(observation.get(key)) is not int or observation[key] <= 0:
            raise ValueError(f"RF native completion lacks its actual {key}")
    return True


def validate_identity(value: dict[str, Any]) -> dict[str, Any]:
    """Validate only the static native basis inputs, excluding source and Fly."""
    require_exact_keys(value, {"schema_version", "role", "gem_sha256", "gem_includes", "grid", "cell_mm",
        "surface", "response_ids", "simion_executable_sha256", "gem2pa_arguments",
        "refine_arguments"}, "RF field identity")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["role"] != "multipole_simion_field_identity":
        raise ValueError("RF field identity version or role differs")
    if not isinstance(value["gem_includes"], dict) or any(Path(name).name != name for name in value["gem_includes"]):
        raise ValueError("RF field GEM include names differ")
    for name, digest in [(name, value[name]) for name in ("gem_sha256", "simion_executable_sha256")] + list(value["gem_includes"].items()):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789ABCDEF" for c in digest):
            raise ValueError(f"RF field {name} is invalid")
    if value["surface"] != "fractional":
        raise ValueError("RF checkpoint supports the existing fractional surface only")
    if len(value["grid"]) != 3 or any(type(n) is not int or n < 1 for n in value["grid"]):
        raise ValueError("RF field grid differs")
    if len(value["cell_mm"]) != 3:
        raise ValueError("RF field cell size differs")
    for n in value["cell_mm"]:
        if require_number(n, "RF field cell size") <= 0:
            raise ValueError("RF field cell size must be positive")
    ids = value["response_ids"]
    if not isinstance(ids, list) or not ids or any(type(n) is not int or n < 1 for n in ids) or ids != sorted(set(ids)):
        raise ValueError("RF field response namespace differs")
    for name, verb in (("gem2pa_arguments", "gem2pa"), ("refine_arguments", "refine")):
        arguments = value[name]
        if not isinstance(arguments, list) or not arguments or any(not isinstance(s, str) or not s for s in arguments) or verb not in arguments:
            raise ValueError(f"RF field {name} differs")
    return value


def _records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]


def _bound_record(manifest: dict[str, Any], path: Path, run: Path) -> dict[str, Any]:
    matches = [r for r in _records(manifest) if record_path(r, base_dir=run) == path.resolve()]
    if not matches or any(r != matches[0] for r in matches[1:]):
        raise ValueError(f"RF field member is not uniquely manifest bound: {path}")
    record = dict(matches[0]); record["path"] = str(path.resolve())
    return record


def _terminal(run: Path) -> dict[str, Any]:
    path = run / "run_manifest.json"
    require_completed_terminal_publication(path)
    value = load_json_object(path)
    if value.get("project") != PROJECT or value.get("run_id") != run.name or value.get("status") not in {"success", "failed", "interrupted"}:
        raise ValueError("RF field requires an explicit terminal producer run")
    verify_record("RF field producer config", value["run_config"], base_dir=run)
    return value


def write_checkpoint(run: Path, identity_path: Path, iob: Path, native_operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Record known native completion; the owner's final manifest binds bytes."""
    run, iob = run.resolve(), iob.resolve()
    config = load_json_object(run / "run_config.json")
    if config.get("project") != PROJECT or config.get("run_id") != run.name:
        raise ValueError("RF field checkpoint owner differs")
    if config.get("artifact_retention", {}).get("class") not in {"solver_review", "qualification"}:
        raise ValueError("Reusable RF field needs solver_review or qualification retention")
    identity = validate_identity(load_json_object(identity_path))
    facts = {r.get("operation_id"): r for r in native_operations}
    for name in ("refine",):
        if not _confirmed_native(facts.get(name, {})):
            raise ValueError(f"RF field lacks confirmed successful native {name}")
    if not iob.is_relative_to(run) or iob.suffix.lower() != ".iob":
        raise ValueError("RF producer IOB must belong to its run")
    stem = iob.with_suffix("")
    family = [Path(str(stem) + ".pa#"), Path(str(stem) + ".pa0"),
        *(Path(str(stem) + f".pa{n}") for n in identity["response_ids"]),
        Path(str(stem) + ".pa-surf")]
    layout_ready = (_confirmed_native(facts.get("build_runtime_iob", {}))
        and _confirmed_native(facts.get("inspect_runtime_iob", {})))
    members = family + ([iob, stem.with_suffix(".lua"), stem.with_suffix(".fly2"), stem.with_suffix(".con")] if layout_ready else [])
    if len(set(members)) != len(members) or any(not path.is_file() or path.is_symlink() for path in members):
        raise ValueError("RF producer field/IOB companion inventory is incomplete")
    checkpoint = run / "results" / CHECKPOINT_NAME
    if checkpoint.exists():
        previous = load_json_object(checkpoint)
        if previous.get("producer_run_directory") != str(run) or previous.get("field_identity") != identity:
            raise ValueError("RF field checkpoint cannot change its producer or field")
        if previous.get("iob_path") is not None and not layout_ready:
            raise ValueError("RF field checkpoint cannot discard completed layout")
    manifest = load_json_object(run / "run_manifest.json")
    if manifest.get("status") != "checkpoint":
        raise ValueError("RF field checkpoint cannot change a terminal producer")
    document = {"schema_version": 1, "role": ROLE, "status": "prepared",
        "producer_run_directory": str(run), "field_identity": identity,
        "identity_path": str(identity_path.resolve()), "iob_path": str(iob) if layout_ready else None,
        "controller_path": str(Path(str(stem) + ".pa0")),
        "payload_paths": [str(path) for path in members],
        "native_operations": [facts[name] for name in ("refine", "build_runtime_iob", "inspect_runtime_iob") if name in facts],
        "qualification": "native_field_prepared_not_scientific_qualification"}
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return {"checkpoint_path": str(checkpoint), "output_paths": [str(checkpoint), *document["payload_paths"]]}


def read_checkpoint(source: Path, identity_path: Path, program: Path, *, template_iob: Path | None = None,
                    template_con: Path | None = None) -> dict[str, Any]:
    """Resolve declared lineage and small records without reading PA payloads."""
    source = source.resolve()
    if source.name == "run_manifest.json":
        source = source.parent
    expected = validate_identity(load_json_object(identity_path))
    manifest = _terminal(source)
    # Reuse the existing explicit batch ancestry; never search for a latest run.
    from projects.rf_multipole_ion_optics.runtime.simion_batch_continuation import ancestry
    candidates = ancestry(source, PROJECT, manifest["mode"])
    checkpoint_record = None
    for ancestor in candidates:
        current = _terminal(ancestor)
        candidates_here = [r for r in _records(current) if record_path(r, base_dir=ancestor).name == CHECKPOINT_NAME]
        if candidates_here:
            checkpoint_record = candidates_here[0]
            if any(r != checkpoint_record for r in candidates_here[1:]):
                raise ValueError("RF field checkpoint binding is ambiguous")
            verify_record("RF field checkpoint", checkpoint_record, base_dir=ancestor)
            checkpoint_path = record_path(checkpoint_record, base_dir=ancestor)
            break
    if checkpoint_record is None:
        raise ValueError("RF predecessor has no manifest-bound completed field checkpoint; provide -NativeFieldRunPath with the same field identity, or continue from a new retained-field producer; disposed or unknown old fields cannot be reused")
    checkpoint = load_json_object(checkpoint_path)
    if type(checkpoint.get("schema_version")) is not int or checkpoint["schema_version"] != 1 or checkpoint.get("role") != ROLE or checkpoint.get("status") != "prepared":
        raise ValueError("RF field checkpoint role or status differs")
    if validate_identity(checkpoint["field_identity"]) != expected:
        raise ValueError("RF field geometry/grid/surface/Refine/SIMION identity differs")
    facts = {r.get("operation_id"): r for r in checkpoint["native_operations"]}
    if not _confirmed_native(facts.get("refine", {})):
        raise ValueError("RF field checkpoint lacks confirmed native refine")
    controller = Path(checkpoint["controller_path"])
    stem = controller.with_suffix("")
    inventory = [str(Path(str(stem) + suffix)) for suffix in
        (".pa#", ".pa0", *(f".pa{n}" for n in expected["response_ids"]), ".pa-surf")]
    if checkpoint["iob_path"] is not None:
        if not _confirmed_native(facts.get("build_runtime_iob", {})) or checkpoint["iob_path"] != str(stem.with_suffix(".iob")):
            raise ValueError("RF field checkpoint lacks confirmed native layout")
        inventory += [str(stem.with_suffix(suffix)) for suffix in (".iob", ".lua", ".fly2", ".con")]
    if checkpoint["payload_paths"] != inventory:
        raise ValueError("RF field checkpoint payload inventory differs")
    producer = Path(checkpoint["producer_run_directory"]).resolve()
    if producer != ancestor:
        verify_record("RF field producer reference", _bound_record(current, producer / "run_manifest.json", ancestor), base_dir=ancestor)
    producer_manifest = _terminal(producer)
    origin_record = _bound_record(producer_manifest, checkpoint_path, producer)
    verify_record("RF original field checkpoint", origin_record, base_dir=producer)
    identity_record = _bound_record(producer_manifest, Path(checkpoint["identity_path"]), producer)
    verify_record("RF original field identity", identity_record, base_dir=producer)
    if load_json_object(record_path(identity_record)) != expected:
        raise ValueError("RF original field identity differs from its checkpoint")
    payload_records = [_bound_record(producer_manifest, Path(path), producer) for path in checkpoint["payload_paths"]]
    for record in payload_records:
        path = record_path(record)
        if not path.is_relative_to(producer) or not path.is_file() or path.stat().st_size != record.get("bytes") or path.stat().st_mode & stat.S_IWRITE:
            raise ValueError("RF field member metadata differs")
        if ".pa" not in path.name.lower():
            verify_record("RF IOB companion", record, base_dir=producer)
    iob = Path(checkpoint["iob_path"]) if checkpoint["iob_path"] is not None else None
    layout_differs = (iob is None or not _confirmed_native(facts.get("inspect_runtime_iob", {}))
        or file_sha256(iob.with_suffix(".lua")) != file_sha256(program))
    for name, current_path in (("simion_layout_template_iob", template_iob), ("simion_layout_template_con", template_con)):
        if current_path is not None:
            old = producer_manifest.get("inputs", {}).get(name)
            if not isinstance(old, dict) or old.get("sha256") != file_sha256(current_path):
                layout_differs = True
    return {"checkpoint_path": str(checkpoint_path), "producer_manifest": str(producer / "run_manifest.json"),
        "producer_manifest_sha256": file_sha256(producer / "run_manifest.json"),
        "iob_path": str(iob) if iob is not None else None, "controller_path": checkpoint["controller_path"],
        "requires_iob_rebind": layout_differs,
        "payload_records": payload_records,
        "small_records": [origin_record, identity_record],
        "protected_paths": [str(path) for path in dict.fromkeys([*candidates, producer])]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("write", "read"))
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--iob", type=Path)
    parser.add_argument("--program", type=Path)
    parser.add_argument("--template-iob", type=Path)
    parser.add_argument("--template-con", type=Path)
    args = parser.parse_args()
    if args.action == "write":
        if args.iob is None:
            parser.error("write requires --iob")
        result = write_checkpoint(args.run, args.identity, args.iob, json.load(sys.stdin))
    else:
        if args.program is None:
            parser.error("read requires --program")
        result = read_checkpoint(args.run, args.identity, args.program, template_iob=args.template_iob, template_con=args.template_con)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
