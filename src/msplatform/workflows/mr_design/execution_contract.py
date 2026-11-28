"""Validate recorded-joint analysis and bounded-controller contract changes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_execution_contract(reference: dict[str, Any], contract: dict[str, Any], *,
                                allow_controller_budget: bool = False) -> dict[str, Any]:
    """Allow observation changes and one selected integration bound, never physics."""
    expected = json.loads(json.dumps(reference))
    scientific = json.loads(json.dumps(contract))
    expected["simion"].pop("trajectory_recording", None)
    scientific["simion"].pop("trajectory_recording", None)
    from msplatform.analysis.joint_analysis_contract import reference_changes
    changes = reference_changes(expected, scientific, contract_base=Path.cwd())
    budget = None
    if scientific != expected:
        if not allow_controller_budget:
            raise ValueError("Finalization contract changes more than the selected trajectory step")
        from msplatform.workflows.mr_design.downstream_workpoint import assert_bounded_controller_resume
        budget = assert_bounded_controller_resume(expected, scientific, None, budget_only=True)
    return dict(reference_profile=changes["reference_profile"], selected_profile=changes["selected_profile"],
                numerical_change=changes["numerical_change"], execution_budget_change=budget,
                analysis_change=changes["analysis_change"], native_refine_change=changes["native_refine_change"])
