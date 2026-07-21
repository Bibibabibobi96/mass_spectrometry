"""Compose the frozen oaTOF Formal SIMION Program with the pulse extension."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def build(formal: Path, extension: Path, output: Path, metadata: Path) -> None:
    formal_text = formal.read_text(encoding="utf-8")
    extension_text = extension.read_text(encoding="utf-8")
    if formal_text.count("simion.workbench_program()") != 1:
        raise ValueError("Formal Program must contain exactly one workbench declaration")
    if "simion.workbench_program()" in extension_text:
        raise ValueError("pulse extension must not redeclare the workbench Program")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(formal_text.rstrip() + "\n\n" + extension_text.rstrip() + "\n", encoding="utf-8", newline="\n")
    metadata.write_text(json.dumps({
        "schema_version": 1,
        "role": "oa_tof_handoff_pulse_program_build",
        "formal_program": {"path": str(formal.resolve()), "sha256": sha256(formal)},
        "pulse_extension": {"path": str(extension.resolve()), "sha256": sha256(extension)},
        "output": {"path": str(output.resolve()), "sha256": sha256(output)},
    }, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    build(args.formal, args.extension, args.output, args.metadata)
    print("OATOF_HANDOFF_PULSE_PROGRAM=PASS")


if __name__ == "__main__":
    main()
