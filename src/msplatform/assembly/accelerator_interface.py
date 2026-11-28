"""Solver-neutral accelerator/MR provider selection and proposal construction."""
from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Mapping

PROJECT = "multi_reflection_tof"
ION_PROCESSOR = "ion_processor"
MODE = "accelerator_interface_preparation"
CONFIG = Path(str(files(f"msplatform.components.{PROJECT}"))).resolve() / "config"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_selection(path: Path, provider: str | None) -> tuple[str, dict[str, Any]]:
    """Resolve the explicit provider choice; no fallback for unknown providers."""
    registry = _read(path)
    if (registry.get("schema_version") != 1
            or registry.get("role") != "mrtof_accelerator_interface_selection"
            or registry.get("execution_scope") != "interface_preparation_only"
            or set(registry.get("providers", {})) != {"orthogonal_accelerator", ION_PROCESSOR}):
        raise ValueError("unsupported accelerator selection contract")
    selected = provider if provider is not None else registry["default_provider"]
    if selected not in registry["providers"]:
        raise ValueError(f"unknown accelerator provider: {selected}")
    return selected, registry["providers"][selected]


def build_interface_proposal(*, frozen: Mapping[str, Mapping[str, Any]],
                             selected: str) -> dict[str, Any]:
    """Build the explicit energy/frame proposal from already frozen inputs.

    The returned receipt performs no I/O, solver call, source generation, or
    flight. The caller owns freezing and publication through its execution owner.
    """
    trajectory = _read(Path(frozen["reference_trajectory"]["path"]))
    old_provider = _read(Path(frozen["reference_provider"]["path"]))
    target = {
        "axial_energy_per_charge_v": old_provider["mrtof_projection"]["target_axial_energy_per_charge_v"],
        "energy_definition": "exit_axial_kinetic_energy_per_charge",
        "project_y_mm": trajectory["accelerator"]["focus_y_anchor"]["project_y_mm"],
        "frame_id": trajectory["coordinate_system"]["frame_id"],
        "source": "manifest_bound_frozen_reference_not_live_candidate_defaults",
    }
    return {
        "schema_version": 1, "role": "mrtof_accelerator_interface_preparation",
        "status": "prepared", "selected_provider": selected,
        "solver_executed": False, "joint_simulation_executed": False,
        "reference_requirements": target,
        "inputs": dict(frozen),
        "next_action": "author_original_birth_simulation_recipe",
        "limitations": [
            "Reference energy is an MR matching demand; component poses come only from the explicit frozen assembly recipe.",
            "The demand is a proposal; author physical geometry, drive and original births explicitly in the public Assembly and SimulationRecipe.",
            "No component source, field, flight or time-focus qualification is produced.",
        ],
    }
