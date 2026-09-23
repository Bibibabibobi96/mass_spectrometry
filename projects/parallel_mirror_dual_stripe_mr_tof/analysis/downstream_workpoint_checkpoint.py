"""Deterministically reconstruct an interrupted downstream iteration checkpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import (
    decide_iteration,
    assert_trial_matches_jacobian,
    resolve_operating_cache_binding,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)

PROJECT = "parallel_mirror_dual_stripe_mr_tof"
CHILD_MODE = "finite_3d_two_prism_voltage_trial"
PARENT_MODE = "downstream_fixed_grid_workpoint_iteration"


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _same_file(left: Path, right: Path, label: str) -> None:
    if _sha(left) != _sha(right):
        raise CandidateContractError(f"checkpoint {label} differs from the current frozen input")


def _manifest_output(manifest_path: Path, name: str) -> Path:
    manifest = _load(manifest_path, "child manifest")
    matches = [item for item in manifest.get("outputs", []) if Path(str(item.get("path", ""))).name == name]
    if len(matches) != 1:
        raise CandidateContractError(f"child manifest must bind exactly one {name}")
    result = Path(str(matches[0]["path"]))
    if not result.is_absolute():
        result = manifest_path.parent / result
    if not result.is_file() or _sha(result).lower() != str(matches[0].get("sha256", "")).lower():
        raise CandidateContractError(f"child manifest output is missing or changed: {name}")
    return result.resolve()


def _child_manifest_ok(path: Path) -> dict[str, Any]:
    value = _load(path, "child manifest")
    if (
        value.get("schema_version") != 2
        or value.get("role") != "simulation_run_manifest"
        or value.get("project") != PROJECT
        or value.get("mode") != CHILD_MODE
        or value.get("status") != "success"
    ):
        raise CandidateContractError(f"child manifest is not verified success: {path}")
    return value


def _voltages(materialization: Mapping[str, Any]) -> np.ndarray:
    result = np.asarray(
        [*materialization.get("stripe_biases_v", []), *materialization.get("prism_voltages_v", [])],
        dtype=float,
    )
    if result.shape != (4,) or not np.all(np.isfinite(result)):
        raise CandidateContractError("child materialization lacks four finite voltages")
    return result


def _child_requested_voltages(child_manifest: Mapping[str, Any], child_path: Path) -> np.ndarray:
    """Read the immutable voltage request bound to a verified child manifest."""
    binding = child_manifest.get("run_config")
    if not isinstance(binding, Mapping):
        raise CandidateContractError("child manifest lacks run-config identity")
    config_path = Path(str(binding.get("path", "")))
    if not config_path.is_absolute():
        config_path = child_path.parent / config_path
    if not config_path.is_file() or _sha(config_path).lower() != str(binding.get("sha256", "")).lower():
        raise CandidateContractError("child run config is missing or changed")
    parameters = _load(config_path, "child run config").get("parameters")
    if not isinstance(parameters, Mapping):
        raise CandidateContractError("child run config lacks parameters")
    result = np.asarray([
        *parameters.get("stripe_biases_v", []),
        parameters.get("prism_1_voltage_v"),
        parameters.get("prism_2_voltage_v"),
    ], dtype=float)
    if result.shape != (4,) or not np.all(np.isfinite(result)):
        raise CandidateContractError("child run config lacks four finite requested voltages")
    return result


def reconstruct_checkpoint(
    old_parent_run: Path,
    latest_child_manifest: Path,
    current_initial_manifest: Path,
    current_proposal: Path,
    current_contract: Path,
    artifact_project_runs: Path,
) -> dict[str, Any]:
    """Rebuild trusted state from frozen inputs and a continuous child chain."""
    old_parent_run = old_parent_run.resolve()
    parent_manifest_path = old_parent_run / "run_manifest.json"
    parent_manifest = _load(parent_manifest_path, "old parent manifest")
    if (
        parent_manifest.get("project") != PROJECT
        or parent_manifest.get("mode") != PARENT_MODE
        or parent_manifest.get("status") not in {"checkpoint", "failed", "interrupted"}
    ):
        raise CandidateContractError("old parent is not a resumable workpoint workflow")
    old_run_id = parent_manifest.get("run_id")
    if not isinstance(old_run_id, str) or not old_run_id:
        raise CandidateContractError("old parent manifest lacks run_id")
    declared_outputs = parent_manifest.get("outputs")
    if not isinstance(declared_outputs, list):
        raise CandidateContractError("old parent manifest outputs are invalid")
    output_names = {Path(str(item.get("path", ""))).name for item in declared_outputs if isinstance(item, Mapping)}
    modern_checkpoint = {"iteration_history.json", "iteration_lineage.json"}.issubset(output_names)
    if modern_checkpoint:
        for item in declared_outputs:
            if not isinstance(item, Mapping):
                raise CandidateContractError("old parent manifest output identity is invalid")
            output = Path(str(item.get("path", "")))
            if not output.is_absolute():
                output = old_parent_run / output
            if not output.is_file() or _sha(output).lower() != str(item.get("sha256", "")).lower():
                raise CandidateContractError(f"old parent checkpoint output differs: {output}")
        run_config = parent_manifest.get("run_config")
        if not isinstance(run_config, Mapping):
            raise CandidateContractError("old parent checkpoint lacks run_config identity")
        if _sha(old_parent_run / "run_config.json").lower() != str(run_config.get("sha256", "")).lower():
            raise CandidateContractError("old parent checkpoint run_config differs")
    old_inputs = old_parent_run / "inputs"
    _same_file(old_inputs / "initial_workpoint.json", current_proposal, "initial proposal/Jacobian")
    _same_file(old_inputs / "contract.json", current_contract, "contract")
    _same_file(old_inputs / "initial_workpoint_manifest.json", current_initial_manifest, "initial manifest")

    latest_doc = _child_manifest_ok(latest_child_manifest.resolve())
    # A failed recovery parent retains the continuous iteration lineage from
    # its predecessor.  The latest verified iteration may therefore have the
    # predecessor's run id; membership is checked against that frozen lineage
    # below rather than against the recovery parent's directory name.
    match = re.fullmatch(r".+-iter-(\d+)", str(latest_doc.get("run_id", "")))
    if match is None:
        raise CandidateContractError("latest child does not belong to the old parent iteration sequence")
    completed = int(match.group(1))
    if completed < 1:
        raise CandidateContractError("latest child iteration must be positive")

    proposal = _load(current_proposal, "initial proposal")
    contract = _load(current_contract, "contract")
    expected = np.asarray(proposal.get("proposed_voltages_v"), dtype=float)
    if expected.shape != (4,) or not np.all(np.isfinite(expected)):
        raise CandidateContractError("initial proposal lacks four finite voltages")
    replayed: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    old_resume = old_inputs / "resume_successful_child_manifest.json"
    old_decisions = old_parent_run / "results"
    recorded_history: list[dict[str, Any]] | None = None
    old_history_path = old_decisions / "iteration_history.json"
    if old_history_path.is_file():
        candidate_history = _load(old_history_path, "old parent history").get("decisions")
        if not isinstance(candidate_history, list):
            raise CandidateContractError("old parent history decisions are invalid")
        recorded_history = candidate_history
    lineage_manifests: dict[int, Path] = {}
    lineage_decisions: dict[int, Path] = {}
    old_lineage_path = old_decisions / "iteration_lineage.json"
    if old_lineage_path.is_file():
        old_lineage = _load(old_lineage_path, "old parent lineage")
        children = old_lineage.get("children")
        if not isinstance(children, list):
            raise CandidateContractError("old parent lineage children are invalid")
        for expected_iteration, item in enumerate(children, 1):
            if not isinstance(item, Mapping) or item.get("iteration") != expected_iteration:
                raise CandidateContractError("old parent lineage iterations are not continuous")
            child_path = Path(str(item.get("child_manifest", "")))
            if not child_path.is_file() or _sha(child_path).lower() != str(item.get("child_manifest_sha256", "")).lower():
                raise CandidateContractError("old parent lineage child manifest identity differs")
            lineage_manifests[expected_iteration] = child_path
            decision_path_text = item.get("decision")
            if decision_path_text is not None:
                decision_path = Path(str(decision_path_text))
                if (
                    not decision_path.is_file()
                    or _sha(decision_path).lower() != str(item.get("decision_sha256", "")).lower()
                ):
                    raise CandidateContractError("old parent lineage decision identity differs")
                lineage_decisions[expected_iteration] = decision_path
    if lineage_manifests:
        expected_latest = lineage_manifests.get(completed)
        if expected_latest is None or _sha(expected_latest) != _sha(latest_child_manifest):
            raise CandidateContractError("latest child is not the retained parent iteration lineage tip")
    elif not re.fullmatch(re.escape(old_run_id) + r"-iter-\d+", str(latest_doc.get("run_id", ""))):
        raise CandidateContractError("latest child does not belong to the old parent iteration sequence")
    recorded_numbers = sorted(
        int(match.group(1))
        for path in old_decisions.glob("iteration_*_decision.json")
        if (match := re.fullmatch(r"iteration_(\d+)_decision\.json", path.name)) is not None
    )
    if recorded_numbers not in [list(range(1, completed)), list(range(1, completed + 1))]:
        raise CandidateContractError("old parent decision iterations are not continuous through the latest child")
    latest_baseline: Path | None = None
    latest_cache: dict[str, Any] | None = None
    migrated_latest_terminal = False
    migrated_latest_controller = False

    for iteration in range(1, completed + 1):
        if recorded_history is not None:
            for recovery_model in recorded_history:
                if (
                    isinstance(recovery_model, Mapping)
                    and recovery_model.get("role") == "mrtof_downstream_workpoint_iteration_recovery_model"
                    and recovery_model.get("recovery_after_iteration") == iteration - 1
                ):
                    replayed.append(dict(recovery_model))
        if iteration in lineage_manifests:
            child_manifest = lineage_manifests[iteration]
        elif iteration == 1 and old_resume.is_file():
            child_manifest = old_resume
        else:
            child_manifest = artifact_project_runs / f"{old_run_id}-iter-{iteration:02d}" / "run_manifest.json"
        child_doc = _child_manifest_ok(child_manifest)
        if iteration == completed and (
            child_doc.get("run_id") != latest_doc.get("run_id")
            or _sha(child_manifest) != _sha(latest_child_manifest)
        ):
            raise CandidateContractError("latest successful child is not the continuous Nth child")
        observation_path = _manifest_output(child_manifest, "two_prism_trial_observation.json")
        materialization_path = _manifest_output(child_manifest, "two_prism_trial_materialization.json")
        child_config = _load(observation_path.parents[1] / "run_config.json", "child run config")
        binding_mode = child_config.get("parameters", {}).get("pa_binding_mode")
        native = binding_mode == "native_corridor_private_fast_adjust_family__four_instances__n1"
        if not native:
            raise CandidateContractError(
                f"iteration {iteration} uses a retired non-native PA binding"
            )
        identity_path = _manifest_output(child_manifest, "native_corridor_runtime_family.json")
        protection_path = _manifest_output(child_manifest, "native_corridor_protection_renewal.json")
        baseline_path = _manifest_output(child_manifest, "artifact_capacity_gate_terminal.json")
        materialization = _load(materialization_path, "child materialization")
        actual = _voltages(materialization)
        requested = _child_requested_voltages(child_doc, child_manifest)
        if not np.allclose(actual, requested, rtol=0.0, atol=1e-10):
            raise CandidateContractError(f"iteration {iteration} materialization differs from requested voltage")
        cache = resolve_operating_cache_binding(
            _load(identity_path, "cache identity"), _load(protection_path, "cache protection renewal")
        )
        if cache.get("native_bank_identity") != proposal.get("native_bank_identity"):
            raise CandidateContractError("checkpoint native bank differs from initial Jacobian")
        assert_trial_matches_jacobian(proposal, child_manifest)
        decision = decide_iteration(
            proposal,
            _load(observation_path, "child observation"),
            materialization,
            contract,
            replayed,
            iteration,
        )
        recorded_path = lineage_decisions.get(
            iteration, old_decisions / f"iteration_{iteration:02d}_decision.json"
        )
        if recorded_path.is_file():
            recorded = _load(recorded_path, "recorded decision")
            recorded_observation = recorded.get("observation_record")
            if isinstance(recorded_observation, Mapping):
                recorded_voltage = np.asarray(recorded_observation.get("voltages_v"), dtype=float)
                if (
                    recorded_voltage.shape != (4,)
                    or not np.all(np.isfinite(recorded_voltage))
                    or not np.allclose(recorded_voltage, actual, rtol=0.0, atol=1e-10)
                ):
                    raise CandidateContractError(
                        f"recorded iteration {iteration} observation voltage differs from child materialization"
                    )
            if recorded != decision:
                legacy_controller = "candidate_accepted" not in recorded
                if iteration < completed:
                    # Historical decisions are immutable evidence.  Their child
                    # manifest, field identity and requested-voltage chain were
                    # verified above; a newer controller may add persistence or
                    # diagnostics without invalidating those flights.  Only the
                    # newest child is reclassified by the current controller.
                    decision = recorded
                    migrated_latest_terminal = False
                    migrated_latest_controller = True
                else:
                    migrated_latest_terminal = bool(
                        iteration == completed
                        and decision.get("state") == "continue"
                        and recorded.get("state") == "terminal"
                        and (
                            (
                                recorded.get("terminal_reason") == decision.get("invalid_trial_reason")
                                and decision.get("coordinate_group") == "physical_topology_backtrack"
                            )
                            or recorded.get("terminal_reason") == "residual_stagnation"
                        )
                    )
                    migrated_latest_controller = bool(iteration == completed)
                    if not migrated_latest_terminal and not migrated_latest_controller:
                        raise CandidateContractError(
                            f"recorded iteration {iteration} decision differs from deterministic replay"
                        )
        elif iteration != completed:
            raise CandidateContractError(f"recorded decision is missing before latest child: iteration {iteration}")
        if decision.get("state") == "recovery_required":
            if iteration != completed:
                raise CandidateContractError("model recovery must follow the latest completed child")
            replayed.append(decision)
            expected = np.asarray(
                decision["recovery_state"]["accepted_anchor"]["voltages_v"], dtype=float
            )
            lineage.append({
                "iteration": iteration,
                "run_id": child_doc["run_id"],
                "child_manifest": str(child_manifest.resolve()),
                "child_manifest_sha256": _sha(child_manifest),
                "observation": str(observation_path),
                "materialization": str(materialization_path),
                "operating_cache_identity": str(identity_path),
                "operating_cache_protection_renewal": str(protection_path),
                "operating_cache_key": cache["cache_key"],
                "replayed_checkpoint": True,
            })
            latest_baseline = baseline_path
            latest_cache = cache
            recovery_required = decision
            break
        if decision.get("state") != "continue":
            raise CandidateContractError(f"iteration {iteration} is already terminal and cannot be resumed")
        replayed.append(decision)
        expected = np.asarray(decision["proposed_voltages_v"], dtype=float)
        lineage.append({
            "iteration": iteration,
            "run_id": child_doc["run_id"],
            "child_manifest": str(child_manifest.resolve()),
            "child_manifest_sha256": _sha(child_manifest),
            "observation": str(observation_path),
            "materialization": str(materialization_path),
            "operating_cache_identity": str(identity_path),
            "operating_cache_protection_renewal": str(protection_path),
            "operating_cache_key": cache["cache_key"],
            "replayed_checkpoint": True,
        })
        latest_baseline = baseline_path
        latest_cache = cache

    assert latest_baseline is not None and latest_cache is not None
    if recorded_history is not None and len(lineage_decisions) != completed:
        old_history = [item for item in recorded_history if not (
            isinstance(item, Mapping)
            and item.get("role") == "mrtof_downstream_workpoint_iteration_recovery_model"
        )]
        replayed_decisions = [item for item in replayed if not (
            isinstance(item, Mapping)
            and item.get("role") == "mrtof_downstream_workpoint_iteration_recovery_model"
        )]
        if len(old_history) not in {completed - 1, completed}:
            raise CandidateContractError("old parent history length differs from the completed child chain")
        comparable_length = len(old_history) - (1 if (migrated_latest_terminal or migrated_latest_controller)
                                                 and len(old_history) == completed else 0)
        if old_history[:comparable_length] != replayed_decisions[:comparable_length]:
            raise CandidateContractError("old parent history differs from deterministic replay")
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_workpoint_reconstructed_checkpoint",
        "source_parent_run": str(old_parent_run),
        "source_parent_manifest_sha256": _sha(parent_manifest_path),
        "completed_iterations": completed,
        "next_iteration": completed + 1,
        "current_voltages_v": expected.tolist(),
        "history": {"schema_version": 1, "role": "mrtof_downstream_workpoint_iteration_history", "decisions": replayed},
        "lineage_children": lineage,
        "latest_child_manifest": str(latest_child_manifest.resolve()),
        "latest_capacity_baseline_receipt": str(latest_baseline),
        "latest_capacity_baseline_receipt_sha256": _sha(latest_baseline),
        "latest_cache": latest_cache,
        "latest_observation": lineage[-1]["observation"],
        "latest_materialization": lineage[-1]["materialization"],
        "latest_cache_protection_renewal": lineage[-1]["operating_cache_protection_renewal"],
        "latest_replayed_decision": replayed[-1],
        "recovery_required_decision": locals().get("recovery_required"),
        "recovery_state_path": str(old_decisions / "iteration_recovery_state.json")
        if (old_decisions / "iteration_recovery_state.json").is_file() else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-parent-run", required=True, type=Path)
    parser.add_argument("--latest-child-manifest", required=True, type=Path)
    parser.add_argument("--current-initial-manifest", required=True, type=Path)
    parser.add_argument("--current-proposal", required=True, type=Path)
    parser.add_argument("--current-contract", required=True, type=Path)
    parser.add_argument("--artifact-project-runs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = reconstruct_checkpoint(
        args.old_parent_run,
        args.latest_child_manifest,
        args.current_initial_manifest,
        args.current_proposal,
        args.current_contract,
        args.artifact_project_runs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_CHECKPOINT_RESUMED=iteration-{result['next_iteration']:02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
