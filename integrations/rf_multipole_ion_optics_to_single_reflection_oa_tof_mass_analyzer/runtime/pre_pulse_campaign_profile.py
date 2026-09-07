"""Expand the registered pre-pulse authoring profile into effective values."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import ContractError


PROFILE_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / (
    "pre_pulse_campaign_profiles.json"
)


def _load_registry() -> dict[str, Any]:
    value = json.loads(PROFILE_REGISTRY_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError("pre-pulse campaign profile registry must be an object")
    return value


def expand_pre_pulse_campaign_profile(campaign: dict[str, Any]) -> dict[str, Any]:
    """Inject one versioned execution profile before materializing v7 rows.

    The profile is authoring convenience only. Its complete values are copied
    into the resolved campaign, while candidate/source/cohort evidence remains
    explicit in the authored campaign and cannot be hidden in a mutable preset.
    """

    profile_id = campaign.get("pre_pulse_campaign_profile_id")
    if profile_id is None:
        return copy.deepcopy(campaign)
    if not isinstance(profile_id, str) or not profile_id:
        raise ContractError("pre-pulse campaign profile ID is invalid")
    registry = _load_registry()
    if registry.get("role") != "rf_multipole_oatof_pre_pulse_campaign_profile_registry":
        raise ContractError("pre-pulse campaign profile registry role differs")
    profiles = {
        item.get("profile_id"): item
        for item in registry.get("profiles", [])
        if isinstance(item, dict) and isinstance(item.get("profile_id"), str)
    }
    if profile_id not in profiles:
        raise ContractError(f"pre-pulse campaign profile is not unique: {profile_id}")
    profile = profiles[profile_id]
    parent_id = profile.get("extends")
    if parent_id is not None:
        if not isinstance(parent_id, str) or parent_id not in profiles:
            raise ContractError("pre-pulse campaign profile parent is invalid")
        parent = profiles[parent_id]
        if parent.get("extends") is not None:
            raise ContractError("pre-pulse campaign profiles permit one inheritance level")
        overrides = profile.get("overrides")
        if (
            set(profile) != {"profile_id", "revision", "extends", "overrides"}
            or not isinstance(overrides, dict)
        ):
            raise ContractError("pre-pulse campaign profile inheritance shape differs")
        parent_defaults = parent.get("defaults")
        if not isinstance(parent_defaults, dict) or set(overrides) - {
            "campaign", "experiment_shared"
        }:
            raise ContractError("pre-pulse campaign profile inheritance defaults differ")
        profile = {
            "profile_id": profile_id,
            "defaults": {
                "campaign": {
                    **copy.deepcopy(parent_defaults.get("campaign", {})),
                    **copy.deepcopy(overrides.get("campaign", {})),
                },
                "experiment_shared": {
                    **copy.deepcopy(parent_defaults.get("experiment_shared", {})),
                    **copy.deepcopy(overrides.get("experiment_shared", {})),
                },
            },
        }
    defaults = profile.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != {
        "campaign", "experiment_shared"
    }:
        raise ContractError("pre-pulse campaign profile defaults differ")
    campaign_defaults = defaults["campaign"]
    shared_defaults = defaults["experiment_shared"]
    if not isinstance(campaign_defaults, dict) or not isinstance(shared_defaults, dict):
        raise ContractError("pre-pulse campaign profile defaults must be objects")
    result = copy.deepcopy(campaign)
    result.pop("pre_pulse_campaign_profile_id")
    for key, value in campaign_defaults.items():
        if key in result:
            raise ContractError(f"pre-pulse campaign profile duplicates authored field: {key}")
        result[key] = copy.deepcopy(value)
    experiments = result.get("experiments")
    if not isinstance(experiments, dict) or not isinstance(experiments.get("shared"), dict):
        raise ContractError("pre-pulse campaign profile requires flat experiment authoring")
    authored_shared = experiments["shared"]
    overlap = set(authored_shared).intersection(shared_defaults)
    if overlap:
        raise ContractError(
            "pre-pulse campaign profile duplicates authored shared field: "
            + ", ".join(sorted(overlap))
        )
    experiments["shared"] = {
        **copy.deepcopy(shared_defaults),
        **copy.deepcopy(authored_shared),
    }
    return result
