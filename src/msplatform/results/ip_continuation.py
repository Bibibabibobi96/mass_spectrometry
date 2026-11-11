"""Read IP continuation ancestry, protection paths and native data selection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import record_path, verify_record
from msplatform.io.manifest_records import require_completed_terminal_publication


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def continuation_ancestry(predecessor: Path) -> list[Path]:
    """Validate and return the explicit predecessor and its bound data ancestors."""
    chain = []
    origins = []
    current = predecessor.resolve(strict=True)
    while True:
        if current in chain:
            raise ValueError("continuation ancestry contains a cycle")
        chain.append(current)
        manifest_path = current / "run_manifest.json"
        require_completed_terminal_publication(manifest_path)
        manifest = _read(manifest_path)
        if (manifest.get("project") != "dual_pressure_rectilinear_ion_processor"
                or manifest.get("mode") != "native_electrode_functional"
                or manifest.get("run_id") != current.name
                or manifest.get("status") not in {"success", "failed"}):
            raise ValueError("continuation ancestry identity differs")
        plan_record = manifest.get("inputs", {}).get("continuation_plan")
        if not plan_record:
            if any(origin != current for origin in origins):
                raise ValueError("continuation ancestry has inconsistent data origins")
            return chain
        verify_record("continuation ancestry plan", plan_record, base_dir=current)
        plan = _read(record_path(plan_record, base_dir=current))
        if (plan.get("role") != "simion_whole_unit_replay_plan" or plan.get("status") != "ready"
                or plan.get("reusable_unit_count") != 1 or plan.get("replay_unit_count") != 0
                or len(plan.get("units", [])) != 1 or plan["units"][0].get("key") != "complete_population"
                or plan["units"][0].get("action") != "reuse"):
            raise ValueError("continuation ancestry requires a complete population plan")
        origin = Path(plan["predecessor"]["run_dir"]).resolve(strict=True)
        records = manifest.get("inputs", {})
        bound = records.get("continuation_origin_manifest") or records.get("continuation_predecessor_manifest")
        if (not bound or record_path(bound, base_dir=current) != origin / "run_manifest.json"
                or str(bound.get("sha256", "")).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("continuation ancestry manifest is not bound to plan")
        verify_record("continuation ancestry manifest", bound, base_dir=current)
        origins.append(origin)
        direct = records.get("continuation_predecessor_manifest")
        if not direct:
            raise ValueError("continuation direct predecessor is not bound")
        verify_record("continuation direct predecessor", direct, base_dir=current)
        direct_path = record_path(direct, base_dir=current)
        if direct_path.name != "run_manifest.json":
            raise ValueError("continuation direct predecessor manifest differs")
        current = direct_path.parent


def continuation_protection_paths(predecessor: Path) -> list[Path]:
    """Protect direct and partial-replay provenance, including data ancestors."""
    result: list[Path] = []
    pending = [predecessor.resolve(strict=True)]
    while pending:
        current = pending.pop()
        for source in continuation_ancestry(current):
            if source in result:
                continue
            result.append(source)
            manifest = _read(source / "run_manifest.json")
            record = manifest.get("inputs", {}).get("partial_predecessor_manifest")
            if record:
                verify_record("partial provenance predecessor", record, base_dir=source)
                path = record_path(record, base_dir=source)
                if path.name != "run_manifest.json":
                    raise ValueError("partial provenance predecessor manifest differs")
                if path.parent in result:
                    raise ValueError("partial provenance ancestry contains a cycle")
                pending.append(path.parent)
    return result


def native_data_directory(run: Path) -> Path:
    """Read the frozen continuation plan, or use this run's native results."""
    plan_path = run / "inputs/simion_whole_unit_replay_plan.json"
    if not plan_path.is_file():
        return run / "simion"
    plan = _read(plan_path)
    if (plan.get("role") != "simion_whole_unit_replay_plan" or plan.get("status") != "ready"
            or plan.get("reusable_unit_count") != 1 or plan.get("replay_unit_count") != 0):
        raise ValueError("IP continuation plan does not bind a complete population")
    outputs = plan["units"][0]["terminal_outputs"]
    matches = [Path(row["path"]) for row in outputs if Path(row["path"]).name == "events.csv"]
    if len(matches) != 1 or matches[0].parent.name != "simion":
        raise ValueError("IP continuation events reference differs")
    return matches[0].parent


def native_field_sample_path(run: Path) -> Path:
    """Use locally measured field samples, otherwise the verified predecessor record."""
    local = run/"simion/native_field_samples.csv"
    if local.is_file():
        return local
    record_pathname = run/"inputs/partial_batch_replay/field_source.json"
    if record_pathname.is_file():
        return Path(_read(record_pathname)["path"])
    plan_path = run/"inputs/simion_whole_unit_replay_plan.json"
    if plan_path.is_file():
        outputs = _read(plan_path)["units"][0]["terminal_outputs"]
        matches = [Path(item["path"]) for item in outputs if Path(item["path"]).name == "native_field_samples.csv"]
        if len(matches) != 1:
            raise ValueError("continuation field sample reference differs")
        return matches[0]
    return native_data_directory(run)/"native_field_samples.csv"


def analysis_source_record(run: Path, path: Path) -> dict:
    """Reuse the already verified continuation identity for diagnostic provenance."""
    path = path.resolve()
    field_record = run/"inputs/partial_batch_replay/field_source.json"
    if field_record.is_file():
        record = _read(field_record)
        if Path(record["path"]).resolve() == path:
            return record
    plan_path = run / "inputs/simion_whole_unit_replay_plan.json"
    if plan_path.is_file():
        outputs = _read(plan_path)["units"][0]["terminal_outputs"]
        matches = [row for row in outputs if Path(row["path"]).resolve() == path]
        if len(matches) != 1 or not path.is_file():
            raise ValueError("IP continuation diagnostic source is not bound")
        return dict(path=str(path), bytes=path.stat().st_size, sha256=matches[0]["sha256"])
    return dict(path=str(path), bytes=path.stat().st_size, sha256=file_sha256(path))
