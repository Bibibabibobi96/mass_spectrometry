"""Fresh MR test inputs from the single original versioned OA profile."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import load_contract
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import build_two_zone_accelerator_requirements


_PROFILE_PATH = Path(__file__).resolve().parents[3] / "orthogonal_accelerator/config/component_contract.json"
_PROFILE_BYTES = _PROFILE_PATH.read_bytes()
_PROFILE_ID = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"


def geometry_authority(contract):
    """Return fresh mutable inputs; only the prepared source bytes are shared."""
    if isinstance(contract, (str, Path)):
        contract = load_contract(Path(contract))
    profile = json.loads(_PROFILE_BYTES)["geometry_profiles"][_PROFILE_ID]
    return {
        "accelerator_requirements": build_two_zone_accelerator_requirements(contract, geometry_profile=profile),
        "geometry_profile": profile,
        "geometry_profile_id": _PROFILE_ID,
        "source_refs": [{"path": str(_PROFILE_PATH), "bytes": len(_PROFILE_BYTES),
                         "sha256": hashlib.sha256(_PROFILE_BYTES).hexdigest()}],
    }


def pure_geometry_inputs(contract):
    """Project the same explicit authority onto the domain resolver's API."""
    authority = geometry_authority(contract)
    return {key: authority[key] for key in ("accelerator_requirements", "geometry_profile", "geometry_profile_id")}
