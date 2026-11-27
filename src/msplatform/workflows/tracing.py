"""Public recipe execution and managed-result reread across supported tracers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from msplatform.recipes import load_recipe
from msplatform.results.particle_data import read_particle_data, summarize_particle_data
from msplatform.storage import ArtifactStore


def run_recipe(recipe_path: str | Path, *, artifact_root: str | Path,
               high_water_bytes: int | None = None, low_water_bytes: int | None = None,
               safety_bytes: int = 0, reserve_bytes: int = 0,
               source_revision: str | None = None,
               cancelled: Callable[[], bool] | None = None, context=None,
               tracking_execution: dict[str, Any] | None = None) -> dict[str, Any]:
    """Snapshot one author, then execute the selected validated recipe exactly once."""
    loaded = load_recipe(recipe_path)
    schema = loaded.to_dict()["schema_version"]
    if schema == 2:
        from .native_tracing import run_loaded_recipe
    else:
        if tracking_execution is not None:
            raise ValueError("tracking execution controls require a native SIMION recipe")
        from .reference_tracing import run_loaded_recipe
    return run_loaded_recipe(loaded, artifact_root=artifact_root,
        high_water_bytes=high_water_bytes, low_water_bytes=low_water_bytes,
        safety_bytes=safety_bytes, reserve_bytes=reserve_bytes,
        source_revision=source_revision, cancelled=cancelled, context=context,
        **({"tracking_execution": tracking_execution} if tracking_execution is not None else {}))


def inspect_results(run_id: str, *, artifact_root: str | Path) -> dict[str, Any]:
    """Reopen a managed run, validate its files, then recompute complete-cohort statistics."""
    store = ArtifactStore(artifact_root)
    state = store.run_status(run_id)
    if state["publication_status"] != "ready":
        return {"run_state": state, "summary": None}
    path = store.inspect_run(run_id)
    collection_path = path / "collection.json"
    if collection_path.is_file():
        from msplatform.contracts.field_intervention import _case
        collection = json.loads(collection_path.read_text(encoding="utf-8"))
        if (not isinstance(collection, dict) or set(collection) != {"schema_version", "role", "cases"}
                or collection["schema_version"] != 1 or collection["role"] not in {"field_intervention_collection", "oa_focus_field_contrast_collection"}
                or not isinstance(collection["cases"], list) or not collection["cases"]):
            raise ValueError("invalid field intervention collection")
        resolved = json.loads((path / "resolved.json").read_text(encoding="utf-8"))
        focus_collection = collection["role"] == "oa_focus_field_contrast_collection"
        expected_cases = resolved["recording"].get("field_interventions")
        if focus_collection:
            modes = resolved["recording"].get("oa_focus_field_modes")
            if not isinstance(modes, list) or len(modes) != 4 or set(modes) != {"native", "zone1_ideal", "zone2_ideal", "full_ideal"}:
                raise ValueError("invalid frozen OA focus field modes")
            expected_cases = [{"id": mode, "selector": mode} for mode in modes]
        if not isinstance(expected_cases, list) or len(expected_cases) != len(collection["cases"]):
            raise ValueError("collection differs from the frozen author cases")
        summaries, mother = [], None
        for case_index, (expected, item) in enumerate(zip(expected_cases, collection["cases"], strict=True)):
            case_id = expected["id"] if focus_collection else _case(expected)[0]
            if (not isinstance(item, dict) or set(item) != {"id", "selector", "path", "summary"}
                    or item["id"] != case_id or item["selector"] != expected["selector"]
                    or item["path"] != f"cases/{case_index:04d}"):
                raise ValueError("collection case identity differs from the frozen author")
            case_path = path / "cases" / f"{case_index:04d}"
            data = read_particle_data(case_path)
            summary = summarize_particle_data(data)
            recorded = json.loads((case_path / "summary.json").read_text(encoding="utf-8"))
            if summary != recorded or summary != item["summary"]:
                raise ValueError("collection statistics differ from published particle data")
            cohort = {"initial_states": data["initial_states"],
                      "clock": data["metadata"]["clock"], "frame_id": data["metadata"]["frame_id"],
                      "species": data["metadata"].get("species"),
                      "initial_state_basis": data["metadata"]["initial_state_basis"]}
            if mother is not None and mother != cohort:
                raise ValueError("collection cases do not share the same initial cohort, frame and clock")
            mother = cohort
            summaries.append({"id": case_id, "selector": item["selector"], "summary": summary})
        return {"run_path": str(path), "run_state": state,
                "summary": {"role": collection["role"], "cases": summaries},
                "provenance": json.loads((path / "provenance.json").read_text(encoding="utf-8"))}
    data = read_particle_data(path)
    summary = summarize_particle_data(data)
    recorded = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    legacy = "detector_observation" not in data["data_integrity"]
    if legacy:
        from msplatform.results.particle_data import _summarize_particle_data
        expected = _summarize_particle_data(data, legacy=True)
    else:
        expected = summary
    if expected != recorded:
        raise ValueError("recorded statistics differ from published particle data")
    result = {"run_path": str(path), "run_state": state, "summary": summary,
              "provenance": json.loads((path / "provenance.json").read_text(encoding="utf-8"))}
    if legacy:
        result["stored_summary"] = recorded
    return result
