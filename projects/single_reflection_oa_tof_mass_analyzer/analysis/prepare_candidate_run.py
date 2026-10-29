"""Freeze an isolated oa-TOF candidate run and compile its ordered workflow."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
from common.contracts.artifact_naming import validate_run_id, validate_task_id
from common.contracts.machine_contracts import load_json, sha256, validate_schema
from common.simion.process_observation import run_observed_process
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
    freeze_candidate_source_closure,
    frozen_source_path,
)


WORKFLOW_PATH = PROJECT_ROOT / "config" / "candidate_workflow.json"
FORMAL_BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
FORMAL_RESOLVED_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"
FORMAL_NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
RUNTIME_PATH = PROJECT_ROOT / "config" / "candidate_runtime.json"


def plan_pa_producer_handoffs(pairs: list[tuple[Path, Path]], *, expected_cache_keys: set[str], artifact_root: Path) -> dict:
    """Read explicit small owner inputs before admission; never inspect a PA."""
    from common.contracts.write_run_manifest import file_record
    from common.simion.pa_family_cache import load_pa_family_cache_transaction

    artifact_root = artifact_root.resolve(strict=True)
    cache = artifact_root / "common/simion/pa_family_cache"
    sources, records, protected = {}, {}, set()
    for transaction_path, result_path in pairs:
        transaction_path, result_path = transaction_path.resolve(strict=True), result_path.resolve(strict=True)
        key = transaction_path.parent.name
        if key not in expected_cache_keys or transaction_path != cache / ".transactions" / key / "transaction.json":
            raise ValueError("PA producer handoff key is absent from the compiled component plans")
        source = dict(transaction_path=str(transaction_path), owner_result_path=str(result_path))
        if key in sources:
            if sources[key] != source:
                raise ValueError("PA producer handoff has conflicting inputs for the same cache key")
            continue
        transaction = load_pa_family_cache_transaction(cache, key)
        predecessor = Path(transaction["producer"]["run_config_path"]).resolve().parent
        result = load_json(result_path)
        if (transaction["status"] not in {"building", "prepared"}
                or result.get("schema_version") != 1 or result.get("role") != "run_artifact_workflow_result"
                or result.get("stage") != "complete" or not isinstance(result.get("stopped_payload_receipt"), dict)
                or Path(result.get("run_directory", "")).resolve() != predecessor
                or any(result.get(flag) is not True for flag in ("terminal_published", "capacity_finalized", "lease_released"))):
            raise ValueError("PA producer handoff requires its completed public owner result and stopped payload receipt")
        protected.add(predecessor)
        for value in (transaction.get("verification") or {}).values():
            if not isinstance(value, str):
                continue
            try:
                parts = Path(value).resolve().relative_to(artifact_root).parts
            except (ValueError, OSError):
                continue
            if len(parts) >= 4 and parts[0] == "projects" and parts[2] == "runs":
                protected.add(artifact_root.joinpath(*parts[:4]))
        for path in (transaction_path, result_path, predecessor / "run_manifest.json"):
            records[str(path)] = file_record(path)
            if records[str(path)]["exists"] is not True:
                raise ValueError("PA producer handoff requires its predecessor manifest")
        sources[key] = source
    return dict(sources=list(sources.values()), source_records=list(records.values()),
                protected_paths=[str(path) for path in sorted(protected)], declared_cache_keys=sorted(expected_cache_keys))


def load_pa_producer_handoffs(path: Path, run_root: Path, *, expected_cache_keys: set[str], capacity_session: dict) -> dict:
    """Validate frozen owner results and their exact public-receipt projections."""
    from common.contracts.verify_run_manifest import verify_record

    run_root = run_root.resolve()
    if not path.resolve().is_relative_to(run_root / "inputs"):
        raise ValueError("PA producer handoff map must be a frozen input of this run")
    document = load_json(path)
    if (document.get("schema_version") != 1 or document.get("role") != "oatof_pa_producer_handoffs"
            or document.get("run_id") != run_root.name or not isinstance(document.get("entries"), dict)
            or not document["entries"] or not isinstance(document.get("declared_cache_keys"), list)
            or document["declared_cache_keys"] != sorted(set(document["declared_cache_keys"]))
            or not set(document["entries"]) <= set(document["declared_cache_keys"])
            or not expected_cache_keys <= set(document["declared_cache_keys"])):
        raise ValueError("PA producer handoff map identity differs")
    result = {}
    for key, entry in document["entries"].items():
        records = {name: entry[name] for name in ("request", "owner_result")}
        for label, record in records.items():
            if not Path(record["path"]).resolve().is_relative_to(run_root / "inputs"):
                raise ValueError("PA producer handoff evidence must remain in frozen inputs")
            verify_record(label, record)
        request = load_json(Path(records["request"]["path"]))
        if (request.get("capacity_lease_id") != capacity_session["lease_id"]
                or request.get("capacity_lease_owner") != capacity_session["owner"]):
            raise ValueError("PA producer handoff must use the current workflow capacity session")
        evidence = {}
        for name in ("transaction_record", "predecessor_manifest", "stopped_receipt"):
            record = request[name]
            if not Path(record["path"]).resolve().is_relative_to(run_root / "inputs"):
                raise ValueError("PA producer handoff evidence must remain in frozen inputs")
            verify_record(name, record)
            evidence[name] = load_json(Path(record["path"]))
        predecessor = Path(evidence["transaction_record"]["producer"]["run_config_path"]).resolve().parent
        owner_result = load_json(Path(records["owner_result"]["path"]))
        if (owner_result.get("schema_version") != 1 or owner_result.get("role") != "run_artifact_workflow_result"
                or owner_result.get("stage") != "complete"
                or any(owner_result.get(flag) is not True for flag in ("terminal_published", "capacity_finalized", "lease_released"))
                or Path(owner_result.get("run_directory", "")).resolve() != predecessor
                or owner_result.get("stopped_payload_receipt") != evidence["stopped_receipt"]
                or evidence["transaction_record"]["cache_key"] != key):
            raise ValueError("PA stopped receipt is not the exact projection of the frozen public owner result")
        if str(predecessor) not in capacity_session["protected_paths"]:
            raise ValueError("PA predecessor must be protected by the current workflow session")
        build_complete = False
        original_completion = None
        if proof := entry.get("build_completion"):
            if not Path(proof["path"]).resolve().is_relative_to(run_root / "inputs"):
                raise ValueError("PA producer completion must remain in frozen inputs")
            verify_record("producer build completion", proof)
            manifest_records = [*evidence["predecessor_manifest"].get("outputs", []),
                                *evidence["predecessor_manifest"].get("inputs", {}).values()]
            bound = [row for row in manifest_records if Path(row["path"]).resolve() == Path(proof["source_path"]).resolve()]
            if not bound or any(any(row.get(name) != proof[name] for name in ("bytes", "sha256")) for row in bound):
                raise ValueError("PA producer build completion is not bound by the predecessor manifest")
            build = load_json(Path(proof["path"]))
            components = [row for row in build.get("components", []) if row["cache_key"] == key]
            if (build.get("role") != "oatof_component_build_completion" or build.get("schema_version") != 1
                    or build.get("run_id") != predecessor.name or len(components) != 1):
                raise ValueError("PA producer build completion component identity differs")
            component = components[0]
            transaction = evidence["transaction_record"]
            original_completion = proof
            if reference := component.get("response_build_completion"):
                original_completion = entry["original_build_completion"]
                if (not Path(reference["path"]).resolve().is_relative_to(predecessor / "inputs")
                        or Path(original_completion["source_path"]).resolve() != Path(reference["path"]).resolve()
                        or not Path(original_completion["path"]).resolve().is_relative_to(run_root / "inputs")
                        or any(original_completion[name] != reference[name] for name in ("bytes", "sha256"))):
                    raise ValueError("PA original build reference differs from its frozen source")
                bound = [row for row in manifest_records if Path(row["path"]).resolve() == Path(reference["path"]).resolve()]
                if not bound or any(any(row.get(name) != reference[name] for name in ("bytes", "sha256")) for row in bound):
                    raise ValueError("PA original build reference is not bound by the predecessor manifest")
                verify_record("original PA build completion", original_completion)
                build = load_json(Path(original_completion["path"]))
                validate_run_id(build["run_id"])
                components = [row for row in build.get("components", []) if row["cache_key"] == key]
                if (build.get("schema_version") != 1 or build.get("role") != "oatof_component_build_completion"
                        or len(components) != 1 or components[0].get("response_build_completion")):
                    raise ValueError("PA original build proof must be a flat native completion, not a reference chain")
                component = components[0]
            if (component["response_ids"] != transaction["identity"]["basis_namespace"]["electrode_ids"]
                    or component["role"] != transaction["identity"]["geometry"]["role"]):
                raise ValueError("PA producer build completion response namespace differs")
            ids = component["response_build_operation_ids"]
            operations = build["operations"]
            by_id = {row["operation_id"]: row for row in operations}
            if len(by_id) != len(operations) or len(set(ids)) != len(ids):
                raise ValueError("PA producer build operation IDs are ambiguous")
            build_complete = bool(ids)
            for operation_id in ids:
                operation = by_id[operation_id]
                native, worker = operation["observation"], operation["managed_process_completion"]
                build_complete &= (native.get("exit_confirmed") is True and native.get("returncode") == 0
                    and worker.get("schema_version") == 1 and worker.get("role") == "repository_managed_python_completion"
                    and all(type(worker.get(name)) is int and worker[name] > 0 for name in (
                        "worker_process_id", "worker_started_at_utc_ticks", "launcher_process_id"))
                    and worker.get("exit_code") == 0 and all(worker.get(flag) is True for flag in (
                        "ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained")))
            if transaction["status"] == "prepared":
                verification = transaction["verification"]
                inherited_verification = False
                prior = transaction.get("producer_handoff", {}).get("request", {}).get("transaction_record")
                if prior:
                    bound = [row for row in manifest_records if Path(row["path"]).resolve() == Path(prior["path"]).resolve()]
                    if (Path(prior["path"]).resolve().is_relative_to(predecessor / "inputs") and bound
                            and all(all(row.get(name) == prior[name] for name in ("bytes", "sha256")) for row in bound)):
                        verify_record("prior prepared transaction", prior)
                        previous = load_json(Path(prior["path"]))
                        inherited_verification = (previous.get("status") == "prepared" and previous.get("cache_key") == key
                            and previous.get("identity") == transaction["identity"] and previous.get("verification") == verification)
                # A later owner may have retried only publication. Its already
                # frozen prepared snapshot binds the unchanged original proof;
                # the public handoff still revalidates the actual script/log SHA.
                if not inherited_verification:
                    for path_key, hash_key in (("verifier_path", "verifier_sha256"), ("verification_output_path", "verification_output_sha256")):
                        matches = [row for row in manifest_records if Path(row["path"]).resolve() == Path(verification[path_key]).resolve()]
                        if not matches or any(row["sha256"] != verification[hash_key] for row in matches):
                            raise ValueError("Prepared PA verification is not bound by the predecessor manifest")
                        for record in matches:
                            verify_record("prepared PA verification", record)
        if key in expected_cache_keys:
            result[key] = dict(request_path=str(records["request"]["path"]), response_build_complete=build_complete,
                has_sealed_inventory=bool(evidence["transaction_record"]["files"]),
                response_build_completion=original_completion if build_complete else None)
    return result


def freeze_pa_producer_handoffs(run_root: Path, handoff_plan: dict, *, expected_cache_keys: set[str], capacity_session: dict) -> dict:
    """Freeze explicit transaction/result pairs; retain raw Result provenance."""
    from common.contracts.frozen_inputs import freeze_file
    from common.contracts.recorded_file_removal import write_json_atomic
    from common.contracts.verify_run_manifest import verify_record
    from common.contracts.write_run_manifest import file_record
    from common.simion.pa_family_cache import load_pa_family_cache_transaction

    run_root = run_root.resolve()
    if handoff_plan["declared_cache_keys"] != sorted(expected_cache_keys):
        raise ValueError("PA producer handoff allowed keys differ from the compiled component plans")
    for record in handoff_plan["source_records"]:
        verify_record("planned PA producer handoff input", record)
    sources = handoff_plan["sources"]
    if (capacity_session.get("role") != "artifact_workflow_capacity_session" or capacity_session.get("status") != "active"
            or str(run_root) not in capacity_session["protected_paths"] or not sources):
        raise ValueError("PA handoff freezing requires the admitted run and its current capacity session")
    destination = run_root / "inputs/pa_producer_handoffs"
    destination.mkdir()
    entries, frozen_records = {}, []
    cache = Path(capacity_session["artifact_root"]).resolve() / "common/simion/pa_family_cache"
    for source in sources:
        if set(source) != {"transaction_path", "owner_result_path"}:
            raise ValueError("PA handoff requires explicit transaction and public owner-result paths")
        transaction_path = Path(source["transaction_path"]).resolve(strict=True)
        key = transaction_path.parent.name
        if (key not in expected_cache_keys or key in entries
                or transaction_path != cache / ".transactions" / key / "transaction.json"):
            raise ValueError("PA handoff transaction is not a unique selected governed component")
        transaction = load_pa_family_cache_transaction(cache, key)
        predecessor = Path(transaction["producer"]["run_config_path"]).resolve().parent
        folder = destination / key
        folder.mkdir()
        owner_result = freeze_file(Path(source["owner_result_path"]), folder / "owner_result.json")
        # This is a deterministic projection, never a second stopped-writer
        # authority: every consumer compares it with the retained raw Result.
        stopped_path = folder / "stopped_receipt.json"
        write_json_atomic(stopped_path, load_json(Path(owner_result["path"]))["stopped_payload_receipt"])
        request = dict(schema_version=1,
            transaction_record=freeze_file(transaction_path, folder / "transaction.json"),
            predecessor_manifest=freeze_file(predecessor / "run_manifest.json", folder / "predecessor_manifest.json"),
            stopped_receipt=file_record(stopped_path), capacity_lease_id=capacity_session["lease_id"],
            capacity_lease_owner=capacity_session["owner"])
        planned = {Path(record["path"]).resolve(): record for record in handoff_plan["source_records"]}
        for record in (owner_result, request["transaction_record"], request["predecessor_manifest"]):
            original = planned[Path(record["source_path"]).resolve()]
            if any(record[name] != original[name] for name in ("bytes", "sha256")):
                raise ValueError(f"Frozen PA handoff source differs from its planned byte identity: {record['source_path']}")
        request_path = folder / "request.json"
        write_json_atomic(request_path, request)
        entries[key] = dict(request=file_record(request_path), owner_result=owner_result)
        frozen_records.extend([owner_result, request["transaction_record"], request["predecessor_manifest"],
                               request["stopped_receipt"], entries[key]["request"]])
        manifest = load_json(Path(request["predecessor_manifest"]["path"]))
        completions = []
        for record in manifest.get("outputs", []):
            candidate = Path(record["path"])
            if candidate.name not in {"build_completion.json", "simion_build_completion.json"}:
                continue
            verify_record("producer build completion", record)
            build = load_json(candidate)
            if build.get("run_id") != predecessor.name or build.get("role") != "oatof_component_build_completion":
                continue
            if any(row.get("cache_key") == key and (row.get("response_build_operation_ids") or row.get("response_build_completion"))
                   for row in build.get("components", [])):
                completions.append(candidate)
        if len(completions) > 1:
            raise ValueError("PA producer has ambiguous completed response builds")
        if completions:
            entries[key]["build_completion"] = freeze_file(completions[0], folder / "build_completion.json")
            frozen_records.append(entries[key]["build_completion"])
            component = next(row for row in load_json(completions[0])["components"] if row["cache_key"] == key)
            if reference := component.get("response_build_completion"):
                verify_record("original PA build completion", reference)
                entries[key]["original_build_completion"] = freeze_file(Path(reference["path"]), folder / "original_build_completion.json")
                frozen_records.append(entries[key]["original_build_completion"])
    path = destination / "handoffs.json"
    write_json_atomic(path, dict(schema_version=1, role="oatof_pa_producer_handoffs", run_id=run_root.name,
                                declared_cache_keys=sorted(expected_cache_keys), entries=entries))
    load_pa_producer_handoffs(path, run_root, expected_cache_keys=expected_cache_keys, capacity_session=capacity_session)
    record = file_record(path)
    return {**record, "frozen_input_records": [*frozen_records, record]}


def validate_artifact_capacity(runtime: dict) -> dict:
    """Read the explicit execution reservation, independent of field identity."""
    capacity = runtime.get("artifact_capacity")
    if not isinstance(capacity, dict):
        raise ValueError("candidate runtime requires explicit artifact_capacity")
    for key in ("comsol_bytes", "cad_bytes", "evidence_bytes"):
        if type(capacity.get(key)) is not int or capacity[key] <= 0:
            raise ValueError(f"artifact_capacity.{key} must be explicit positive bytes")
    if not isinstance(capacity.get("basis"), dict) or not capacity["basis"].get("policy"):
        raise ValueError("artifact_capacity requires its measured source and engineering policy")
    return capacity


def validate_workflow(workflow: dict) -> None:
    if workflow.get("role") != "oa_tof_candidate_workflow_contract":
        raise ValueError("unsupported candidate workflow contract")
    stages = workflow.get("stages", [])
    identifiers = [stage["stage_id"] for stage in stages]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate workflow has duplicate stage identifiers")
    seen: set[str] = set()
    for stage in stages:
        missing = set(stage.get("depends_on", [])) - seen
        if missing:
            raise ValueError(f"stage {stage['stage_id']} has forward or missing dependencies: {sorted(missing)}")
        seen.add(stage["stage_id"])
        if not stage.get("failure_stops_workflow"):
            raise ValueError(f"candidate stage must fail closed: {stage['stage_id']}")
    policy = workflow.get("formal_policy", {})
    if not policy.get("formal_is_read_only_during_candidate_run") or policy.get("automatic_promotion"):
        raise ValueError("candidate workflow must keep formal read-only and disable automatic promotion")
    if not workflow.get("promotion_is_not_a_workflow_stage") or "promotion" in seen:
        raise ValueError("promotion must be a separate approved run")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _provenance_path(record: dict, base: Path, label: str) -> Path:
    path = Path(record.get("path", ""))
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    expected = record.get("sha256", "")
    if not path.is_file() or not expected or sha256(path).lower() != expected.lower():
        raise ValueError(f"candidate {label} provenance is missing or changed")
    return path


def _candidate_sources(candidate_baseline: Path, candidate_resolved: Path, candidate_diff: Path) -> dict[str, Path]:
    baseline = candidate_baseline.resolve()
    resolved = candidate_resolved.resolve()
    diff = candidate_diff.resolve()
    report = load_json(diff)
    if report.get("role") != "oa_tof_candidate_contract_diff":
        raise ValueError("candidate diff has an unsupported role")
    provenance = report.get("provenance", {})
    proposal = _provenance_path(provenance.get("proposal", {}), diff.parent, "proposal")
    request = _provenance_path(provenance.get("request", {}), diff.parent, "request")
    proposal_contract = load_json(proposal)
    request_contract = load_json(request)
    numerics = resolved.parent / "candidate_solver_numerics.json"
    if not numerics.is_file():
        raise ValueError("candidate solver numerics contract is missing")
    if resolved_source := load_json(resolved):
        inputs = resolved_source.get("inputs", {})
        if inputs.get("solver_numerics_sha256", "").lower() != sha256(numerics).lower():
            raise ValueError("candidate solver numerics and resolved contract hashes do not match")
    validate_schema(proposal_contract, "candidate_proposal.schema.json")
    validate_schema(request_contract, "design_request.schema.json")
    proposal_request = proposal_contract["request"]
    proposal_request_path = Path(proposal_request["path"])
    if not proposal_request_path.is_absolute():
        proposal_request_path = proposal.parent / proposal_request_path
    if proposal_request_path.resolve() != request or proposal_request["sha256"].lower() != sha256(request).lower():
        raise ValueError("candidate proposal and request provenance do not match")
    if (
        report.get("candidate_id") != proposal_contract["candidate_id"]
        or report.get("request_id") != request_contract["request_id"]
    ):
        raise ValueError("candidate diff identity does not match its proposal/request")
    return {
        "candidate_baseline.json": baseline,
        "candidate_resolved_geometry.json": resolved,
        "candidate_solver_numerics.json": numerics,
        "candidate_diff.json": diff,
        "candidate_proposal.json": proposal,
        "design_request.json": request,
    }


def _registered_template_source_path(value: object, label: str, record_name: str) -> Path:
    """Resolve one registered template source path without accepting a missing spelling."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"candidate SIMION template {record_name} path is missing: {label}")
    try:
        return Path(value).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(
            f"candidate SIMION template {record_name} path is missing or unresolvable: {label}"
        ) from error


def _registered_candidate_template(template_run: Path, artifact_project_root: Path) -> dict[str, Path]:
    """Return validated sources from one successful non-Formal layout registration."""
    run_root = template_run.resolve()
    runs_root = (artifact_project_root / "runs").resolve()
    if not _inside(run_root, runs_root) or run_root.parent != runs_root:
        raise ValueError("candidate SIMION template must be a direct artifacts/runs registration run")
    paths = {
        "run_config": run_root / "run_config.json",
        "summary": run_root / "summary.json",
        "manifest": run_root / "run_manifest.json",
        "runtime_report": run_root / "simion_layout_runtime_report.txt",
    }
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("candidate SIMION template registration evidence is incomplete")
    config = load_json(paths["run_config"])
    summary = load_json(paths["summary"])
    manifest = load_json(paths["manifest"])
    if (
        config.get("role") != "oa_tof_simion_candidate_layout_template_build"
        or config.get("project") != "single_reflection_oa_tof_mass_analyzer"
        or config.get("mode") != "candidate_layout_template_build"
        or config.get("run_id") != run_root.name
        or config.get("template_role") != "oa_tof_candidate_simion_layout_template"
    ):
        raise ValueError("candidate SIMION template registration has an unsupported identity")
    if (
        summary.get("role") != "oa_tof_simion_candidate_layout_template_build_summary"
        or summary.get("status") != "success"
        or not summary.get("runtime_structure_verified")
        or summary.get("particle_fly_executed")
        or summary.get("formal_modified")
        or manifest.get("status") != "success"
        or manifest.get("run_id") != run_root.name
    ):
        raise ValueError("candidate SIMION template registration is not a successful structure-only run")
    report = paths["runtime_report"].read_text(encoding="utf-8", errors="replace")
    if not all(token in report for token in ("STATUS=PASS", "INSTANCE_COUNT=4", "TEMPLATE_STRUCTURE_ONLY=true")):
        raise ValueError("candidate SIMION template runtime evidence is incomplete")
    inputs = config.get("inputs", {})
    hashes = config.get("input_sha256", {})
    manifest_inputs = manifest.get("inputs", {})
    result = {"registration_run": run_root, "registration_manifest": paths["manifest"]}
    for label, suffix in (("source_iob", ".iob"), ("source_con", ".con")):
        path = _registered_template_source_path(inputs.get(label), label, "config")
        expected = str(hashes.get(label, ""))
        recorded = manifest_inputs.get(label, {})
        if not isinstance(recorded, dict):
            raise ValueError(f"candidate SIMION template manifest record is invalid: {label}")
        recorded_path = _registered_template_source_path(recorded.get("path"), label, "manifest")
        if path != recorded_path:
            raise ValueError(f"candidate SIMION template config and manifest paths differ: {label}")
        if path.suffix.lower() != suffix:
            raise ValueError(f"candidate SIMION template source suffix is invalid: {label}")
        if not expected:
            raise ValueError(f"candidate SIMION template config SHA-256 is missing: {label}")
        actual = sha256(path).lower()
        if actual != expected.lower():
            raise ValueError(f"candidate SIMION template source SHA-256 changed: {label}")
        if str(recorded.get("sha256", "")).lower() != expected.lower():
            raise ValueError(f"candidate SIMION template manifest SHA-256 differs: {label}")
        if any(segment in path.as_posix().lower().split("/") for segment in ("formal", "archive", "history")):
            raise ValueError("candidate SIMION template registration references a prohibited source path")
        result[label] = path
    if result["source_iob"].with_suffix(".con").name != result["source_con"].name:
        raise ValueError("candidate SIMION template registration bundle basenames do not match")
    return result


def prepare_candidate_run(
    candidate_baseline: Path,
    candidate_resolved: Path,
    candidate_diff: Path,
    run_id: str,
    artifact_project_root: Path | None = None,
    particle_source_seed: int | None = None,
    simion_template_run: Path | None = None,
    campaign_table: Path | None = None,
    campaign_selection: Path | None = None,
) -> dict:
    run_identity = validate_run_id(run_id)
    workflow = load_json(WORKFLOW_PATH)
    validate_workflow(workflow)
    artifact_project_root = (artifact_project_root or WORKSPACE_ROOT / "artifacts" / "projects" / "single_reflection_oa_tof_mass_analyzer").resolve()
    formal_root = artifact_project_root / "formal"
    run_root = artifact_project_root / "runs" / run_id
    task_id = f"{run_identity['stamp']}__cross__candidate-plan-{sha256(candidate_resolved.resolve())[:8].lower()}"
    validate_task_id(task_id)
    planning_root = artifact_project_root / "scratch" / task_id
    if run_root.exists():
        raise FileExistsError(f"candidate run already exists; overwrite is forbidden: {run_root}")
    if planning_root.exists():
        raise FileExistsError(f"candidate planning task already exists; overwrite is forbidden: {planning_root}")

    if not isinstance(particle_source_seed, int):
        raise ValueError("candidate run requires an explicit integer particle source seed")
    if (campaign_table is None) != (campaign_selection is None):
        raise ValueError(
            "campaign table and selection must be supplied together"
        )
    primary_sources = [candidate_baseline.resolve(), candidate_resolved.resolve(), candidate_diff.resolve()]
    if any(not path.is_file() for path in primary_sources):
        raise FileNotFoundError("candidate baseline, resolved contract, and diff must all exist")
    sources = _candidate_sources(candidate_baseline, candidate_resolved, candidate_diff)
    artifact_capacity = validate_artifact_capacity(load_json(RUNTIME_PATH))
    sources["candidate_runtime.json"] = RUNTIME_PATH
    if any(_inside(path, formal_root) for path in sources.values()):
        raise ValueError("candidate inputs must not be sourced from formal artifacts")
    if (
        sources["candidate_baseline.json"] == FORMAL_BASELINE_PATH.resolve()
        or sources["candidate_resolved_geometry.json"] == FORMAL_RESOLVED_PATH.resolve()
        or sources["candidate_solver_numerics.json"] == FORMAL_NUMERICS_PATH.resolve()
    ):
        raise ValueError("candidate run requires isolated candidate contracts, not the formal project contracts")
    template_registration = (
        _registered_candidate_template(simion_template_run, artifact_project_root)
        if simion_template_run is not None
        else None
    )
    resolved_source = load_json(sources["candidate_resolved_geometry.json"])
    if resolved_source.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("candidate resolved contract has an unsupported role")
    if (
        resolved_source.get("inputs", {}).get("baseline_sha256", "").lower()
        != sha256(sources["candidate_baseline.json"]).lower()
    ):
        raise ValueError("candidate baseline and resolved contract hashes do not match")

    planning_root.mkdir(parents=True)
    inputs_dir = planning_root / "inputs"
    inputs_dir.mkdir()
    source_closure = freeze_candidate_source_closure(inputs_dir / "code", artifact_project_root)
    frozen_code_root = Path(source_closure["code_root"])
    frozen = {}
    for name, source in sources.items():
        target = inputs_dir / name
        shutil.copy2(source, target)
        frozen[name] = target
    campaign_binding = None
    if campaign_table is not None and campaign_selection is not None:
        table_source = campaign_table.resolve(strict=True)
        selection_source = campaign_selection.resolve(strict=True)
        selection = load_json(selection_source)
        if (
            selection.get("role") != "oatof_campaign_selection"
            or selection.get("candidate_run_id") != run_id
            or selection.get("particle_source_seed") != particle_source_seed
            or selection.get("campaign_sha256") != sha256(table_source)
        ):
            raise ValueError("campaign selection does not bind this Candidate run")
        request_record = selection.get("request", {})
        proposal_record = selection.get("proposal", {})
        if (
            request_record.get("sha256") != sha256(Path(request_record.get("path", "")))
            or proposal_record.get("sha256") != sha256(Path(proposal_record.get("path", "")))
        ):
            raise ValueError("campaign selection request or proposal binding changed")
        table_target = inputs_dir / "experiment_campaign.json"
        selection_target = inputs_dir / "campaign_selection.json"
        shutil.copy2(table_source, table_target)
        shutil.copy2(selection_source, selection_target)
        frozen["experiment_campaign"] = table_target
        frozen["campaign_selection"] = selection_target
        campaign_binding = {
            "campaign_id": selection["campaign_id"],
            "campaign_run_id": selection["campaign_run_id"],
            "experiment_id": selection["experiment_id"],
            "campaign_sha256": sha256(table_target),
            "selection_sha256": sha256(selection_target),
            "candidate_run_id": run_id,
            "particle_source_seed": particle_source_seed,
        }
    frozen_template = None
    if template_registration is not None:
        template_dir = inputs_dir / "simion_template"
        template_dir.mkdir()
        frozen_template = {}
        for key, target_name in (("source_iob", "layout.iob"), ("source_con", "layout.con")):
            source = template_registration[key]
            target = template_dir / target_name
            shutil.copy2(source, target)
            frozen[f"candidate_simion_template_{key}"] = target
            frozen_template[key.removeprefix("source_")] = {"path": str(target), "sha256": sha256(target)}
        manifest_target = template_dir / "registration_manifest.json"
        shutil.copy2(template_registration["registration_manifest"], manifest_target)
        frozen["candidate_simion_template_registration_manifest"] = manifest_target

    prepared_dir = inputs_dir / "prepared_consumers"
    compiler_logs = planning_root / "logs"
    compiler_logs.mkdir(exist_ok=True)
    stdout, stderr = compiler_logs / "prepare_consumers.stdout.log", compiler_logs / "prepare_consumers.stderr.log"
    process, _ = run_observed_process([
        source_closure["runtime"]["python_executable"], "-B", "-m",
        "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers",
        "--contract", str(frozen["candidate_resolved_geometry.json"]), "--output-dir", str(prepared_dir),
        "--particle-source-seed", str(particle_source_seed),
    ], cwd=frozen_code_root, stdout=stdout, stderr=stderr,
        environment={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        warning_seconds=30)
    if process.returncode != 0:
        # Keep the actual final diagnostic after a temporary planning tree exits,
        # with the same 4 KiB bound used for public failure diagnostics.
        with stderr.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 4096))
            detail = stream.read().decode("utf-8", errors="replace")
        raise ValueError(
            f"frozen Candidate consumer compiler failed; exit_code={process.returncode}; "
            f"stderr={stderr}; stderr_tail=\n{detail}"
        )
    generated = {"resolved_lua": prepared_dir / "simion/oatof_resolved.lua",
                 "program": prepared_dir / "simion/oatof_ideal_grounded.lua",
                 "fly2": prepared_dir / "simion/oatof_ideal_grounded.fly2"}
    frozen.update({f"candidate_simion_{key}": path for key, path in generated.items()})
    resolved_contract = load_json(frozen["candidate_resolved_geometry.json"])
    source = resolved_contract["particle_source"]
    target = resolved_contract["validation_target"]
    comsol_model = run_root / "comsol" / "single_reflection_oa_tof_mass_analyzer__candidate.mph"
    candidate_ion = inputs_dir / "oatof_candidate_N100.ion"
    report_dir = run_root / "logs"
    workflow_plan = {
        "schema_version": 1,
        "role": "oa_tof_candidate_run_plan",
        "status": "EXECUTION_READY" if frozen_template is not None else "NEEDS_RUNTIME_INPUTS",
        "run_id": run_id,
        "run_instance": {
            "particle_source_seed": particle_source_seed,
            "particle_count": 100,
        },
        "planning_root": str(planning_root),
        "run_root": str(run_root),
        "formal_root": {"path": str(formal_root), "mutation_allowed": False},
        "formal_baseline_sha256_at_planning": sha256(FORMAL_BASELINE_PATH),
        "formal_baseline_path_at_planning": str(FORMAL_BASELINE_PATH.resolve()),
        "candidate_inputs": {key: {"path": str(path), "sha256": sha256(path)} for key, path in frozen.items()},
        **({"campaign_binding": campaign_binding} if campaign_binding is not None else {}),
        "execution_source_closure": source_closure,
        "artifact_capacity": artifact_capacity,
        "stages": [
            {
                "stage_id": "static_inputs",
                "status": "prepared_except_particle_table",
                "prepared_outputs": [str(path) for path in generated.values()],
                "pending_output": str(candidate_ion),
                "entrypoint": frozen_source_path(
                    source_closure,
                    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1",
                ),
                "arguments": {
                    "N": 100,
                    "MassAmu": target["mass_amu"],
                    "Charge": 1,
                    "EnergyMeanEv": target["initial_energy_mean_ev"],
                    "EnergyStdEv": target["initial_energy_sigma_ev"],
                    "HalfWidthXmm": source["size_x_mm"] / 2,
                    "HalfWidthYmm": source["size_y_mm"] / 2,
                    "HalfWidthZmm": source["size_z_mm"] / 2,
                    "CenterXmm": source["center_x_mm"],
                    "CenterYmm": source["center_y_mm"],
                    "CenterZmm": source["center_z_mm"],
                    "Seed": particle_source_seed,
                    "Output": str(candidate_ion),
                },
            },
            {
                "stage_id": "comsol_candidate",
                "status": "not_run",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "model_path": str(comsol_model),
                "report_path": str(report_dir / "comsol_build.txt"),
                "entrypoint": frozen_source_path(source_closure, "common/comsol/run_comsol_r2025b.ps1"),
                "task_script": str(frozen_code_root / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m"),
                "environment": {
                    "OATOF_CANDIDATE_CONTRACT_PATH": str(frozen["candidate_resolved_geometry.json"]),
                    "OATOF_CANDIDATE_MODEL_PATH": str(comsol_model),
                    "OATOF_CANDIDATE_RUN_CONFIG_PATH": str(run_root / "run_config.json"),
                    "OATOF_RUNTIME_DIR": str(run_root / "comsol"),
                },
            },
            {
                "stage_id": "simion_candidate",
                "status": "ready" if frozen_template is not None else "blocked_requires_explicit_nonformal_template",
                "contract_path": str(frozen["candidate_resolved_geometry.json"]),
                "baseline_path": str(frozen["candidate_baseline.json"]),
                "text_dir": str(prepared_dir / "simion"),
                "output_dir": str(run_root / "simion"),
                "required_input": "runs/<run_id>/inputs/simion_template/ with role oa_tof_candidate_simion_layout_template and SHA-256 provenance",
                "formal_asset_read_allowed": False,
                **({
                    "template_input": {
                        "role": "oa_tof_candidate_simion_layout_template",
                        "files": frozen_template,
                        "registration_run_id": template_registration["registration_run"].name,
                        "registration_manifest": {
                            "path": str(manifest_target),
                            "sha256": sha256(manifest_target),
                        },
                    }
                } if frozen_template is not None and template_registration is not None else {}),
            },
            {
                "stage_id": "cad_candidate",
                "status": "blocked_until_comsol_success",
                "model_path": str(comsol_model),
                "output_dir": str(run_root / "cad"),
                "entrypoint": frozen_source_path(source_closure, "common/comsol/run_comsol_r2025b.ps1"),
                "task_script": str(frozen_code_root / "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_cad_sync.m"),
            },
            {
                "stage_id": "structural_acceptance",
                "status": "ready" if frozen_template is not None else "blocked",
                "output_dir": str(run_root / "results"),
            },
        ],
        "promotion": {
            "included": False,
            "automatic": False,
            "safe_to_promote": False,
            "required_separate_decision": True,
        },
        "limitations": [
            "This preparation step does not launch COMSOL, SIMION, or SolidWorks.",
            "Runtime stages must update summary and manifest evidence before acceptance.",
            "Acceptance never mutates baseline or formal assets; promotion is a separate approved workflow.",
        ],
    }
    stage_contracts = {stage["stage_id"]: stage for stage in workflow["stages"]}
    for stage in workflow_plan["stages"]:
        contract_stage = stage_contracts[stage["stage_id"]]
        stage["depends_on"] = contract_stage["depends_on"]
        stage["failure_stops_workflow"] = contract_stage["failure_stops_workflow"]
        for key in ("acceptance_scope", "performance_claim_allowed"):
            if key in contract_stage:
                stage[key] = contract_stage[key]
    (planning_root / "candidate_workflow_plan.json").write_text(
        json.dumps(workflow_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run_config = {
        "schema_version": 1,
        "role": "oa_tof_candidate_run_config",
        "run_id": run_id,
        "project": "single_reflection_oa_tof_mass_analyzer",
        "mode": "design_candidate",
        "artifact_capacity": artifact_capacity,
        "run_instance": {
            "particle_source_seed": particle_source_seed,
            "particle_count": 100,
        },
        "project_root": str(PROJECT_ROOT),
        "inputs": {key: value["path"] for key, value in workflow_plan["candidate_inputs"].items()},
        "input_sha256": {key: value["sha256"] for key, value in workflow_plan["candidate_inputs"].items()},
        **({"campaign_binding": campaign_binding} if campaign_binding is not None else {}),
        "formal_gate_passed": False,
        "promotion_authorized": False,
    }
    (planning_root / "run_config.template.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return workflow_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-baseline", required=True, type=Path)
    parser.add_argument("--candidate-resolved", required=True, type=Path)
    parser.add_argument("--candidate-diff", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--particle-source-seed", required=True, type=int)
    parser.add_argument("--simion-template-run", type=Path)
    args = parser.parse_args()
    result = prepare_candidate_run(args.candidate_baseline, args.candidate_resolved, args.candidate_diff, args.run_id, particle_source_seed=args.particle_source_seed, simion_template_run=args.simion_template_run)
    print(f"CANDIDATE_RUN_PREPARE={result['status']} PLAN_ROOT={result['planning_root']} RUN_ROOT={result['run_root']}")


if __name__ == "__main__":
    main()
