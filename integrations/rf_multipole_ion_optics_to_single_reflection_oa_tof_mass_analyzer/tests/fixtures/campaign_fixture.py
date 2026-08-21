from __future__ import annotations

# Shared campaign fixture helpers live under the fixture namespace.

import copy
from typing import Any


_SOURCE_KEYS = {
    "run_id",
    "launched_particle_count",
    "particle_source_manifest_input_role",
    "manifest",
    "state",
    "particle_source",
    "metadata",
}


def current_campaign_fixture(value: dict[str, Any]) -> dict[str, Any]:
    """Upgrade test-only campaign copies to the current derived-count contract."""
    result = copy.deepcopy(value)
    if result.get("role") != "rf_multipole_oatof_experiment_campaign":
        return result

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if _SOURCE_KEYS <= node.keys():
                node.pop("particle_count", None)
                node.setdefault(
                    "particle_count_binding",
                    {
                        "mode": "derive_from_frozen_source_state_v1",
                        "selector": {"event": "handoff", "status": "transmitted"},
                    },
                )
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(result)
    return result
