"""Frozen worker for sealed-parent mass-spectrum reanalysis."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from msplatform.workflows.single_reflection_mass_spectrum import analyze_mass_spectrum
from msplatform.workflows.single_reflection_mass_spectrum_study import OUTPUT_NAMES


def _verify_required_sources(root: Path, selection: dict) -> None:
    inventory = json.loads((root.parent / "code_inventory.json").read_text(encoding="utf-8-sig"))
    required = (
        "msplatform/workflows/single_reflection_mass_spectrum.py",
        "msplatform/results/single_reflection_particle_table.py",
        "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json",
    )
    for relative in required:
        matches = [row for row in inventory["files"] if row.get("relative_path") == relative]
        if len(matches) != 1:
            raise ValueError(f"Frozen mass-spectrum source identity differs: {relative}")
        path = root / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual.lower() != str(matches[0]["sha256"]).lower():
            raise ValueError(f"Frozen mass-spectrum source identity differs: {relative}")
    geometry = next(row for row in inventory["files"]
                    if row.get("relative_path") == required[2])
    if str(geometry["sha256"]).lower() != selection["inputs"]["resolved_geometry"]["sha256"].lower():
        raise ValueError("Frozen selected geometry identity differs")


def run_frozen_analysis(*, selection_path: Path, output: Path, code_root: Path) -> dict:
    selection = json.loads(selection_path.read_text(encoding="utf-8-sig"))
    root = code_root.resolve(strict=True)
    _verify_required_sources(root, selection)
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        origin = getattr(module, "__file__", None)
        if (name == "msplatform" or name.startswith("msplatform.")) and origin:
            if not Path(origin).resolve().is_relative_to(root):
                raise ValueError("Mass-spectrum analyzer escaped its frozen source root")
    result = analyze_mass_spectrum(
        Path(selection["frozen_mode"]), Path(selection["source_directory"]) / "comsol",
        Path(selection["exports"]["simion_csv"]["path"]), output,
        Path(selection["frozen_geometry"]),
    )
    expected = {"mode_config": selection["inputs"]["mode_config"]["sha256"],
                "simion_csv": selection["exports"]["simion_csv"]["sha256"]}
    expected.update({name: row["sha256"] for name, row in selection["exports"].items()
                     if name.startswith("comsol_")})
    if any(str(result["inputs"].get(name, "")).lower() != sha.lower()
           for name, sha in expected.items()):
        raise ValueError("Consumed mass-spectrum record differs from its frozen source selection")
    missing = [name for name in OUTPUT_NAMES if not (output / name).is_file()]
    if missing:
        raise ValueError(f"Mass-spectrum analysis outputs are incomplete: {missing}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    args = parser.parse_args()
    result = run_frozen_analysis(selection_path=args.selection, output=args.output,
                                 code_root=args.code_root)
    print(json.dumps(dict(status=result["status"], species=len(result["species"]) // 2)))


if __name__ == "__main__":
    main()
