"""Validate the required file family for a SIMION surface=none PA build."""

from __future__ import annotations

import argparse
from pathlib import Path


def validate_family(directory: Path, stem: str, highest_electrode: int) -> list[Path]:
    if highest_electrode < 0:
        raise ValueError("highest electrode must be nonnegative")
    required = [directory / f"{stem}.pa#"] + [
        directory / f"{stem}.pa{index}" for index in range(highest_electrode + 1)
    ]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"{stem} PA family missing required files: {', '.join(missing)}")
    surface = directory / f"{stem}.pa-surf"
    if surface.exists():
        raise ValueError(f"{stem} surface=none PA family unexpectedly contains pa-surf")
    return required


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("stem")
    parser.add_argument("highest_electrode", type=int)
    args = parser.parse_args()
    required = validate_family(args.directory, args.stem, args.highest_electrode)
    print(f"PA_FAMILY=PASS STEM={args.stem} FILES={len(required)}")


if __name__ == "__main__":
    main()
