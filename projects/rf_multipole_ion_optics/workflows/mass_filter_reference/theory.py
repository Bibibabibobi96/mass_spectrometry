"""Solver-independent L0 reference calculations for an ideal quadrupole.

The voltage convention follows ``docs/multipoles``: ``U`` and ``V`` are the
DC and RF amplitudes of one rod group about the common-mode axis voltage, and
``V`` is zero-to-peak.  The opposite rod group receives the negative of those
differential components.  A common-mode offset does not enter the ideal
transverse Mathieu parameters.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


from msplatform.workflows.rf_mass_filter import reference


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "baseline.json"
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "quadrupole_mass_filter_reference.json"



















def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--check-mode", action="store_true")
    args = parser.parse_args()
    if not args.check_mode:
        parser.error("--check-mode is required")
    result = reference.validate_mass_filter_reference(_load(args.baseline), _load(args.mode))
    print(json.dumps(result, indent=2, sort_keys=True))
    print("QUADRUPOLE_L0_REFERENCE=PASS")


if __name__ == "__main__":
    main()
