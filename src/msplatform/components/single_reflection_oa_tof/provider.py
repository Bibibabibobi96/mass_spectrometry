"""Path-free, solver-independent complete TOF component authoring boundary."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .geometry_contract import resolve_contract_documents
from .layout import compile_geometry_and_port
from .accelerator_geometry import apply_side_opening, resolve_accelerator_geometry
from .assembly_interface import resolve_assembly_interface


def _identity(document: dict[str, Any], name: str) -> dict[str, Any]:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return dict(path="document:" + name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def resolve_component(design: dict[str, Any], *, geometry_profile_id: str | None = None) -> dict[str, Any]:
    """Resolve explicit scientific author documents, without native or host I/O.

    Source design envelopes are retained as geometry/theory inputs; this function
    neither creates a particle cohort nor selects a release clock.
    """
    required = {"baseline", "science", "layout_profile", "base_port",
                "three_zone_candidate", "design_catalog", "side_opening"}
    if not isinstance(design, dict) or set(design) != required:
        raise ValueError("TOF design requires exactly the explicit scientific author documents")
    document = copy.deepcopy(design)
    base = resolve_contract_documents(document["baseline"], document["science"],
        input_identity={key: _identity(document[key], key) for key in ("baseline", "science")})
    candidate = document["three_zone_candidate"]
    identity = _identity(candidate, "three_zone_candidate")
    resolved, _, _ = compile_geometry_and_port(base, document["base_port"], document["layout_profile"],
        three_zone_candidate=candidate, three_zone_candidate_binding={key: identity[key] for key in ("path", "sha256")},
        design_catalog=document["design_catalog"])
    projection = apply_side_opening(resolve_accelerator_geometry(resolved, variant_id="three_zone_square"),
                                    side_opening=document["side_opening"])
    interface = resolve_assembly_interface(resolved, projection=projection, geometry_profile_id=geometry_profile_id)
    resolved["mechanical_side_opening"] = copy.deepcopy(document["side_opening"])
    return dict(resolved_design=resolved, assembly_interface=interface)
