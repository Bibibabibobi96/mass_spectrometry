"""Compile, freeze, and execute one oa-TOF structural Candidate from one request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import load_json, sha256
from common.paths.workspace_paths import resolve_workspace_paths
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import write_candidate
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import prepare_candidate_run
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import (
    CandidateWorkflowError,
    CandidateWorkflowInterrupted,
    CandidateWorkflowTimedOut,
    REUSABLE_STAGES,
    run_candidate_workflow,
)


RUNTIME_CONFIG = PROJECT_ROOT / "config" / "candidate_runtime.json"
EXECUTION_PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"


def validate_candidate_runtime(
    artifact_project_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the registered SIMION template binding."""
    artifact_root = (
        artifact_project_root
        or Path(resolve_workspace_paths(REPO_ROOT)["artifact_root"]) / "projects" / PROJECT_ROOT.name
    ).resolve()
    runtime = load_json(RUNTIME_CONFIG)
    if runtime.get("role") != "oa_tof_candidate_runtime":
        raise ValueError("candidate runtime config has an unsupported role")
    template_run_id = str(runtime.get("simion_template_run_id", ""))
    validate_run_id(template_run_id)
    template = artifact_root / "runs" / template_run_id
    from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
        _registered_candidate_template,
    )

    registration = _registered_candidate_template(template, artifact_root)
    return {
        "runtime": runtime,
        "artifact_root": artifact_root,
        "template": template,
        "registration": registration,
    }


def _proposal_for_request(request_path: Path) -> Path:
    request = request_path.resolve(strict=True)
    proposal = request.parent / "candidate_proposal.json"
    if not proposal.is_file():
        raise ValueError(
            "approved request must be accompanied by candidate_proposal.json in the same directory"
        )
    document = load_json(proposal)
    record = document.get("request", {})
    bound = Path(str(record.get("path", "")))
    if not bound.is_absolute():
        bound = (proposal.parent / bound).resolve()
    if bound != request or str(record.get("sha256", "")).upper() != sha256(request):
        raise ValueError("candidate_proposal.json does not bind the supplied request")
    return proposal


def _runtime_coverage(request_path: Path, diff_path: Path) -> None:
    request = load_json(request_path)
    diff = load_json(diff_path)
    profiles = load_json(EXECUTION_PROFILES)["profiles"]
    profile = next(
        item for item in profiles if item["profile_id"] == "validated_structural_candidate"
    )
    allowed = set(profile["supported_design_variables"])
    requested = set(request.get("design_variables", []))
    proposed = {
        item.get("variable")
        for item in diff.get("changed_variables", [])
        if item.get("change_origin") == "proposed"
    }
    unsupported = (requested | proposed) - allowed
    if unsupported:
        raise ValueError(
            "approved request contains variables without runtime coverage: "
            + ", ".join(sorted(unsupported))
        )
    if proposed - requested:
        raise ValueError("candidate proposal changes a variable absent from the approved request")
    if any(
        item.get("change_origin") != "proposed"
        for item in diff.get("changed_variables", [])
    ):
        raise ValueError("candidate runtime only accepts explicitly proposed variable changes")


def prepare_execution(
    request_path: Path,
    run_id: str,
    *,
    particle_source_seed: int,
    artifact_project_root: Path | None = None,
    campaign_table: Path | None = None,
    campaign_selection: Path | None = None,
    solver_numerics_contract: Path | None = None,
) -> Path:
    if not isinstance(particle_source_seed, int):
        raise ValueError("candidate entry requires an explicit integer particle source seed")
    identity = validate_run_id(run_id)
    artifact_root = (
        artifact_project_root
        or Path(resolve_workspace_paths(REPO_ROOT)["artifact_root"]) / "projects" / PROJECT_ROOT.name
    ).resolve()
    request = request_path.resolve(strict=True)
    proposal = _proposal_for_request(request)
    preparation = (
        artifact_root
        / "scratch"
        / f"{identity['stamp']}__cross__candidate-entry-{sha256(request)[:8].lower()}"
    )
    contracts = preparation / "candidate_contracts"
    numeric_arguments = ({"solver_numerics_contract": solver_numerics_contract}
                         if solver_numerics_contract is not None else {})
    baseline, resolved, diff = write_candidate(proposal, contracts, **numeric_arguments)
    _runtime_coverage(request, diff)
    runtime_preflight = validate_candidate_runtime(artifact_root)
    template = runtime_preflight["template"]
    plan = prepare_candidate_run(
        baseline,
        resolved,
        diff,
        run_id,
        artifact_root,
        particle_source_seed=particle_source_seed,
        simion_template_run=template,
        campaign_table=campaign_table,
        campaign_selection=campaign_selection,
    )
    plan_path = Path(plan["planning_root"]) / "candidate_workflow_plan.json"
    document = load_json(plan_path)
    stages = document["stages"]
    if [item["stage_id"] for item in stages] != [
        "static_inputs",
        "comsol_candidate",
        "simion_candidate",
        "cad_candidate",
        "structural_acceptance",
    ]:
        raise ValueError("candidate workflow is not the governed fixed linear sequence")
    document["entry_request"] = {
        "path": str(request),
        "sha256": sha256(request),
    }
    plan_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return plan_path


def execute_request(
    request_path: Path,
    run_id: str,
    *,
    simion_executable: Path,
    particle_source_seed: int,
    artifact_project_root: Path | None = None,
    reuse_parent: Path | None = None,
    reuse_through: str | None = None,
    stage_executor: Any = None,
    campaign_table: Path | None = None,
    campaign_selection: Path | None = None,
    pa_handoff_output: Path | None = None,
    pa_producer_handoffs: list[tuple[Path, Path]] | None = None,
    solver_numerics_contract: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    executable = simion_executable.resolve(strict=True)
    plan = prepare_execution(
        request_path,
        run_id,
        particle_source_seed=particle_source_seed,
        artifact_project_root=artifact_project_root,
        campaign_table=campaign_table,
        campaign_selection=campaign_selection,
        solver_numerics_contract=solver_numerics_contract,
    )
    kwargs: dict[str, Any] = {
        "reuse_parent": reuse_parent,
        "reuse_through": reuse_through,
    }
    if pa_handoff_output is not None or pa_producer_handoffs:
        kwargs.update(pa_handoff_output=pa_handoff_output, pa_producer_handoffs=pa_producer_handoffs)
    if stage_executor is not None:
        kwargs["stage_executor"] = stage_executor
    return run_candidate_workflow(
        plan,
        str(executable),
        **kwargs,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--postprocess-from", type=Path, metavar="PARENT_RUN",
                        help="New read-only-parent COMSOL postprocessing child; no physical solve")
    parser.add_argument("--particle-source-seed", type=int)
    parser.add_argument("--solver-numerics-contract", type=Path,
                        help="Explicit supported solver numerics data; default unchanged, no Formal qualification")
    parser.add_argument("--resume-finalization", type=Path, metavar="RUN_DIR",
                        help="Resume publication from an existing run's frozen request")
    parser.add_argument("--owner-result", type=Path,
                        help="Existing owner Result when an explicit PA handoff output was used")
    parser.add_argument("--simion-exe", type=Path)
    parser.add_argument("--reuse-parent", type=Path)
    parser.add_argument("--reuse-through", choices=REUSABLE_STAGES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pa-handoff-output", type=Path,
                        help="Preserve the actual lifecycle owner Result outside the run for an explicit PA handoff")
    parser.add_argument("--pa-producer-handoff", type=Path, nargs=2, action="append", metavar=("TRANSACTION", "OWNER_RESULT"))
    parser.add_argument("--campaign-table", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--campaign-selection", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.postprocess_from is not None:
        if args.run_id is None or any((args.request, args.particle_source_seed is not None, args.resume_finalization,
                args.owner_result, args.simion_exe, args.reuse_parent, args.reuse_through, args.dry_run,
                args.pa_handoff_output, args.pa_producer_handoff, args.campaign_table, args.campaign_selection,
                args.solver_numerics_contract)):
            parser.error("--postprocess-from requires new --run-id and rejects new execution/reuse/finalization options")
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import run_candidate_postprocess
        try:
            root, summary = run_candidate_postprocess(args.postprocess_from, args.run_id)
        except (OSError, KeyError, ValueError, CandidateWorkflowError) as error:
            raise SystemExit(f"OATOF_CANDIDATE=POSTPROCESS_FAILED ERROR={error}") from error
        print(f"OATOF_CANDIDATE=POSTPROCESSED RUN_ROOT={root} SCOPE={summary['scope']}")
        return
    if args.resume_finalization is not None:
        if any((args.request, args.run_id is not None, args.particle_source_seed is not None, args.simion_exe,
                args.reuse_parent, args.reuse_through, args.dry_run, args.pa_handoff_output,
                args.pa_producer_handoff, args.campaign_table, args.campaign_selection,
                args.solver_numerics_contract)):
            parser.error("--resume-finalization rejects new scientific/execution inputs")
        from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate_workflow import (
            resume_candidate_finalization,
        )
        try:
            run_root, summary = resume_candidate_finalization(args.resume_finalization, args.owner_result)
        except (OSError, KeyError, ValueError, CandidateWorkflowError) as exc:
            raise SystemExit(f"OATOF_CANDIDATE=FINALIZATION_FAILED RUN_ROOT={args.resume_finalization} ERROR={exc}") from exc
        print(f"OATOF_CANDIDATE=FINALIZED RUN_ROOT={run_root} DECISION={summary['candidate_decision']}")
        return
    if args.owner_result is not None:
        parser.error("--owner-result requires --resume-finalization")
    if args.request is None or args.particle_source_seed is None or args.run_id is None:
        parser.error("execution requires --request, --run-id and --particle-source-seed")
    if args.dry_run and (args.pa_handoff_output is not None or args.pa_producer_handoff):
        parser.error("PA producer handoff requires execution; it cannot be combined with --dry-run")
    if args.pa_handoff_output is not None and args.pa_handoff_output.exists():
        parser.error("--pa-handoff-output must be a new path")
    try:
        plan = prepare_execution(
            args.request,
            args.run_id,
            particle_source_seed=args.particle_source_seed,
            campaign_table=args.campaign_table,
            campaign_selection=args.campaign_selection,
            solver_numerics_contract=args.solver_numerics_contract,
        )
        if args.dry_run:
            print(f"OATOF_CANDIDATE=EXECUTION_READY PLAN={plan}")
            return
        if args.simion_exe is None:
            parser.error("execution requires --simion-exe")
        simion_executable = args.simion_exe.resolve(strict=True)
        run_root, summary = run_candidate_workflow(
            plan,
            str(simion_executable),
            reuse_parent=args.reuse_parent,
            reuse_through=args.reuse_through,
            pa_handoff_output=args.pa_handoff_output,
            pa_producer_handoffs=args.pa_producer_handoff,
        )
    except CandidateWorkflowInterrupted as exc:
        raise SystemExit(130) from exc
    except CandidateWorkflowTimedOut as exc:
        print(f"OATOF_CANDIDATE=TIMEOUT RUN_ROOT={exc.run_root}", file=sys.stderr)
        raise SystemExit(124) from exc
    except CandidateWorkflowError as exc:
        print(f"OATOF_CANDIDATE=FAIL RUN_ROOT={exc.run_root} ERROR={exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"OATOF_CANDIDATE=FAIL_BEFORE_RUN ERROR={exc}") from exc
    print(
        f"OATOF_CANDIDATE=PASS RUN_ROOT={run_root} "
        f"DECISION={summary['candidate_decision']} "
        f"RESULT={args.pa_handoff_output or run_root.parent.parent / 'scratch' / 'workflow_results' / run_root.name / 'result.json'}"
    )


if __name__ == "__main__":
    main()
