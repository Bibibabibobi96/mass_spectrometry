"""Resolve and execute one stage of the oaTOF three-zone theory funnel.

This module is deliberately solver-free and single-stage.  It validates frozen
campaign authorities, expands deterministic rows, verifies predecessor receipts,
and emits hash-bound plan/report/receipt documents.  It never runs SIMION, COMSOL,
or CAD and it never promotes project lifecycle state.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.experiment_campaign import (
    _canonical_sha as canonical_sha256,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    compute_time_derivatives,
    derive_three_zone_state,
    exact_total_normalized_time,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_theory_numeric_execution import (
    execute_numeric_stage,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN_SCHEMA = "oatof_three_zone_solver_free_funnel.schema.json"
PLAN_SCHEMA = "oatof_three_zone_resolved_plan.schema.json"
REPORT_SCHEMA = "oatof_three_zone_stage_report.schema.json"
RECEIPT_SCHEMA = "oatof_three_zone_stage_receipt.schema.json"
STAGE_ORDER = ("T0", "T1", "T2", "G1", "T3", "T4a", "T4b", "T4c", "G2", "T5")


def _content_sha256(document: Mapping[str, Any], identity_field: str) -> str:
    payload = {key: value for key, value in document.items() if key != identity_field}
    return canonical_sha256(payload)


def _bound_file(root: Path, record: Mapping[str, Any], label: str) -> Path:
    path = (root / str(record["path"])).resolve()
    if not path.is_file():
        raise ValueError(f"{label} authority is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} authority byte count differs")
    if file_sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{label} authority SHA-256 differs")
    return path


def load_campaign(
    campaign_path: Path, *, repository_root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    """Load a campaign and fail closed on schema or authority drift."""

    campaign = load_json(campaign_path)
    validate_schema(campaign, CAMPAIGN_SCHEMA)
    if campaign["status"] != "authorized":
        raise ValueError("three-zone theory campaign is not an authorized execution contract")
    if campaign["stage_execution_mode"] != "single_stage_only":
        raise ValueError("three-zone theory campaign must remain single-stage-only")
    if campaign["solver_execution_allowed"]:
        raise ValueError("solver execution cannot be enabled in this workflow")
    for label, record in campaign["authorities"].items():
        _bound_file(repository_root, record, label)
    return campaign


def _decimal_grid(specification: Mapping[str, float]) -> list[float]:
    minimum = float(specification["minimum"])
    maximum = float(specification["maximum"])
    step = float(specification["step"])
    count = round((maximum - minimum) / step) + 1
    values = [minimum + index * step for index in range(count)]
    if not math.isclose(values[-1], maximum, rel_tol=0.0, abs_tol=1.0e-10):
        raise ValueError("grid does not close exactly at its declared maximum")
    return [round(value, 12) for value in values]


def _row(
    sequence: int,
    row_id: str,
    arm_role: str,
    outer: Mapping[str, float | None],
    solve_variables: Sequence[str],
    solve_targets: Sequence[str],
    *,
    scientific_gate_eligible: bool = True,
    scope: str = "frozen_domain",
    matched_control_row_id: str | None = None,
) -> dict[str, Any]:
    row = {
        "sequence": sequence,
        "row_id": row_id,
        "row_sha256": "0" * 64,
        "arm_role": arm_role,
        "scientific_gate_eligible": scientific_gate_eligible,
        "scope": scope,
        "outer": dict(outer),
        "solve_variables": list(solve_variables),
        "solve_targets": list(solve_targets),
        "matched_control_row_id": matched_control_row_id,
    }
    row["row_sha256"] = _content_sha256(row, "row_sha256")
    return row


def _outer(d1: float, l23: float, split: float, drop: float) -> dict[str, float]:
    return {"d1_mm": d1, "l23_mm": l23, "lambda": split, "delta_v1_v": drop}


def _baseline_row(campaign: Mapping[str, Any], sequence: int) -> dict[str, Any]:
    fixture = campaign["fixtures"]["current_exact_baseline"]
    return _row(
        sequence,
        "current_exact_baseline",
        "current_exact_baseline",
        fixture["outer"],
        ("u_r1", "f_r2"),
        ("d1", "d2"),
        scientific_gate_eligible=False,
        scope="extrapolation_only",
    )


def _t1_rows(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    anchor = campaign["fixtures"]["low_contrast_anchor"]["outer"]
    rows = []
    for index, fixture_id in enumerate(campaign["stage_design"]["T1"]["formula_fixtures"], 1):
        rows.append(
            _row(
                index,
                fixture_id,
                "formula_fixture",
                anchor,
                (),
                (),
                scope="identity_only",
            )
        )
    return rows


def _t2_rows(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    domain = campaign["theory_domain"]
    rows = []
    for index, values in enumerate(
        itertools.product(
            _decimal_grid(domain["d1_mm"]),
            _decimal_grid(domain["l23_mm"]),
            _decimal_grid(domain["delta_v1_v"]),
        ),
        1,
    ):
        d1, l23, drop = values
        rows.append(
            _row(
                index,
                f"t2_two_zone_{index:04d}",
                "two_zone_benchmark",
                _outer(d1, l23, 0.5, drop),
                ("u_r1", "f_r2"),
                ("d1", "d2"),
            )
        )
    rows.append(_baseline_row(campaign, len(rows) + 1))
    return rows


def _t3_rows(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    design = campaign["stage_design"]["T3"]
    triples = list(
        itertools.product(
            design["d1_values_mm"], design["l23_values_mm"], design["delta_v1_values_v"]
        )
    )
    control_ids = {
        triple: f"t3_control_{index:02d}" for index, triple in enumerate(triples, 1)
    }
    rows = []
    for values in itertools.product(
        design["d1_values_mm"],
        design["l23_values_mm"],
        design["delta_v1_values_v"],
        design["lambda_values"],
    ):
        d1, l23, drop, split = values
        matched = control_ids[(d1, l23, drop)]
        rows.append(
            _row(
                len(rows) + 1,
                f"t3_three_zone_{len(rows) + 1:02d}",
                "three_zone_screen",
                _outer(d1, l23, split, drop),
                ("eta", "u_r1", "f_r2"),
                ("d1", "d2", "d3"),
                matched_control_row_id=matched,
            )
        )
    for d1, l23, drop in triples:
        rows.append(
            _row(
                len(rows) + 1,
                control_ids[(d1, l23, drop)],
                "paired_two_zone_control",
                _outer(d1, l23, 0.5, drop),
                ("u_r1", "f_r2"),
                ("d1", "d2"),
            )
        )
    rows.append(_baseline_row(campaign, len(rows) + 1))
    return rows


def _grid_rows(
    axes: Sequence[Sequence[float]], arm_role: str, prefix: str
) -> list[dict[str, Any]]:
    rows = []
    for index, (d1, l23, drop, split) in enumerate(itertools.product(*axes), 1):
        rows.append(
            _row(
                index,
                f"{prefix}_{index:05d}",
                arm_role,
                _outer(float(d1), float(l23), float(split), float(drop)),
                ("eta", "u_r1", "f_r2"),
                ("d1", "d2", "d3"),
            )
        )
    return rows


def _t4a_rows(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    design = campaign["stage_design"]["T4a"]
    return _grid_rows(
        (
            design["d1_values_mm"],
            design["l23_values_mm"],
            design["delta_v1_values_v"],
            design["lambda_values"],
        ),
        "three_zone_discovery",
        "t4a_discovery",
    )


def _t4c_rows(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    domain = campaign["theory_domain"]
    return _grid_rows(
        (
            _decimal_grid(domain["d1_mm"]),
            _decimal_grid(domain["l23_mm"]),
            _decimal_grid(domain["delta_v1_v"]),
            _decimal_grid(domain["lambda"]),
        ),
        "three_zone_discovery",
        "t4c_discovery",
    )


def _t5_rows(
    campaign: Mapping[str, Any], predecessor: Mapping[str, Any]
) -> list[dict[str, Any]]:
    primary = predecessor.get("frozen_primary")
    benchmark = predecessor.get("best_feasible_two_zone")
    if primary is None or benchmark is None:
        raise ValueError("T5 requires frozen_primary and best_feasible_two_zone")
    control_id = "t5_same_primary_two_zone_control"
    return [
        _row(
            1,
            "t5_frozen_primary",
            "three_zone_confirmation",
            primary,
            ("eta", "u_r1", "f_r2"),
            ("d1", "d2", "d3"),
            matched_control_row_id=control_id,
        ),
        _row(
            2,
            "t5_best_feasible_two_zone",
            "two_zone_benchmark",
            benchmark,
            ("u_r1", "f_r2"),
            ("d1", "d2"),
        ),
        _row(
            3,
            control_id,
            "paired_two_zone_control",
            primary,
            ("u_r1", "f_r2"),
            ("d1", "d2"),
        ),
        _baseline_row(campaign, 4),
    ]


def _t4b_rows(campaign: Mapping[str, Any], predecessor: Mapping[str, Any]) -> list[dict[str, Any]]:
    design = campaign["stage_design"]["T4b"]
    selected = predecessor.get("selected_outer_points", [])
    if not 1 <= len(selected) <= int(design["top_k"]):
        raise ValueError("T4b requires one to top_k predecessor-selected outer points")
    domain = campaign["theory_domain"]
    candidates: set[tuple[float, float, float, float]] = set()
    offsets = design["offset_multipliers"]
    steps = design["full_domain_steps"]
    for point in selected:
        for multipliers in itertools.product(offsets, repeat=4):
            values = (
                float(point["d1_mm"]) + multipliers[0] * steps["d1_mm"],
                float(point["l23_mm"]) + multipliers[1] * steps["l23_mm"],
                float(point["delta_v1_v"]) + multipliers[2] * steps["delta_v1_v"],
                float(point["lambda"]) + multipliers[3] * steps["lambda"],
            )
            checks = zip(values, (domain["d1_mm"], domain["l23_mm"], domain["delta_v1_v"], domain["lambda"]), strict=True)
            if all(float(spec["minimum"]) <= value <= float(spec["maximum"]) for value, spec in checks):
                candidates.add(tuple(round(value, 12) for value in values))
    axes = sorted(candidates)
    return [
        _row(
            index,
            f"t4b_refinement_{index:04d}",
            "three_zone_discovery",
            _outer(d1, l23, split, drop),
            ("eta", "u_r1", "f_r2"),
            ("d1", "d2", "d3"),
        )
        for index, (d1, l23, drop, split) in enumerate(axes, 1)
    ]


def _receipt_reference(path: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "stage_id": receipt["stage_id"],
        "conclusion": receipt["conclusion"],
        "next_stage_authorized": True,
    }


def _load_predecessor(
    path: Path | None, campaign: Mapping[str, Any], stage_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    stage = next(item for item in campaign["stages"] if item["stage_id"] == stage_id)
    allowed = set(stage["allowed_predecessors"])
    if not allowed:
        if path is not None:
            raise ValueError(f"{stage_id} does not accept a predecessor")
        return None, None
    if path is None:
        raise ValueError(f"{stage_id} requires a predecessor receipt")
    receipt = load_json(path)
    validate_schema(receipt, RECEIPT_SCHEMA)
    if receipt["campaign_id"] != campaign["campaign_id"]:
        raise ValueError("predecessor campaign identity differs")
    if receipt["stage_id"] not in allowed:
        raise ValueError("predecessor stage is not allowed")
    if receipt["status"] != "success" or not receipt["next_stage_authorized"]:
        raise ValueError("predecessor receipt did not authorize continuation")
    required_conclusion = campaign["stage_design"].get(stage_id, {}).get("authorization_conclusion")
    if required_conclusion and receipt["conclusion"] != required_conclusion:
        raise ValueError(f"{stage_id} requires predecessor conclusion {required_conclusion}")
    if stage_id == "T3" and receipt["conclusion"] != "G1_AUTHORIZE_THIRD_DIRECTION_TEST":
        raise ValueError("T3 requires explicit G1 third-direction authorization")
    if stage_id == "T5" and receipt["stage_id"] == "G2" and receipt["conclusion"] != "G2_PRIMARY_FROZEN":
        raise ValueError("T5 after G2 requires a frozen-primary conclusion")
    return receipt, _receipt_reference(path, receipt)


def resolve_stage_plan(
    campaign_path: Path,
    stage_id: str,
    *,
    predecessor_receipt_path: Path | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Resolve one deterministic stage plan and bind every row by SHA-256."""

    if stage_id not in STAGE_ORDER:
        raise ValueError(f"unknown stage_id {stage_id!r}")
    campaign = load_campaign(campaign_path, repository_root=repository_root)
    predecessor, predecessor_reference = _load_predecessor(
        predecessor_receipt_path, campaign, stage_id
    )
    if stage_id in {"T0", "G1", "G2"}:
        rows: list[dict[str, Any]] = []
    elif stage_id == "T1":
        rows = _t1_rows(campaign)
    elif stage_id == "T2":
        rows = _t2_rows(campaign)
    elif stage_id == "T3":
        rows = _t3_rows(campaign)
    elif stage_id == "T4a":
        rows = _t4a_rows(campaign)
    elif stage_id == "T4b":
        if predecessor is None:
            raise ValueError("T4b predecessor is missing")
        rows = _t4b_rows(campaign, predecessor)
    elif stage_id == "T4c":
        rows = _t4c_rows(campaign)
    elif stage_id == "T5":
        if predecessor is None:
            raise ValueError("T5 predecessor is missing")
        rows = _t5_rows(campaign, predecessor)
    else:
        raise AssertionError("unhandled stage")
    expected = campaign["stage_design"].get(stage_id, {}).get("expected_rows")
    if expected is not None and len(rows) != int(expected):
        raise ValueError(f"{stage_id} row count {len(rows)} differs from {expected}")
    plan = {
        "schema_version": 1,
        "role": "oatof_three_zone_resolved_stage_plan",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": file_sha256(campaign_path),
        "stage_id": stage_id,
        "plan_sha256": "0" * 64,
        "assessment_design_status": campaign["assessment_design_status"],
        "solver_execution_allowed": False,
        "automatic_retry_count": 0,
        "predecessor": predecessor_reference,
        "manual_gate": (
            predecessor_reference
            if predecessor is not None and predecessor["stage_id"] in {"G1", "G2"}
            else None
        ),
        "authorities": campaign["authorities"],
        "parameters": {
            "frozen_source": campaign["frozen_source"],
            "reflectron_geometry": campaign["reflectron_geometry"],
            "physics_limits": campaign["physics_limits"],
            "root_policy": campaign["root_policy"],
            "sampling_policy": campaign["sampling_policy"],
            "scientific_gates": campaign["scientific_gates"],
        },
        "rows": rows,
        "claim_limit": campaign["claim_limit"],
    }
    plan["plan_sha256"] = _content_sha256(plan, "plan_sha256")
    validate_schema(plan, PLAN_SCHEMA)
    return plan


def verify_resolved_plan(plan: Mapping[str, Any]) -> None:
    """Validate plan schema and all self-contained content identities."""

    validate_schema(plan, PLAN_SCHEMA)
    if _content_sha256(plan, "plan_sha256") != plan["plan_sha256"]:
        raise ValueError("resolved plan content SHA-256 differs")
    for sequence, row in enumerate(plan["rows"], 1):
        if row["sequence"] != sequence:
            raise ValueError("resolved plan row sequence is not contiguous")
        if _content_sha256(row, "row_sha256") != row["row_sha256"]:
            raise ValueError(f"row SHA-256 differs for {row['row_id']}")


def _source(campaign: Mapping[str, Any]) -> AffineSource:
    frozen = campaign["frozen_source"]
    if int(frozen["charge_sign"]) != 1:
        raise ValueError("v1 theory campaign requires positive unit charge")
    return AffineSource.from_velocity(
        mass_to_charge_th=frozen["mass_to_charge_th"],
        center_x_mm=frozen["center_x_mm"],
        center_velocity_m_per_s=frozen["center_velocity_m_per_s"],
        velocity_slope_m_per_s_per_mm=frozen["velocity_slope_m_per_s_per_mm"],
    )


def _reflectron(campaign: Mapping[str, Any]) -> ReflectronGeometry:
    return ReflectronGeometry(**campaign["reflectron_geometry"])


def _outer_model(campaign: Mapping[str, Any], values: Mapping[str, float]) -> OuterGeometry:
    return OuterGeometry(
        zone1_length_mm=values["d1_mm"],
        downstream_length_mm=values["l23_mm"],
        split_fraction=values["lambda"],
        zone1_voltage_drop_v=values["delta_v1_v"],
        nominal_energy_per_charge_v=campaign["frozen_source"]["nominal_energy_per_charge_v"],
    )


def _execute_t1(campaign: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    source = _source(campaign)
    reflectron = _reflectron(campaign)
    fixture = campaign["fixtures"]["low_contrast_anchor"]
    outer = _outer_model(campaign, fixture["outer"])
    inner = InnerSolution(
        stage1_voltage_drop_v=fixture["inner"]["u_r1_v"],
        stage2_field_v_per_mm=fixture["inner"]["f_r2_v_per_mm"],
        eta=fixture["inner"]["eta"],
    )
    state = derive_three_zone_state(source, outer, inner.eta)
    derivatives = compute_time_derivatives(source, state, reflectron, inner)
    observed = {
        "focus_drift_after_exit_mm": derivatives.focus_drift_after_exit_mm,
        "field1_v_per_mm": state.field1_v_per_mm,
        "field2_v_per_mm": state.field2_v_per_mm,
        "field3_v_per_mm": state.field3_v_per_mm,
        "field_ratio_2_over_3": state.field_ratio_2_over_3,
        "accelerator_field_contrast": max(
            state.field_ratio_2_over_3, 1.0 / state.field_ratio_2_over_3
        ),
    }
    tolerance = float(campaign["scientific_gates"]["eta_zero_oracle_relative_tolerance"])
    fixture_passed = all(
        math.isclose(observed[name], expected, rel_tol=tolerance, abs_tol=tolerance)
        for name, expected in fixture["expected"].items()
    )
    derivative_observed = {
        "d1": derivatives.d1,
        "d2": derivatives.d2,
        "d3": derivatives.d3,
        "d4": derivatives.d4,
    }
    derivative_fixture_passed = all(
        math.isclose(
            derivative_observed[name],
            expected,
            rel_tol=tolerance,
            abs_tol=tolerance,
        )
        for name, expected in fixture["expected_derivatives"].items()
    )
    eta_zero_inner = InnerSolution(
        stage1_voltage_drop_v=inner.stage1_voltage_drop_v,
        stage2_field_v_per_mm=inner.stage2_field_v_per_mm,
        eta=0.0,
    )
    left_outer = OuterGeometry(
        outer.zone1_length_mm,
        outer.downstream_length_mm,
        0.3,
        outer.zone1_voltage_drop_v,
        outer.nominal_energy_per_charge_v,
    )
    right_outer = OuterGeometry(
        outer.zone1_length_mm,
        outer.downstream_length_mm,
        0.7,
        outer.zone1_voltage_drop_v,
        outer.nominal_energy_per_charge_v,
    )
    left_state = derive_three_zone_state(source, left_outer, 0.0)
    right_state = derive_three_zone_state(source, right_outer, 0.0)
    left_derivative = compute_time_derivatives(source, left_state, reflectron, eta_zero_inner)
    right_derivative = compute_time_derivatives(source, right_state, reflectron, eta_zero_inner)
    positions = np.linspace(source.center_x_mm - 1.1, source.center_x_mm + 1.1, 101)
    left_time = exact_total_normalized_time(
        source, left_state, reflectron, eta_zero_inner, positions,
        left_derivative.focus_drift_after_exit_mm,
    )
    right_time = exact_total_normalized_time(
        source, right_state, reflectron, eta_zero_inner, positions,
        right_derivative.focus_drift_after_exit_mm,
    )
    eta_zero_error = float(np.max(np.abs(np.asarray(left_time) - np.asarray(right_time))))
    eta_zero_passed = eta_zero_error <= tolerance
    focus_policy_passed = math.isclose(
        reflectron.upstream_drift_mm + derivatives.focus_drift_after_exit_mm,
        642.7426154615485,
        rel_tol=0.0,
        abs_tol=1.0e-10,
    )
    passed = (
        fixture_passed
        and derivative_fixture_passed
        and eta_zero_passed
        and focus_policy_passed
    )
    return passed, {
        "fixture_expected": fixture["expected"],
        "fixture_observed": observed,
        "derivative_fixture_expected": fixture["expected_derivatives"],
        "derivative_fixture_observed": derivative_observed,
        "analytic_derivatives": asdict(derivatives),
        "eta_zero_max_pointwise_normalized_time_error": eta_zero_error,
        "focus_to_reflectron_mm": reflectron.upstream_drift_mm,
        "exit_to_reflectron_mm": reflectron.upstream_drift_mm
        + derivatives.focus_drift_after_exit_mm,
        "fixture_passed": fixture_passed,
        "derivative_fixture_passed": derivative_fixture_passed,
        "eta_zero_passed": eta_zero_passed,
        "focus_translation_policy_passed": focus_policy_passed,
    }


def _bound_predecessor_document(plan: Mapping[str, Any]) -> dict[str, Any] | None:
    reference = plan.get("predecessor")
    if reference is None:
        return None
    path = Path(str(reference["path"]))
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise ValueError("predecessor receipt changed after plan resolution")
    receipt = load_json(path)
    validate_schema(receipt, RECEIPT_SCHEMA)
    if receipt["stage_id"] != reference["stage_id"]:
        raise ValueError("predecessor receipt stage identity differs")
    if receipt["conclusion"] != reference["conclusion"]:
        raise ValueError("predecessor receipt conclusion differs")
    return receipt


def execute_stage(
    campaign_path: Path,
    plan: Mapping[str, Any],
    output_dir: Path,
    *,
    manual_conclusion: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute one supported stage and atomically publish report then receipt."""

    verify_resolved_plan(plan)
    campaign = load_campaign(campaign_path)
    if file_sha256(campaign_path) != plan["campaign_sha256"]:
        raise ValueError("campaign changed after plan resolution")
    stage_id = str(plan["stage_id"])
    stage_contract = next(item for item in campaign["stages"] if item["stage_id"] == stage_id)
    conclusions = set(stage_contract["conclusions"])
    predecessor = _bound_predecessor_document(plan)
    results: dict[str, Any] = {}
    performance_metrics_read = False
    selected_outer_points: list[dict[str, float]] = []
    frozen_primary: dict[str, float] | None = None
    best_feasible_two_zone: dict[str, float] | None = None
    failed_rows = 0
    if stage_id == "T0":
        passed = True
        conclusion = "CONTRACT_READY_FOR_ORACLE"
        next_stage_authorized = True
    elif stage_id == "T1":
        passed, results = _execute_t1(campaign)
        conclusion = "THEORY_ORACLE_SUPPORTED" if passed else "THEORY_ORACLE_FAILED"
        next_stage_authorized = passed
    elif stage_id in {"G1", "G2"}:
        if manual_conclusion not in conclusions:
            raise ValueError(f"{stage_id} requires one declared manual conclusion")
        conclusion = str(manual_conclusion)
        passed = conclusion not in {"G1_STOP", "G1_REQUIRE_SUCCESSOR_CONTRACT", "G2_STOP"}
        next_stage_authorized = passed
        results = {"manual_gate_conclusion": conclusion}
        if predecessor is not None:
            selected_outer_points = list(predecessor["selected_outer_points"])
            frozen_primary = predecessor["frozen_primary"]
            best_feasible_two_zone = predecessor["best_feasible_two_zone"]
        if stage_id == "G2" and conclusion == "G2_PRIMARY_FROZEN":
            if not selected_outer_points:
                raise ValueError("G2_PRIMARY_FROZEN requires a selected outer point")
            frozen_primary = dict(selected_outer_points[0])
    elif stage_id in {"T2", "T3", "T4a", "T4b", "T4c", "T5"}:
        outcome = execute_numeric_stage(campaign, plan, predecessor)
        passed = outcome.status == "success"
        conclusion = outcome.conclusion
        next_stage_authorized = outcome.next_stage_authorized
        results = outcome.results
        performance_metrics_read = True
        selected_outer_points = outcome.selected_outer_points
        frozen_primary = outcome.frozen_primary
        best_feasible_two_zone = outcome.best_feasible_two_zone
        failed_rows = outcome.failed_rows
    else:
        raise AssertionError(f"unhandled stage {stage_id}")
    if conclusion not in conclusions:
        raise ValueError(f"stage conclusion {conclusion} is not declared by campaign")
    status = "success" if passed else "failed"
    planned = len(plan["rows"])
    completed = planned
    if not failed_rows and not passed:
        failed_rows = planned
    report = {
        "schema_version": 1,
        "role": "oatof_three_zone_stage_report",
        "campaign_id": campaign["campaign_id"],
        "stage_id": stage_id,
        "plan_sha256": plan["plan_sha256"],
        "status": status,
        "scientific_assessment": conclusion,
        "engineering_compatibility_annotation": (
            "REAL_FIELD_AND_MANUFACTURING_NOT_ASSESSED"
            if stage_id in {"T1", "T2", "T3", "T4a", "T4b", "T4c", "T5"}
            else "NOT_APPLICABLE"
        ),
        "row_census": {
            "planned": planned,
            "completed": completed,
            "failed": failed_rows,
            "not_started": planned - completed,
        },
        "results": results,
        "allowed_claim": (
            "Solver-free formula oracle and staged contract only; no engineering or solver qualification."
        ),
        "claim_limit": campaign["claim_limit"],
    }
    validate_schema(report, REPORT_SCHEMA)
    output_dir.mkdir(parents=True, exist_ok=False)
    plan_path = output_dir / "resolved_plan.json"
    report_path = output_dir / "stage_report.json"
    receipt_path = output_dir / "stage_receipt.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_record = {
        "path": str(report_path.resolve()),
        "bytes": report_path.stat().st_size,
        "sha256": file_sha256(report_path),
    }
    receipt = {
        "schema_version": 1,
        "role": "oatof_three_zone_stage_receipt",
        "campaign_id": campaign["campaign_id"],
        "campaign_sha256": plan["campaign_sha256"],
        "stage_id": stage_id,
        "plan_sha256": plan["plan_sha256"],
        "status": status,
        "conclusion": conclusion,
        "next_stage_authorized": next_stage_authorized,
        "assessment_design_status": campaign["assessment_design_status"],
        "solver_execution_performed": False,
        "performance_metrics_read": performance_metrics_read,
        "completed_rows": completed,
        "planned_rows": planned,
        "selected_outer_points": selected_outer_points,
        "frozen_primary": frozen_primary,
        "best_feasible_two_zone": best_feasible_two_zone,
        "report": report_record,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_limit": campaign["claim_limit"],
    }
    validate_schema(receipt, RECEIPT_SCHEMA)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return report, receipt
