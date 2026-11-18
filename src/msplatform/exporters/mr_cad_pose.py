#!/usr/bin/env python3
"""Compose frozen SolidWorks transforms into top-level CAD pose evidence.

The SolidWorks MathTransform ArrayData convention is represented as a row-vector
map ``p_parent = p_local R + t``.  This utility only composes independently
audited transform arrays; it does not open, save, or change CAD.
"""

from __future__ import annotations

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
