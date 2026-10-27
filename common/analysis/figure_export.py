"""Export an explicit batch of prepared figures without overwriting files.

Callers own figure creation, names, formats, resolution, appearance and closing.
This module computes no scientific quantities and does not publish run manifests.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def export_figures(figures: Mapping[Path, Figure], *, formats: Sequence[str],
                   dpi: float, facecolor: str) -> list[dict]:
    """Save prepared figures at caller-supplied complete stems and return records.

    All output parents must already exist. Preflight checks every resolved
    destination, format and collision before writing. Each destination is then
    opened exclusively; any save failure removes only files created by this
    call and propagates the error. Existing files are never overwritten.
    Records contain actual path, format, savefig DPI, figure inches, byte size
    and the explicit background color. Figure lifetime remains with the caller.
    """
    if not figures or isinstance(formats, str) or not formats or len(set(formats)) != len(formats):
        raise ValueError("nonempty figures and unique explicit formats required")
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("figure DPI must be finite and positive")
    if not isinstance(facecolor, str) or not facecolor:
        raise ValueError("explicit figure facecolor required")
    planned, seen = [], set()
    for stem, figure in figures.items():
        size = [float(value) for value in figure.get_size_inches()]
        if len(size) != 2 or any(not math.isfinite(value) or value <= 0 for value in size):
            raise ValueError("figure size in inches must be finite and positive")
        supported = figure.canvas.get_supported_filetypes()
        for extension in formats:
            if not isinstance(extension, str) or extension not in supported:
                raise ValueError(f"unsupported explicit figure format: {extension!r}")
            declared = Path(str(stem) + "." + extension)
            if declared.exists() or declared.is_symlink():
                raise FileExistsError(f"figure export refuses to overwrite: {declared}")
            path = declared.resolve()
            if path in seen:
                raise ValueError(f"duplicate figure destination: {path}")
            if path.exists() or path.is_symlink():
                raise FileExistsError(f"figure export refuses to overwrite: {path}")
            if not path.parent.is_dir():
                raise FileNotFoundError(f"figure output parent does not exist: {path.parent}")
            seen.add(path)
            planned.append((figure,path,extension,size))
    created, records = [], []
    try:
        for figure,path,extension,size in planned:
            with path.open("xb") as stream:
                created.append(path)
                figure.savefig(stream,format=extension,dpi=dpi,facecolor=facecolor)
            byte_count = path.stat().st_size
            if not byte_count:
                raise ValueError(f"figure export produced an empty file: {path}")
            records.append(dict(path=str(path),format=extension,savefig_dpi=dpi,
                                size_inches=size,bytes=byte_count,facecolor=facecolor))
    except BaseException:
        for path in reversed(created):
            path.unlink()
        raise
    return records
