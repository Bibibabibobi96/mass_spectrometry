"""Compose a governed downstream-owned terminal onto a resolved multipole design."""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    canonical_sha256,
    resolved_design_sha256,
)
from common.multipole.grounded_shield import require_grounded_potential


TERMINAL_PROFILE_SCHEMA = "multipole_downstream_terminal_profiles.schema.json"
RESOLVED_SCHEMA = "multipole_resolved_design.schema.json"
COMPOSER_ID = "common.multipole.downstream_terminal.compose_downstream_terminal"
_ABS_TOL = 1e-12


class DownstreamTerminalError(MultipoleDesignCompileError):
    """Raised when a terminal registry or composition is inconsistent."""


def select_downstream_terminal_profile(
    registry: Mapping[str, Any],
    terminal_profile_id: str,
    *,
    upstream_project_id: str,
) -> dict[str, Any]:
    """Validate an integration-owned registry and select one compatible profile."""
    document = copy.deepcopy(dict(registry))
    try:
        validate_schema(document, TERMINAL_PROFILE_SCHEMA)
    except ContractError as error:
        raise DownstreamTerminalError(str(error)) from error
    if upstream_project_id not in document["allowed_upstream_project_ids"]:
        raise DownstreamTerminalError(
            f"terminal registry does not allow upstream project {upstream_project_id!r}"
        )
    matches = [
        profile
        for profile in document["profiles"]
        if profile["terminal_profile_id"] == terminal_profile_id
    ]
    if len(matches) != 1:
        raise DownstreamTerminalError(
            f"downstream terminal profile is not unique: {terminal_profile_id!r}"
        )
    return copy.deepcopy(matches[0])


def _rod_electrode_potentials(resolved: Mapping[str, Any]) -> list[dict[str, Any]]:
    segmentation = resolved["segmentation"]
    expanded = segmentation.get("segmented_rod_array")
    if expanded is None:
        potential = float(resolved["drive"]["common_mode_offset_V"])
        return [
            {"electrode_id": int(group), "potential_V": potential}
            for group in (1, 2)
        ]
    potentials: dict[int, float] = {}
    for electrode in expanded["electrodes"]:
        electrode_id = int(electrode["electrode_id"])
        potential = float(electrode["common_mode_V"])
        previous = potentials.setdefault(electrode_id, potential)
        if not math.isclose(previous, potential, rel_tol=0, abs_tol=_ABS_TOL):
            raise DownstreamTerminalError(
                f"electrode_id {electrode_id} has inconsistent common-mode potentials"
            )
    return [
        {"electrode_id": electrode_id, "potential_V": potentials[electrode_id]}
        for electrode_id in sorted(potentials)
    ]


def _static_references(resolved: Mapping[str, Any]) -> tuple[float, float]:
    static = resolved["static_electrodes_V"]
    if static["role"] == "cylindrical_shield_static_electrodes":
        return (
            float(static["shield_entrance_outer_endcap_aperture_plate_connector_V"]),
            float(static["exit_outer_endcap_aperture_plate_connector_V"]),
        )
    if static["role"] == "rectangular_reference_static_electrodes":
        return (
            float(static["entrance_aperture_plate_and_connector_V"]),
            float(static["exit_outer_enclosure_and_connector_V"]),
        )
    raise DownstreamTerminalError("unsupported static-electrode role")


def compose_downstream_terminal(
    resolved_design: Mapping[str, Any],
    terminal_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic resolved design with one downstream-owned terminal.

    The profile is selected by the integration layer.  This function derives all
    physical planes and entity potentials so solver adapters do not branch on mode.
    """
    resolved = copy.deepcopy(dict(resolved_design))
    profile = copy.deepcopy(dict(terminal_profile))
    try:
        validate_schema(resolved, RESOLVED_SCHEMA)
    except ContractError as error:
        raise DownstreamTerminalError(str(error)) from error
    if resolved.get("terminal_composition") is not None:
        raise DownstreamTerminalError("resolved design already has a downstream terminal")
    if resolved_design_sha256(resolved) != resolved["resolved_sha256"]:
        raise DownstreamTerminalError("base resolved design hash is stale")
    required_profile_fields = {
        "terminal_profile_id", "owner", "surface_role", "rod_end_clearance_mm",
        "upstream_enclosure_end_plane_binding", "electrode_thickness_mm",
        "outer_envelope", "aperture", "upstream_entrance_reference_sleeve",
        "terminal_potential_V",
    }
    if set(profile) != required_profile_fields:
        raise DownstreamTerminalError("terminal profile fields differ")
    if profile["owner"] not in {"upstream", "downstream"}:
        raise DownstreamTerminalError("composed terminal owner is unsupported")
    if profile["surface_role"] != "aperture_outer_tangent_plane":
        raise DownstreamTerminalError("terminal surface role differs")
    if profile["upstream_enclosure_end_plane_binding"] != (
        "interfaces_mm.exit.aperture_plate_upstream_face_z_mm"
    ):
        raise DownstreamTerminalError("upstream enclosure plane binding differs")
    numeric_values = [
        profile["rod_end_clearance_mm"], profile["electrode_thickness_mm"],
        profile["outer_envelope"]["width_mm"], profile["outer_envelope"]["height_mm"],
        profile["upstream_entrance_reference_sleeve"]["inner_radius_mm"],
        profile["upstream_entrance_reference_sleeve"]["outer_radius_mm"],
        profile["upstream_entrance_reference_sleeve"]["minimum_insulation_gap_mm"],
        profile["upstream_entrance_reference_sleeve"]["downstream_rod_clearance_mm"],
        profile["terminal_potential_V"],
    ]
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value)) for value in numeric_values
    ):
        raise DownstreamTerminalError("terminal profile numbers must be finite")
    positive_dimensions = numeric_values[:-2]
    if any(float(value) <= 0 for value in positive_dimensions):
        raise DownstreamTerminalError("terminal profile dimensions must be positive")
    if float(profile["upstream_entrance_reference_sleeve"]["downstream_rod_clearance_mm"]) < 0:
        raise DownstreamTerminalError("reference sleeve downstream rod clearance must be nonnegative")
    outer = profile["outer_envelope"]
    aperture = profile["aperture"]
    if outer.get("shape") != "rectangular":
        raise DownstreamTerminalError("terminal outer envelope must be rectangular")
    aperture_shape = aperture.get("shape")
    if aperture_shape not in {"rectangular", "circular"}:
        raise DownstreamTerminalError("terminal aperture shape is unsupported")
    if aperture_shape == "rectangular":
        try:
            aperture_width = float(aperture["width_mm"])
            aperture_height = float(aperture["height_mm"])
        except (KeyError, TypeError, ValueError) as error:
            raise DownstreamTerminalError("rectangular terminal aperture dimensions are invalid") from error
        if not all(math.isfinite(value) and value > 0 for value in (aperture_width, aperture_height)):
            raise DownstreamTerminalError("rectangular terminal aperture dimensions must be positive")
        if aperture.get("width_axis") != "multipole_x" or aperture.get("height_axis") != "multipole_y":
            raise DownstreamTerminalError("terminal aperture local axes differ")
        if aperture_width >= float(outer["width_mm"]) or aperture_height >= float(outer["height_mm"]):
            raise DownstreamTerminalError("terminal aperture must remain inside its outer envelope")
    else:
        try:
            raw_aperture_radius = aperture["radius_mm"]
            if isinstance(raw_aperture_radius, bool):
                raise TypeError("boolean radius is not physical")
            aperture_radius = float(raw_aperture_radius)
        except (KeyError, TypeError, ValueError) as error:
            raise DownstreamTerminalError("circular terminal aperture radius is invalid") from error
        if not math.isfinite(aperture_radius) or aperture_radius <= 0:
            raise DownstreamTerminalError("circular terminal aperture radius must be positive")
        if 2.0 * aperture_radius >= min(float(outer["width_mm"]), float(outer["height_mm"])):
            raise DownstreamTerminalError("terminal aperture must remain inside its outer envelope")

    rod_end = float(resolved["geometry_mm"]["rod_z_max"])
    surface_plane = rod_end + float(profile["rod_end_clearance_mm"])
    upstream_end = float(
        resolved["interfaces_mm"]["exit"]["aperture_plate_upstream_face_z_mm"]
    )
    enclosure_clearance = surface_plane - upstream_end
    if upstream_end < rod_end - _ABS_TOL or enclosure_clearance < -_ABS_TOL:
        raise DownstreamTerminalError(
            "upstream enclosure end plane intersects rods or downstream terminal"
        )
    try:
        terminal_potential = require_grounded_potential(
            profile["terminal_potential_V"], "downstream shield terminal"
        )
        require_grounded_potential(output_static := _static_references(resolved)[1], "upstream output shield")
        require_grounded_potential(_static_references(resolved)[0], "upstream entrance shield")
    except ValueError as error:
        raise DownstreamTerminalError(str(error)) from error
    if not math.isclose(output_static, terminal_potential, rel_tol=0, abs_tol=_ABS_TOL):
        raise DownstreamTerminalError(
            "resolved output reference differs from downstream terminal potential"
        )
    if not math.isclose(
        float(resolved["axial_drive"]["output_reference_V"]),
        terminal_potential,
        rel_tol=0,
        abs_tol=_ABS_TOL,
    ):
        raise DownstreamTerminalError(
            "axial-drive output reference differs from downstream terminal potential"
        )
    rod_electrodes = _rod_electrode_potentials(resolved)
    entrance_rod_potential = rod_electrodes[0]["potential_V"]
    sleeve_profile = profile["upstream_entrance_reference_sleeve"]
    enclosure = resolved["geometry_mm"]["enclosure"]
    entrance = resolved["interfaces_mm"]["entrance"]
    sleeve_inner = float(sleeve_profile["inner_radius_mm"])
    sleeve_outer = float(sleeve_profile["outer_radius_mm"])
    insulation_gap = float(sleeve_profile["minimum_insulation_gap_mm"])
    sleeve_upstream = float(enclosure["entrance_outer_endcap_upstream_face_z_mm"])
    sleeve_downstream = (
        float(resolved["geometry_mm"]["rod_z_min"])
        - float(sleeve_profile["downstream_rod_clearance_mm"])
    )
    if not (
        0.0 < sleeve_inner < sleeve_outer
        and sleeve_outer + insulation_gap < float(entrance["aperture_radius_mm"])
        and sleeve_upstream < float(entrance["release_plane_z_mm"]) < sleeve_downstream
    ):
        raise DownstreamTerminalError(
            "entrance reference sleeve does not enclose the release plane with insulation clearance"
        )

    base_hash = resolved["resolved_sha256"]
    resolved["terminal_composition"] = {
        "composer": COMPOSER_ID,
        "base_resolved_sha256": base_hash,
        "terminal_profile_sha256": canonical_sha256(profile),
    }
    resolved["downstream_terminal"] = {
        "terminal_profile_id": profile["terminal_profile_id"],
        "owner": profile["owner"],
        "surface_role": profile["surface_role"],
        "surface_plane_z_mm": surface_plane,
        "rod_end_clearance_mm": float(profile["rod_end_clearance_mm"]),
        "upstream_enclosure_end_plane_z_mm": upstream_end,
        "upstream_enclosure_to_terminal_clearance_mm": max(0.0, enclosure_clearance),
        "electrode_thickness_mm": float(profile["electrode_thickness_mm"]),
        "electrode_outer_shape": outer["shape"],
        "electrode_outer_width_mm": float(outer["width_mm"]),
        "electrode_outer_height_mm": float(outer["height_mm"]),
        "aperture": copy.deepcopy(aperture),
        "terminal_potential_V": terminal_potential,
        "upstream_terminal_electrode_present": profile["owner"] == "upstream",
    }
    resolved["axial_dc"] = {
        "rod_electrodes": rod_electrodes,
        "upstream_shield_potential_V": 0.0,
        "entrance_plate_potential_V": entrance_rod_potential,
        "entrance_reference_sleeve": {
            "profile_id": sleeve_profile["profile_id"],
            "role": "functional_source_reference_not_shield",
            "potential_V": entrance_rod_potential,
            "inner_radius_mm": sleeve_inner,
            "outer_radius_mm": sleeve_outer,
            "upstream_face_z_mm": sleeve_upstream,
            "downstream_face_z_mm": sleeve_downstream,
            "minimum_insulation_gap_mm": insulation_gap,
        },
        "terminal_electrode_potential_V": terminal_potential,
    }
    resolved["resolved_sha256"] = resolved_design_sha256(resolved)
    try:
        validate_schema(resolved, RESOLVED_SCHEMA)
    except ContractError as error:
        raise DownstreamTerminalError(
            f"terminal composition produced an invalid resolved design: {error}"
        ) from error
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--terminal-registry", required=True, type=Path)
    parser.add_argument("--terminal-profile-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    registry = json.loads(args.terminal_registry.read_text(encoding="utf-8-sig"))
    profile = select_downstream_terminal_profile(
        registry,
        args.terminal_profile_id,
        upstream_project_id=resolved["identity"]["project_id"],
    )
    composed = compose_downstream_terminal(resolved, profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(composed, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
