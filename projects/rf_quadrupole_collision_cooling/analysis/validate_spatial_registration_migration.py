"""Fail closed if active RF-to-oaTOF code reintroduces coordinate authority."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
POLICY = PROJECT_ROOT / "config" / "spatial_registration_migration_policy.json"
PYTHON_FILES = (
    PROJECT_ROOT / "analysis" / "build_interface_handoff.py",
    PROJECT_ROOT / "analysis" / "build_oatof_handoff.py",
    PROJECT_ROOT / "analysis" / "resolve_s2_connector_case.py",
    PROJECT_ROOT / "analysis" / "resolve_spatial_registration.py",
    PROJECT_ROOT / "analysis" / "analyze_rf_oatof_checkpoints.py",
    REPOSITORY_ROOT / "projects" / "oa_tof" / "analysis" / "rf_handoff_adapter.py",
)
MATLAB_FILES = (
    PROJECT_ROOT / "tests" / "comsol" / "build_s1_joint_field_candidate.m",
    PROJECT_ROOT / "tests" / "comsol" / "build_s2_passive_connector_model.m",
    PROJECT_ROOT / "tests" / "comsol" / "solve_s2_passive_connector_field.m",
)
LOCAL_PRIMITIVES = {"determinant3", "matvec", "matmul3", "transpose3"}


def scan_python(path: Path, source: str) -> list[str]:
    """Return ratchet violations in one active Python source."""
    tree = ast.parse(source, filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in LOCAL_PRIMITIVES:
            if "RigidTransform" not in ast.unparse(node):
                violations.append(
                    f"no_local_matrix_primitives:{path.name}:{node.name}"
                )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in LOCAL_PRIMITIVES
        ):
            violations.append(
                f"no_local_matrix_primitive_calls:{path.name}:{node.lineno}"
            )
        if isinstance(node, ast.Dict):
            pairs = {
                key.value: value.value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            }
            if (
                pairs.get("role")
                == "resolved_spatial_registration_do_not_edit"
            ):
                violations.append(
                    f"no_second_resolved_authority:{path.name}:{node.lineno}"
                )
    if path.name == "resolve_spatial_registration.py":
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and float(node.value) == 90.2
            ):
                violations.append(
                    f"no_instance_surface_constant:{path.name}:{node.lineno}"
                )
    return violations


def scan_matlab(path: Path, source: str) -> list[str]:
    """Return ratchet violations in one active MATLAB supplier adapter."""
    violations: list[str] = []
    if "RF_OATOF_SPATIAL_REGISTRATION" not in source:
        violations.append(
            f"commercial_adapters_consume_resolved:{path.name}:missing_input"
        )
    if "expectedSourceRotation" in source or re.search(
        r"rotation\s*=\s*\[\s*0\s+0\s+1\s*;\s*1\s+0\s+0\s*;\s*0\s+1\s+0\s*\]",
        source,
    ):
        violations.append(
            f"commercial_adapters_consume_resolved:{path.name}:hardcoded_pose"
        )
    return violations


def validate() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    expected_rules = {
        "no_local_matrix_primitives",
        "no_second_resolved_authority",
        "commercial_adapters_consume_resolved",
        "no_instance_surface_constant",
    }
    if (
        policy.get("role") != "spatial_registration_migration_ratchet"
        or {item.get("rule_id") for item in policy.get("rules", [])}
        != expected_rules
        or policy.get("legacy_exceptions") != []
    ):
        raise ValueError("spatial-registration migration policy is invalid")
    violations: list[str] = []
    for path in PYTHON_FILES:
        violations.extend(scan_python(path, path.read_text(encoding="utf-8")))
    for path in MATLAB_FILES:
        violations.extend(scan_matlab(path, path.read_text(encoding="utf-8")))
    if violations:
        raise ValueError(
            "spatial-registration migration ratchet failed: "
            + ", ".join(violations)
        )


def main() -> None:
    validate()
    print("SPATIAL_REGISTRATION_MIGRATION=PASS LEGACY_EXCEPTIONS=0")


if __name__ == "__main__":
    main()
