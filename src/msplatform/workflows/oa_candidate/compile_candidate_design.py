"""Compile an approved oa-TOF proposal into isolated candidate contracts only."""

from __future__ import annotations

from msplatform.components.single_reflection_oa_tof.design_compilation import (
    EnvelopeReviewRequired,
    compile_design_proposal,
    compile_design_overrides as _canonical_compile_overrides,
)

import argparse
import json
from pathlib import Path
from typing import Any


from msplatform.contracts.machine_contracts import load_json, sha256, validate_schema
from msplatform.workflows.design_request import validate_request
from msplatform.workflows.oa_candidate.geometry_contract import resolve_contract, serialized
from msplatform.workflows.oa_candidate.science_paths import CandidateSciencePaths


def compile_design_overrides(base_contract, overrides, *, science_root: Path):
    catalog = load_json(CandidateSciencePaths(science_root).catalog)
    return _canonical_compile_overrides(base_contract, overrides, catalog=catalog)

def compile_proposal(proposal_path: Path, *, science_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = CandidateSciencePaths(science_root)
    REGISTRY_PATH = paths.registry
    CATALOG_PATH = paths.catalog
    ENVELOPE_PATH = paths.envelope
    BASELINE_PATH = paths.baseline
    NUMERICS_PATH = paths.numerics
    proposal_path = proposal_path.resolve()
    proposal = load_json(proposal_path)
    validate_schema(proposal, "candidate_proposal.schema.json")
    if proposal["project_id"] != "single_reflection_oa_tof_mass_analyzer":
        raise ValueError(
            "candidate proposal project_id must be "
            "single_reflection_oa_tof_mass_analyzer"
        )
    request_path = Path(proposal["request"]["path"])
    if not request_path.is_absolute():
        request_path = (proposal_path.parent / request_path).resolve()
    if sha256(request_path) != proposal["request"]["sha256"]:
        raise ValueError("design request hash differs from candidate proposal")
    request = load_json(request_path)
    registry = load_json(REGISTRY_PATH)
    selection = validate_request(request, registry)
    if selection["status"] != "READY" or selection["selected_project_id"] != "single_reflection_oa_tof_mass_analyzer":
        raise ValueError(
            "design request is not ready for "
            f"single_reflection_oa_tof_mass_analyzer: {selection['status']}"
        )
    if request["status"] != "approved":
        raise ValueError("candidate compilation requires an approved design request")

    catalog = load_json(CATALOG_PATH)
    envelope = load_json(ENVELOPE_PATH)
    validate_schema(catalog, "design_variable_catalog.schema.json")
    validate_schema(envelope, "optimization_envelope.schema.json")
    if envelope["status"] != "approved":
        raise ValueError("optimization envelope is not approved")
    if envelope["reference"]["baseline_sha256"] != sha256(BASELINE_PATH):
        raise ValueError("optimization envelope reference baseline is stale")
    formal = load_json(BASELINE_PATH)
    candidate, changes, derived_changes = compile_design_proposal(
        formal, proposal, request, catalog=catalog, envelope=envelope)
    report = {
        "schema_version": 1,
        "role": "oa_tof_candidate_contract_diff",
        "candidate_id": proposal["candidate_id"],
        "request_id": request["request_id"],
        "provenance": {
            "proposal": {"path": str(proposal_path), "sha256": sha256(proposal_path)},
            "request": {"path": str(request_path), "sha256": sha256(request_path)},
            "design_variable_catalog": {"path": str(CATALOG_PATH), "sha256": sha256(CATALOG_PATH)},
            "formal_solver_numerics": {"path": str(NUMERICS_PATH), "sha256": sha256(NUMERICS_PATH)},
        },
        "optimization_envelope": {"envelope_id": envelope["envelope_id"], "sha256": sha256(ENVELOPE_PATH)},
        "formal_baseline_sha256": sha256(BASELINE_PATH),
        "changed_variables": changes,
        "derived_changes": derived_changes,
        "zero_change_reference_reproduction": not changes,
        "solver_or_cad_executed": False,
    }
    return candidate, report, request


def write_candidate(proposal_path: Path, output_dir: Path, *,
                    science_root: Path,
                    solver_numerics_contract: Path | None = None) -> tuple[Path, Path, Path]:
    paths = CandidateSciencePaths(science_root)
    candidate, report, _ = compile_proposal(proposal_path, science_root=science_root)
    numerics_source = (paths.numerics if solver_numerics_contract is None else solver_numerics_contract).resolve(strict=True)
    numerics_payload = numerics_source.read_bytes()
    output_dir.mkdir(parents=True, exist_ok=False)
    baseline_path = output_dir / "candidate_baseline.json"
    resolved_path = output_dir / "candidate_resolved_geometry.json"
    numerics_path = output_dir / "candidate_solver_numerics.json"
    report_path = output_dir / "candidate_diff.json"
    baseline_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Freeze the selected pure-data contract once; all resolution consumes this
    # copy rather than later external/default values. Validation stays with the
    # existing geometry/numerics resolver and its original policies.
    numerics_path.write_bytes(numerics_payload)
    resolved = resolve_contract(
        baseline_path=baseline_path, mode_path=paths.mode, numerics_path=numerics_path,
        project_root=paths.project_root,
    )
    report["provenance"]["solver_numerics"] = {"path": str(numerics_source),
        "sha256": resolved["inputs"]["solver_numerics_sha256"]}
    report["zero_change_reference_reproduction"] = (
        report["zero_change_reference_reproduction"] and
        resolved["inputs"]["solver_numerics_sha256"].upper() ==
        report["provenance"]["formal_solver_numerics"]["sha256"].upper())
    resolved_path.write_text(serialized(resolved), encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return baseline_path, resolved_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--science-root", required=True, type=Path)
    parser.add_argument("--solver-numerics-contract", type=Path,
                        help="Explicit solver numerics JSON; default remains the project contract")
    args = parser.parse_args()
    try:
        baseline, resolved, report = write_candidate(args.proposal, args.output_dir,
            science_root=args.science_root, solver_numerics_contract=args.solver_numerics_contract)
    except EnvelopeReviewRequired as exc:
        raise SystemExit(str(exc)) from exc
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"CANDIDATE_COMPILE=FAIL {exc}") from exc
    print(f"CANDIDATE_COMPILE=PASS BASELINE={baseline.resolve()} RESOLVED={resolved.resolve()} NUMERICS={(resolved.parent / 'candidate_solver_numerics.json').resolve()} DIFF={report.resolve()}")


if __name__ == "__main__":
    main()
