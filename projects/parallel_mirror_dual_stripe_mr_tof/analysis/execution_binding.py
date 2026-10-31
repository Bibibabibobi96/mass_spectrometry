"""Bind one existing MR condition's explicit context and release contracts."""
import math
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json
from common.ion_release.release import validate_release_spec


def resolve_execution_binding(repo_root: Path, project_id: str, bindings: dict[str, str],
                              *, request_path: Path | None = None) -> dict[str, Any]:
    if project_id != "parallel_mirror_dual_stripe_mr_tof":
        raise ValueError("MR execution binding project identity differs")
    condition = load_json(Path(bindings["condition_path"]))
    context_path = Path(bindings["context_path"]).resolve()
    context = load_json(context_path)
    if condition.get("schema_version") != 1 or condition.get("role") != "mrtof_native_candidate_campaign_condition":
        raise ValueError("Condition identity is invalid")
    if context.get("schema_version") != 1 or context.get("role") != "mrtof_native_candidate_condition_context":
        raise ValueError("Condition context identity is invalid")
    for key in ("K", "accelerator_y"):
        if isinstance(condition.get(key), bool) or not math.isfinite(float(condition[key])):
            raise ValueError(f"Condition {key} must be finite")
    records = []
    missing = []
    resolved = {}
    for key in ("contract_path", "fixed_grid_mirror_run_manifest", "geometry_review_run_path",
                "native_corridor_bank_run_path", "native_system_runtime_bundle_path", "source_definition_path",
                "oa_base_release_spec_path", "oa_request_path", "native_runtime_checkpoint_path"):
        value = context.get(key)
        if key == "native_runtime_checkpoint_path" and not value:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"Condition context is missing {key}")
        source = Path(value)
        path = (source if source.is_absolute() else context_path.parent/source).resolve()
        if path.is_dir():
            path = path/"run_manifest.json"
        if not path.is_file() or path.suffix.lower() != ".json":
            missing.append(f"{key}: existing small JSON authority is missing: {path}")
            continue
        resolved[key] = path
        records.append(str(path))
    if missing:
        return dict(project_id=project_id, structural_variant_id=None, authorized_run_id=None,
                    input_paths=records, preparation_required=missing)
    release = load_json(resolved["oa_base_release_spec_path"])
    validate_release_spec(release)
    return dict(project_id=project_id, structural_variant_id=None, authorized_run_id=None,
                operating_points=[dict(mass=dict(value=release["species"]["mass_amu"], unit="Da"),
                                       charge_state=release["species"]["charge_state"])], input_paths=records)
