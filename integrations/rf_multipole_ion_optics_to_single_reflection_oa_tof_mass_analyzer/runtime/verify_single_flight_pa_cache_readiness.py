"""Read-only readiness check for the 300 mm accelerator aperture-scan PA cache.

The checker deliberately reads only cache pointers, JSON receipts, and directory
member names.  It does not hash, open, or invoke SIMION on PA payloads.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_execution_profile import (
    resolve_execution_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pre_pulse_campaign_profile import (
    expand_pre_pulse_campaign_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    resolve_three_zone_pa_plus_solution_model,
)


MAIN_ROLE = "simion_single_flight_accelerator_main_pa_cache"
LOCAL_ROLE = "simion_single_flight_accelerator_entrance_local_pa_cache"
FORBIDDEN_OVERLAY_ROLE = "simion_single_flight_accelerator_intermediate_overlay_pa_cache"
MAIN_PREFIX = "accelerator_main"
LOCAL_PREFIX = "accelerator_entrance_local"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED path={path}")
    return value


def _number_pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        return float(value["width"]), float(value["height"])
    except (KeyError, TypeError, ValueError):
        return None


def _number_triplet(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        numbers = tuple(float(value[axis]) for axis in ("x", "y", "z"))
    except (KeyError, TypeError, ValueError):
        return None
    return numbers if all(math.isfinite(number) and number > 0 for number in numbers) else None


def _normalized_json(value: Any) -> Any | None:
    """Return a hashable exact JSON value, rejecting non-finite numerics."""

    if value is None or isinstance(value, str) or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    if isinstance(value, list):
        values = tuple(_normalized_json(item) for item in value)
        return values if all(item is not None for item in values) else None
    if isinstance(value, dict):
        values = tuple(
            (key, _normalized_json(item))
            for key, item in sorted(value.items())
            if isinstance(key, str)
        )
        return values if len(values) == len(value) and all(item is not None for _, item in values) else None
    return None


@dataclass(frozen=True)
class MainIdentity:
    shape: str
    cell_mm_xyz: tuple[float, float, float]
    domain_policy: Any
    reference_aperture_mm: tuple[float, float]


@dataclass(frozen=True)
class Generation:
    cache_key: str
    role: str
    root: Path
    manifest: dict[str, Any]

    @property
    def identity(self) -> dict[str, Any]:
        value = self.manifest.get("identity")
        return value if isinstance(value, dict) else {}

    @property
    def members(self) -> set[str]:
        files = self.manifest.get("files")
        if not isinstance(files, list):
            return set()
        return {
            item["name"]
            for item in files
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }


def _discover_generations(cache_root: Path) -> tuple[list[Generation], list[str]]:
    generations: list[Generation] = []
    warnings: list[str] = []
    if not cache_root.is_dir():
        return generations, [f"CACHE_ROOT_MISSING path={cache_root}"]
    for role_root in sorted(cache_root.iterdir()):
        if not role_root.is_dir():
            continue
        for entry in sorted(role_root.iterdir()):
            pointer_path = entry / "current_generation.json"
            if not entry.is_dir() or not pointer_path.is_file():
                continue
            try:
                pointer = _read_json(pointer_path)
                generation = pointer.get("generation_sha256")
                relative = pointer.get("generation_relative_path")
                if (
                    pointer.get("cache_key") != entry.name
                    or not isinstance(generation, str)
                    or relative != f"generations/{generation}"
                ):
                    raise ValueError("CURRENT_POINTER_INVALID")
                manifest_path = entry / relative / "cache_manifest.json"
                manifest = _read_json(manifest_path)
                role = manifest.get("role")
                if manifest.get("cache_key") != entry.name or not isinstance(role, str):
                    raise ValueError("GENERATION_MANIFEST_INVALID")
                generations.append(Generation(entry.name, role, manifest_path.parent, manifest))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"CACHE_GENERATION_UNUSABLE path={entry} reason={exc}")
    return generations, warnings


def _provider_contract(generation: Generation, runs_root: Path, name: str) -> dict[str, Any] | None:
    run_id = generation.manifest.get("provider_run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    path = runs_root / run_id / "inputs" / name
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _shape_from_contract(contract: dict[str, Any] | None) -> str | None:
    if not isinstance(contract, dict):
        return None
    value = contract.get("cross_section")
    return value if value in {"square", "cylindrical"} else None


def _published_mode_model(generation: Generation) -> dict[str, Any] | None:
    options = generation.identity.get("critical_options")
    model = options.get("pa_plus_solution_model") if isinstance(options, dict) else None
    return model if isinstance(model, dict) else None


def _mode_ids(model: dict[str, Any] | None) -> tuple[int, ...] | None:
    if model is None:
        return None
    values = model.get("mode_ids") if isinstance(model, dict) else None
    if not isinstance(values, list) or not values:
        return None
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return None
    mode_ids = tuple(values)
    return mode_ids if len(set(mode_ids)) == len(mode_ids) else None


def _expected_mode_model(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    """Rebuild the active PA+ model from the provider's physical contract."""

    if not isinstance(contract, dict):
        return None
    ring_placement = contract.get("ring_placement")
    embedded = contract.get("pa_plus_solution_model")
    if not isinstance(ring_placement, dict) or not isinstance(embedded, dict):
        return None
    try:
        expected = resolve_three_zone_pa_plus_solution_model(
            contract["electrodes"],
            planes_global_z_mm=contract["axial_planes_global_z_mm"],
            ring_z_mm=ring_placement["ring_z_mm"],
        )
    except (KeyError, TypeError, ValueError):
        return None
    # The provider contract and cache identity must both describe the model
    # derived by the active electrode authority.  This leaves older complete
    # families readable in cache without making them candidates for a new run.
    return expected if embedded == expected else None


def _has_required_family(
    generation: Generation, prefix: str, mode_ids: tuple[int, ...]
) -> bool:
    required = {f"{prefix}.pa#", f"{prefix}.pa+", f"{prefix}.pa0"}
    required.update(f"{prefix}.pa{mode}" for mode in mode_ids)
    return required <= generation.members and all(
        (generation.root / name).is_file() for name in required
    )


def _main_identity_from_contract(contract: dict[str, Any] | None) -> MainIdentity | None:
    if not isinstance(contract, dict):
        return None
    aperture = contract.get("accelerator_port_aperture")
    reference = _number_pair(
        aperture.get("reference_aperture_mm") if isinstance(aperture, dict) else None
    )
    domain_policy = _normalized_json(contract.get("domain_policy"))
    shape = _shape_from_contract(contract)
    cell = _number_triplet(contract.get("cell_mm_xyz"))
    if None in (shape, cell, domain_policy, reference):
        return None
    assert shape is not None and cell is not None and reference is not None
    return MainIdentity(shape, cell, domain_policy, reference)


def _expected_main_identity(
    configuration: dict[str, Any], shape: str, frontend_grid_profile_id: Any
) -> MainIdentity | None:
    if not isinstance(frontend_grid_profile_id, str):
        return None
    try:
        resolved = resolve_execution_profile(
            configuration, frontend_grid_profile_id=frontend_grid_profile_id
        )
    except ValueError:
        return None
    cell = _number_triplet(resolved.get("accelerator_main_cell_mm_xyz"))
    domain_policy = _normalized_json(resolved.get("accelerator_main_domain"))
    reference = _number_pair(resolved.get("accelerator_main_reference_aperture_mm"))
    if cell is None or domain_policy is None or reference is None:
        return None
    return MainIdentity(shape, cell, domain_policy, reference)


def _campaign_expectations(
    campaign: dict[str, Any], layouts: dict[str, Any], configuration: dict[str, Any]
) -> tuple[list[tuple[MainIdentity, tuple[float, float]]], list[str]]:
    warnings: list[str] = []
    experiments = campaign.get("experiments")
    rows = experiments.get("rows") if isinstance(experiments, dict) else None
    if not isinstance(rows, list):
        return [], ["CAMPAIGN_ROWS_MISSING"]
    shared = experiments.get("shared") if isinstance(experiments, dict) else None
    if not isinstance(shared, dict):
        return [], ["CAMPAIGN_SHARED_EXECUTION_CONFIGURATION_MISSING"]
    row_values = [
        row.get("values")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("values"), dict)
    ]
    declared_profiles = [
        {**shared, **values}.get("single_flight_frontend_grid_profile_id")
        for values in row_values
    ]
    if len(row_values) != len(rows) or any(
        not isinstance(profile_id, str) or not profile_id
        for profile_id in declared_profiles
    ):
        return [], ["FIELD_BEARING_EXECUTION_PROFILE_MISSING"]
    expected: list[tuple[MainIdentity, tuple[float, float]]] = []
    for row in rows:
        values = row.get("values") if isinstance(row, dict) else None
        if not isinstance(values, dict):
            warnings.append("CAMPAIGN_ROW_INVALID")
            continue
        layout = layouts.get(values.get("single_flight_layout_profile_id"))
        realization = layout.get("accelerator_realization_id") if isinstance(layout, dict) else None
        shape = {"square_3d": "square", "cylindrical_3d": "cylindrical"}.get(realization)
        aperture = _number_pair(values.get("accelerator_entrance_local_aperture_mm"))
        effective = {**shared, **values}
        main_identity = (
            None
            if shape is None
            else _expected_main_identity(
                configuration,
                shape,
                effective.get("single_flight_frontend_grid_profile_id"),
            )
        )
        if main_identity is None or aperture is None:
            warnings.append(f"CAMPAIGN_ROW_UNRESOLVED id={row.get('experiment_id')}")
            continue
        expected.append((main_identity, aperture))
    if len(expected) != 8 or len(set(expected)) != 8:
        warnings.append("CAMPAIGN_NOT_EIGHT_UNIQUE_SHAPE_APERTURE_ROWS")
    return expected, warnings


def verify_readiness(
    campaign_path: Path,
    layout_path: Path,
    cache_root: Path,
    single_flight_configuration_path: Path,
) -> dict[str, Any]:
    """Return a warning-bearing readiness receipt; never raises for a cache miss."""

    warnings: list[str] = []
    try:
        campaign = expand_pre_pulse_campaign_profile(_read_json(campaign_path))
        layout_document = _read_json(layout_path)
        configuration = _read_json(single_flight_configuration_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "WARN", "warnings": [f"CONFIGURATION_UNUSABLE reason={exc}"], "rows": []}
    profiles = layout_document.get("profiles")
    layouts = {
        item.get("layout_profile_id"): item
        for item in profiles if isinstance(item, dict) and isinstance(item.get("layout_profile_id"), str)
    } if isinstance(profiles, list) else {}
    expected, campaign_warnings = _campaign_expectations(campaign, layouts, configuration)
    warnings.extend(campaign_warnings)
    if any(
        warning.startswith("FIELD_BEARING_EXECUTION_PROFILE_MISSING")
        for warning in warnings
    ):
        return {"status": "WARN", "warnings": warnings, "rows": []}
    generations, cache_warnings = _discover_generations(cache_root)
    warnings.extend(cache_warnings)
    runs_root = cache_root.parent / "runs"

    mains = [item for item in generations if item.role == MAIN_ROLE]
    locals_ = [item for item in generations if item.role == LOCAL_ROLE]
    forbidden = [item for item in generations if item.role == FORBIDDEN_OVERLAY_ROLE]
    if forbidden:
        warnings.append("INTERMEDIATE2_OVERLAY_CACHE_PRESENT")

    main_by_identity: dict[MainIdentity, list[Generation]] = {}
    for main in mains:
        contract = _provider_contract(main, runs_root, "accelerator_main_contract.json")
        main_identity = _main_identity_from_contract(contract)
        if main_identity is None:
            continue
        expected_model = _expected_mode_model(contract)
        if _published_mode_model(main) != expected_model:
            continue
        mode_ids = _mode_ids(expected_model)
        if mode_ids is None:
            continue
        if not _has_required_family(main, MAIN_PREFIX, mode_ids):
            continue
        main_by_identity.setdefault(main_identity, []).append(main)

    selected_main: dict[MainIdentity, Generation] = {}
    for main_identity in sorted(set(identity for identity, _ in expected), key=repr):
        candidates = main_by_identity.get(main_identity, [])
        if len(candidates) != 1:
            warnings.append(
                "MAIN_CACHE_COUNT_INVALID "
                f"shape={main_identity.shape} count={len(candidates)}"
            )
        else:
            selected_main[main_identity] = candidates[0]

    rows: list[dict[str, Any]] = []
    for main_identity, aperture in expected:
        shape = main_identity.shape
        main = selected_main.get(main_identity)
        matching: list[Generation] = []
        for local in locals_:
            contract = _provider_contract(local, runs_root, "accelerator_entrance_local_contract.json")
            if _shape_from_contract(contract) != shape:
                continue
            observed = _number_pair(
                contract.get("accelerator_port_aperture", {}).get("mechanical_aperture_mm")
                if isinstance(contract, dict) and isinstance(contract.get("accelerator_port_aperture"), dict)
                else None
            )
            parent = local.identity.get("inputs", {}).get("accelerator_main_cache_key") if isinstance(local.identity.get("inputs"), dict) else None
            replacement = local.identity.get("critical_options", {}).get("replacement_semantics") if isinstance(local.identity.get("critical_options"), dict) else None
            boundary = local.identity.get("critical_options", {}).get("boundary_mode") if isinstance(local.identity.get("critical_options"), dict) else None
            main_mode_model = _published_mode_model(main) if main is not None else None
            main_mode_ids = _mode_ids(main_mode_model)
            if observed == aperture and main is not None and parent == main.cache_key and replacement == "highest_priority_complete_local_replacement_v1" and boundary == "accelerator_main_electrode_basis_dirichlet_v1" and _published_mode_model(local) == main_mode_model and main_mode_ids is not None and _has_required_family(local, LOCAL_PREFIX, main_mode_ids):
                matching.append(local)
        ready = len(matching) == 1
        if not ready:
            warnings.append(f"LOCAL_CACHE_COUNT_INVALID shape={shape} aperture={aperture[0]}x{aperture[1]} count={len(matching)}")
        rows.append({"shape": shape, "aperture_mm": {"width": aperture[0], "height": aperture[1]}, "main_cache_key": None if main is None else main.cache_key, "local_cache_key": matching[0].cache_key if ready else None, "ready": ready})
    return {"status": "PASS" if not warnings else "WARN", "warnings": warnings, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--layout-profiles", required=True, type=Path)
    parser.add_argument("--single-flight-configuration", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    receipt = verify_readiness(
        args.campaign,
        args.layout_profiles,
        args.cache_root,
        args.single_flight_configuration,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    if args.require_ready and receipt["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
