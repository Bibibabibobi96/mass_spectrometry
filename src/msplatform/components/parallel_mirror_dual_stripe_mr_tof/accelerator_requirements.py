"""Explicit research input reading for the canonical MR/OA geometry boundary."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry import build_two_zone_accelerator_requirements as _build_two_zone_accelerator_requirements
from msplatform.components.orthogonal_accelerator.two_zone_geometry import validate_geometry_profile
from msplatform.io.manifest_records import file_record


def read_accelerator_geometry_authority(contract: dict[str, Any], *, component_contract_path: Path,
                                        geometry_profile_id: str) -> dict[str, Any]:
    """Read the explicitly selected provider profile; never search another checkout.

    The complete file record accompanies new source inputs. It is not part of
    the physical geometry fingerprint and does not rewrite a prior run.
    """
    path = Path(component_contract_path).resolve(strict=True)
    provider = json.loads(path.read_text(encoding="utf-8"))
    try:
        profile = dict(validate_geometry_profile(provider["geometry_profiles"][geometry_profile_id]))
    except (KeyError, TypeError) as error:
        raise CandidateContractError("explicit OA geometry profile authority is unavailable") from error
    return {
        "accelerator_requirements": _build_two_zone_accelerator_requirements(contract, geometry_profile=profile),
        "geometry_profile": profile,
        "geometry_profile_id": geometry_profile_id,
        "source_refs": [file_record(path)],
    }
