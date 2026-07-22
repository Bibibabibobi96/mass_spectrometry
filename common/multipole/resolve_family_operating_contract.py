"""Resolve project-specific multipole inputs into the shared operating contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.multipole.family_contract import (
    from_high_order_baseline,
    from_quadrupole_contract,
    operating_contract_document,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, choices=("high-order", "quadrupole"))
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--mode", type=Path)
    parser.add_argument("--rf-amplitude-v-per-group", type=float)
    parser.add_argument("--frequency-hz", type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
    if args.adapter == "quadrupole":
        if args.mode is None:
            parser.error("--mode is required for the quadrupole adapter")
        mode = json.loads(args.mode.read_text(encoding="utf-8-sig"))
        operating = from_quadrupole_contract(
            baseline,
            mode,
            rf_amplitude_v_per_group=args.rf_amplitude_v_per_group,
            frequency_hz=args.frequency_hz,
        )
    else:
        if args.mode is not None or args.rf_amplitude_v_per_group is not None or args.frequency_hz is not None:
            parser.error("quadrupole mode and per-run RF bindings are not used by the high-order adapter")
        operating = from_high_order_baseline(baseline)
    document = operating_contract_document(operating)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"MULTIPOLE_OPERATING_CONTRACT=PASS PROJECT={document['identity']['project_id']} "
        f"ORDER={document['identity']['radial_order_n']}"
    )


if __name__ == "__main__":
    main()
