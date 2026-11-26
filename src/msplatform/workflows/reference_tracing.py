"""Installed continuous reference workflow: compile, integrate, publish and reread.

Field and complete particle batches have dependency keys independent of labels
and repository HEAD. Evidence is retained in each run, separate from expendable
performance caches. This workflow never invokes a commercial backend.
"""
from __future__ import annotations

from contextlib import ExitStack
from importlib.metadata import version
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

import numpy as np
import scipy

from msplatform.io.file_identity import canonical_json_sha256, file_sha256
from msplatform.recipes import load_recipe, validate_recipe
from msplatform.results.particle_data import read_particle_data, summarize_particle_data, write_particle_data
from msplatform.storage import ArtifactStore
from msplatform.tracing import TraceResult, preflight, trace_particles
import msplatform.fields as fields_implementation
import msplatform.tracing as tracer_implementation
import msplatform.analysis.particle_census as census_implementation
import msplatform.results.particle_data as data_implementation


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def _implementations() -> dict[str, str]:
    return {"tracer": file_sha256(tracer_implementation.__file__),
            "fields": file_sha256(fields_implementation.__file__),
            "cohort": file_sha256(census_implementation.__file__),
            "particle_data": file_sha256(data_implementation.__file__),
            "numpy": np.__version__, "scipy": scipy.__version__,
            "distribution": version("mass-spectrometry-analysis"), "data_schema": "si_particle_data_1"}


def _merged(results: list[dict[str, Any]]) -> TraceResult:
    status = "succeeded"
    if any(row["execution_status"] == "failed" for row in results):
        status = "failed"
    elif any(row["execution_status"] == "cancelled" for row in results):
        status = "cancelled"
    return TraceResult(
        initial_states=[p for r in results for p in r["initial_states"]],
        terminal_states=[p for r in results for p in r["terminal_states"]],
        events=[p for r in results for p in r["events"]],
        trajectories={name: np.concatenate([r["trajectories"][name] for r in results], axis=0)
                      for name in ("particle_id", "time_s", "position_m", "velocity_m_s")},
        execution_status=status,
        data_integrity={"status": "complete" if all(r["data_integrity"].get("status") == "complete" for r in results)
                        else "incomplete", "batch_integrity": [r["data_integrity"] for r in results]},
    )


def _batch(store: ArtifactStore, recipe: Mapping[str, Any], particle: dict, field_key: str,
           implementation: dict, cancelled: Callable[[], bool] | None,
           stack: ExitStack) -> tuple[dict, dict]:
    scientific = {k: recipe[k] for k in ("frame_id", "clock", "constants", "gas_environment", "numerics",
                                       "surfaces", "recording", "particle_tracer", "assembly")}
    key = canonical_json_sha256({"role": "complete_particle_batch", "field": field_key,
                                "input": scientific, "particle": particle, "implementation": implementation})
    cached = stack.enter_context(store.claim_key(key)) if cancelled is None else None
    reused = cached is not None and cancelled is None
    if reused:
        asset_id, path = cached
        data = read_particle_data(path)
        written = 0
    else:
        batch_recipe = {**recipe, "initial_states": [particle]}
        result = trace_particles(batch_recipe, cancelled=cancelled)
        work = store.new_work()
        write_particle_data(work, result, metadata={"frame_id": recipe["frame_id"], "clock": recipe["clock"]})
        written = sum(p.stat().st_size for p in work.iterdir() if p.is_file())
        # Failed/cancelled execution is retained as run evidence, never a reusable success cache.
        if result.execution_status == "succeeded":
            asset_id, path = stack.enter_context(store.put_asset_claimed("particle_batch", key, work, retention="cache"))
        else:
            asset_id, path = None, work
        data = read_particle_data(path)
        if asset_id is None:
            store.discard_work(work)
            written = 0
    return data, {"particle_id": particle["particle_id"], "task_key": key,
                  "asset_id": asset_id, "reused": reused, "new_payload_bytes": written}


def run_recipe(recipe_path: str | Path, *, artifact_root: str | Path,
               high_water_bytes: int | None = None, low_water_bytes: int | None = None,
               safety_bytes: int = 0, reserve_bytes: int = 0,
               source_revision: str | None = None,
               cancelled: Callable[[], bool] | None = None,
               context=None) -> dict[str, Any]:
    """Run an author TOML through the public pipeline and return independently reread statistics.

The deployment supplies disk watermarks and an optional additional peak budget.
Numerical failures and cancellation publish explicit incomplete evidence.
"""
    loaded = load_recipe(recipe_path)
    recipe = loaded.to_dict()
    if recipe["schema_version"] == 2:
        from .native_tracing import run_loaded_recipe
        return run_loaded_recipe(loaded, context=context, artifact_root=artifact_root,
            high_water_bytes=high_water_bytes, low_water_bytes=low_water_bytes, safety_bytes=safety_bytes,
            reserve_bytes=reserve_bytes, source_revision=source_revision, cancelled=cancelled)
    if context is not None:
        raise ValueError("reference tracing does not consume a native execution context")
    validate_recipe(recipe)
    preflight(recipe)
    if source_revision is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", source_revision):
        raise ValueError("source_revision must be an explicit full repository SHA")
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError("reserve_bytes must be a nonnegative integer")
    store = ArtifactStore(artifact_root, high_water_bytes=high_water_bytes,
                          low_water_bytes=low_water_bytes, safety_bytes=safety_bytes)
    run_id, run_work = store.begin_run()
    _write_json(run_work / "resolved.json", recipe)
    (run_work / "author.toml").write_bytes(loaded.source_bytes)
    # Dense samples require 64 bytes/row. Reserve for cache and run copies plus
    # conservative table/container metadata; deployments can increase the peak.
    estimated = len(recipe["initial_states"]) * (128 * recipe["numerics"]["sample_count"] + 1048576)
    budget = max(reserve_bytes, estimated)
    with store.run_writer(run_id):
        try:
            with store.reserve(budget) as reservation:
                store.mark_running(run_id)
                _execute_recipe(store, recipe, run_work, run_id, reservation, budget, source_revision, cancelled)
        except OSError as error:
            state = store.run_status(run_id)
            if state["execution_status"] == "queued":
                store.set_queued_reason(run_id, str(error))
            else:
                store.finish_run(run_id, "failed", reason=str(error))
            raise OSError(f"run {run_id}: {error}") from error
        except KeyboardInterrupt:
            store.finish_run(run_id, "cancelled", reason="keyboard_interrupt")
            raise
        except Exception as error:
            store.finish_run(run_id, "failed", reason=str(error))
            raise
    inspected = inspect_results(run_id, artifact_root=artifact_root)
    return {"run_id": run_id, "artifact_root": str(Path(artifact_root).resolve()), **inspected}


def _execute_recipe(store: ArtifactStore, recipe: dict, run_work: Path, run_id: str,
                    reservation: str, budget: int, source_revision: str | None,
                    cancelled: Callable[[], bool] | None) -> None:
    """Compute and publish one admitted run without changing its frozen identity."""
    implementation = _implementations()
    field_key = canonical_json_sha256({"role": "uniform_field", "field": recipe["field_source"],
                                      "frame_id": recipe["frame_id"], "implementation": implementation["fields"]})
    stopped = False

    def cancellation() -> bool:
        nonlocal stopped
        stopped = stopped or bool(cancelled and cancelled())
        return stopped

    with ExitStack() as claims:
        written = 0
        field = claims.enter_context(store.claim_key(field_key))
        field_reused = field is not None
        if field is None:
            work = store.new_work()
            _write_json(work / "field.json", recipe["field_source"])
            written += (work / "field.json").stat().st_size
            field_id, field_path = claims.enter_context(store.put_asset_claimed("field", field_key, work, retention="cache"))
        else:
            field_id, field_path = field
        actual_field = json.loads((field_path / "field.json").read_text(encoding="utf-8"))
        if actual_field != recipe["field_source"]:
            raise ValueError("published field does not match resolved recipe")
        results, batches = [], []
        for particle in recipe["initial_states"]:
            data, receipt = _batch(store, {**recipe, "field_source": actual_field}, particle, field_key, implementation,
                                   cancellation if cancelled else None, claims)
            results.append(data)
            batches.append(receipt)
            # R means still-unwritten growth, not bytes already deducted from real free space.
            written += receipt["new_payload_bytes"]
            store.reservation_written(reservation, max(0, budget - written))
        merged = _merged(results)
        work = run_work
        write_particle_data(work, merged, metadata={"frame_id": recipe["frame_id"], "clock": recipe["clock"]})
        _write_json(work / "provenance.json", {"schema_version": 1, "implementation": implementation,
                    "author_sha256": file_sha256(work / "author.toml"), "execution_owner": "reference_tracing",
                    "repository_source": {"sha": source_revision, "status": "declared" if source_revision else "unavailable",
                                          "basis": "explicit_run_provenance"},
                    "field": {"task_key": field_key, "asset_id": field_id, "reused": field_reused},
                    "batches": batches})
        _write_json(work / "summary.json", summarize_particle_data(read_particle_data(work)))
        written += sum(p.stat().st_size for p in work.iterdir() if p.is_file())
        store.reservation_written(reservation, max(0, budget - written))
        provenance = [field_id] + [b["asset_id"] for b in batches if b["asset_id"]]
        store.publish_run(work, run_id=run_id, execution_status=merged.execution_status, provenance_assets=provenance)


def inspect_results(run_id: str, *, artifact_root: str | Path) -> dict[str, Any]:
    """Reopen a managed run, validate its files, then recompute complete-cohort statistics."""
    store = ArtifactStore(artifact_root)
    state = store.run_status(run_id)
    if state["publication_status"] != "ready":
        return {"run_state": state, "summary": None}
    path = store.inspect_run(run_id)
    data = read_particle_data(path)
    summary = summarize_particle_data(data)
    recorded = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    if summary != recorded:
        raise ValueError("recorded statistics differ from published particle data")
    return {"run_path": str(path), "run_state": state, "summary": summary,
            "provenance": json.loads((path / "provenance.json").read_text(encoding="utf-8"))}
