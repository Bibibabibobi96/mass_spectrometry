"""Legacy CLI and one-way renderer bridge; native compilation lives in msplatform."""
import argparse
import json
from pathlib import Path
from msplatform.backends.simion import rf_geometry as _backend

for _name in dir(_backend):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_backend, _name)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--cell-mm", type=float)
    parser.add_argument("--cell-mm-x", type=float)
    parser.add_argument("--cell-mm-y", type=float)
    parser.add_argument("--cell-mm-z", type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    axis_values = (args.cell_mm_x, args.cell_mm_y, args.cell_mm_z)
    if args.cell_mm is not None and any(value is not None for value in axis_values):
        parser.error("--cell-mm is mutually exclusive with three-axis cell spacing")
    if args.cell_mm is None and not all(value is not None for value in axis_values):
        parser.error("provide --cell-mm or all of --cell-mm-x/y/z")
    cell_mm_xyz: dict[str, float] | float = (
        args.cell_mm
        if args.cell_mm is not None
        else {"x": args.cell_mm_x, "y": args.cell_mm_y, "z": args.cell_mm_z}
    )
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        _backend.render_gem(resolved, cell_mm_xyz),
        encoding="ascii",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
