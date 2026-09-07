"""Validate the bounded finite-3-D first-prism SIMION diagnostic result."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


class FirstPrismResultError(ValueError):
    """Raised when a first-prism diagnostic log is incomplete or inconsistent."""


_FIELDS = re.compile(r"([A-Za-z_]+)=([^ ]+)")


def _fields(line: str) -> dict[str, str]:
    return dict(_FIELDS.findall(line))


def _number(fields: dict[str, str], key: str) -> float:
    try:
        value = float(fields[key])
    except (KeyError, ValueError) as error:
        raise FirstPrismResultError(f"event lacks finite {key}") from error
    if not math.isfinite(value):
        raise FirstPrismResultError(f"event {key} is non-finite")
    return value


def _expected_source(input_manifest: Path) -> dict[str, Any]:
    document = json.loads(input_manifest.read_text(encoding="utf-8"))
    source = document.get("first_prism_iob_fly2")
    if not isinstance(source, dict) or source.get("particle_count") != 1:
        raise FirstPrismResultError("input manifest does not bind one first-prism IOB particle")
    if source.get("expected_particle_ids") != [1]:
        raise FirstPrismResultError("first-prism IOB source must bind exactly ion 1")
    return source


def analyze(log_path: Path, input_manifest: Path, receipt_path: Path) -> dict[str, Any]:
    """Return a fail-closed receipt for one actual finite-3-D interface crossing."""
    source = _expected_source(input_manifest)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "reference_static_prism_candidate__first_prism_l0_only":
        raise FirstPrismResultError("first-prism receipt status is incompatible")
    target_z = float(receipt["target_plane_z_mm"])
    target_x = float(receipt["target_plane_x_mm"])
    acceptance = receipt["target_plane_y_acceptance_mm"]
    if not isinstance(acceptance, list) or len(acceptance) != 2:
        raise FirstPrismResultError("first-prism receipt has no y acceptance")
    lines = log_path.read_text(encoding="utf-8", errors="strict").splitlines()
    interfaces = [_fields(line) for line in lines if line.startswith("MRTOF_FIRST_PRISM_EVENT interface ")]
    terminals = [_fields(line) for line in lines if line.startswith("MRTOF_FIRST_PRISM_EVENT terminal ")]
    if len(interfaces) != 1 or len(terminals) != 1:
        raise FirstPrismResultError("first-prism log must contain exactly one interface and one terminal event")
    interface, terminal = interfaces[0], terminals[0]
    if interface.get("ion") != "1" or terminal.get("ion") != "1":
        raise FirstPrismResultError("first-prism events do not belong to frozen ion 1")
    if interface.get("accepted_y") != "true" or terminal.get("interface_reached") != "true":
        raise FirstPrismResultError("ion did not reach the accepted first-prism interface")
    if terminal.get("splat") != "1":
        raise FirstPrismResultError("first-prism diagnostic did not stop on its declared interface event")
    x, y, z, time_us = (_number(interface, key) for key in ("x_mm", "y_mm", "z_mm", "t_us"))
    x_offset = _number(interface, "x_offset_mm")
    if abs(z - target_z) > 1e-9 or abs(x_offset - (x - target_x)) > 1e-9:
        raise FirstPrismResultError("interface interpolation differs from frozen target plane")
    if not float(acceptance[0]) <= y <= float(acceptance[1]):
        raise FirstPrismResultError("interface event lies outside frozen y acceptance")
    return {
        "schema_version": 1,
        "status": "prototype_first_prism_interface_observed",
        "source": {"filename": source["filename"], "sha256": source["sha256"], "particle_count": 1},
        "interface": {
            "ion": 1, "time_us": time_us, "position_project_mm": [x, y, z],
            "x_offset_from_target_mm": x_offset, "y_acceptance_mm": [float(acceptance[0]), float(acceptance[1])],
        },
        "limitations": [
            "One finite-3-D first-prism crossing only; it does not validate a second prism, K=25 circulation, time focus, transmission, or resolution.",
            "The prism-16 voltage remains a static L0 seed pending a finite-3-D shooting/return optimization.",
        ],
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.log, args.input_manifest, args.receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FIRST_PRISM_L0_RESULT=PASS OUTPUT=" + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
