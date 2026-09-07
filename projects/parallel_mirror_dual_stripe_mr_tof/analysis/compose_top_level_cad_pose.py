#!/usr/bin/env python3
"""Compose frozen SolidWorks transforms into top-level CAD pose evidence.

The SolidWorks MathTransform ArrayData convention is represented as a row-vector
map ``p_parent = p_local R + t``.  This utility only composes independently
audited transform arrays; it does not open, save, or change CAD.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _transform(values: list[float]) -> tuple[list[list[float]], list[float]]:
    if len(values) < 13:
        raise ValueError("SolidWorks transform needs rotation, translation, and scale")
    if abs(float(values[12]) - 1.0) > 1e-12:
        raise ValueError("non-unit SolidWorks transform scale is not a rigid placement")
    return ([list(map(float, values[row * 3 : row * 3 + 3])) for row in range(3)], list(map(float, values[9:12])))


def _multiply(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3)] for row in range(3)]


def _row_vector(vector: list[float], matrix: list[list[float]]) -> list[float]:
    return [sum(vector[index] * matrix[index][column] for index in range(3)) for column in range(3)]


def compose(child_values: list[float], parent_values: list[float]) -> dict[str, Any]:
    """Return child-in-parent transform using the documented row-vector convention."""
    child_r, child_t = _transform(child_values)
    parent_r, parent_t = _transform(parent_values)
    rotation = _multiply(child_r, parent_r)
    translated_child = _row_vector(child_t, parent_r)
    translation = [translated_child[index] + parent_t[index] for index in range(3)]
    return {"rotation": rotation, "translation_m": translation}


def _index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["instance_name"]: record for record in records}


def _component_pose(local: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    result = compose(local["solidworks_transform_array"], parent["solidworks_transform_array"])
    array = [value for row in result["rotation"] for value in row] + result["translation_m"] + [1.0, 0.0, 0.0, 0.0]
    return {
        "local_instance": local["instance_name"],
        "top_parent": parent["instance_name"],
        "instance_name": local["instance_name"],
        "part_path": local["part_path"],
        "suppressed": local["suppressed"],
        "local_part_box_m": local.get("local_part_box_m"),
        "solidworks_transform_array": array,
        **result,
    }


def resolve(two_mirror: dict[str, Any], single_mirror: dict[str, Any], ion_foil: dict[str, Any]) -> dict[str, Any]:
    top = _index(two_mirror["components"])
    local_mirror = _index(single_mirror["components"])
    local_foil = _index(ion_foil["components"])
    mirrors = [top[f"单套反射电极装配组件-{index}"] for index in (1, 2)]
    foil_parent = top["离子箔装配组件-1"]
    mirror_parts = [
        local_mirror[name]
        for name in (
            "反射电极装配-电极A 盖板-1",
            "反射电极装配-电极A-1",
            "反射电极装配-电极B-1",
            "反射电极装配-电极C-1",
            "反射电极装配-电极D-1",
            "反射电极装配-电极E-1",
            "反射电极装配-电极E 盖板-1",
        )
    ]
    foil_parts = [
        record
        for name, record in local_foil.items()
        if any(token in name.lower() for token in ("ion foil", "prism", "grounded"))
    ]
    mirror_poses = {
        parent["instance_name"]: [_component_pose(part, parent) for part in mirror_parts]
        for parent in mirrors
    }
    foil_poses = [_component_pose(part, foil_parent) for part in foil_parts]
    a_covers = [
        next(pose for pose in mirror_poses[parent["instance_name"]] if pose["local_instance"] == "反射电极装配-电极A 盖板-1")
        for parent in mirrors
    ]
    inner_shield_midplane_y_m = sum(pose["translation_m"][1] for pose in a_covers) / 2.0
    return {
        "schema_version": 1,
        "units": "metres",
        "method": "frozen SolidWorks ArrayData, row-vector composition p_parent=p_local R+t",
        "top_level_assembly": two_mirror["assembly_path"],
        "assembly_path": two_mirror["assembly_path"],
        "mirror_component_poses": mirror_poses,
        "ion_foil_component_poses": foil_poses,
        # This is directly consumable by resolve_cad_geometry.py because each
        # component transform has already been composed into the top-level CAD
        # frame used by cad_to_theory_frame.json.
        "components": foil_poses,
        "derived_evidence": {
            "inner_A_cover_centre_y_m": [pose["translation_m"][1] for pose in a_covers],
            "midplane_between_A_cover_centres_y_m": inner_shield_midplane_y_m,
            "qualification": "Top-level CAD positions only.  No project-frame assignment is made until this CAD arrangement is checked against the documented z-reflection/y-drift/x-focus convention.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--two-mirror", required=True, type=Path)
    parser.add_argument("--single-mirror", required=True, type=Path)
    parser.add_argument("--ion-foil", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = resolve(*(json.loads(path.read_text(encoding="utf-8")) for path in (arguments.two_mirror, arguments.single_mirror, arguments.ion_foil)))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"COMPOSED_TOP_LEVEL_CAD_POSE: output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
