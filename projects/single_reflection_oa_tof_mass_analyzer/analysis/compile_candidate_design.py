"""Project forwarding for installed OA-TOF candidate design compilation."""
from __future__ import annotations

import sys
from pathlib import Path

from msplatform.workflows.oa_candidate.compile_candidate_design import (
    EnvelopeReviewRequired as EnvelopeReviewRequired,
    _constraint_passes as _constraint_passes,
    _derive_accelerator_focus as _derive_accelerator_focus,
    _derive_reflectron_for_flight_length as _derive_reflectron_for_flight_length,
    _envelope_excesses as _envelope_excesses,
    _variable_envelope_excesses as _variable_envelope_excesses,
    compile_design_overrides as _compile_design_overrides,
    compile_proposal as _compile_proposal,
    derive_accelerator_outer_envelope_min_z as derive_accelerator_outer_envelope_min_z,
    derive_shield_bounds as derive_shield_bounds,
    pointer_get as pointer_get,
    pointer_set as pointer_set,
    pointer_tokens as pointer_tokens,
    write_candidate as _write_candidate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]


def compile_design_overrides(base_contract, overrides):
    return _compile_design_overrides(base_contract, overrides, science_root=REPO_ROOT)


def _validate_invariants(baseline):
    from msplatform.workflows.oa_candidate.compile_candidate_design import _validate_invariants as installed
    return installed(baseline, science_root=REPO_ROOT)


def compile_proposal(proposal_path: Path):
    return _compile_proposal(proposal_path, science_root=REPO_ROOT)


def write_candidate(
    proposal_path: Path, output_dir: Path, *, solver_numerics_contract: Path | None = None,
):
    return _write_candidate(
        proposal_path, output_dir, science_root=REPO_ROOT,
        solver_numerics_contract=solver_numerics_contract,
    )


def main() -> None:
    from msplatform.workflows.oa_candidate.compile_candidate_design import main as installed_main
    if "--science-root" not in sys.argv:
        sys.argv.extend(["--science-root", str(REPO_ROOT)])
    installed_main()


if __name__ == "__main__":
    main()
