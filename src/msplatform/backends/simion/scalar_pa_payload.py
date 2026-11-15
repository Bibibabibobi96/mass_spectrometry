"""Finalize owner-private Assembly scalar payloads with the shared PA header."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from msplatform.backends.simion.collision_overlay import COLLISION_NOTREFINABLE_FLAG, collision_pa_header
from msplatform.backends.simion.standalone_pa_composition import HEADER, PA_CHUNK_NODES, PaHeader


def finalize_scalar_pair(potential: Path, mask: Path, grid: Mapping[str, Any]) -> None:
    """Validate raw x-fastest doubles and write headers only after both scans pass.

    MATLAB supplies no PA-format fields. It writes HEADER.size zero placeholder
    bytes followed by the complete little-endian payload to two owned files.
    A failure leaves actual partial owned bytes for the existing owner lifecycle.
    """
    potential, mask = Path(potential), Path(mask)
    if potential.resolve() == mask.resolve():
        raise ValueError('scalar potential and mask must be distinct files')
    dimensions = grid.get('dimensions'); pitch = grid.get('pitch_mm')
    if (not isinstance(dimensions,(list,tuple)) or len(dimensions)!=3
            or any(type(n) is not int or n<2 or n>90000 for n in dimensions)
            or dimensions[0]<3 or dimensions[1]<3):
        raise ValueError('scalar grid dimensions exceed the PA writer minimum')
    if (not isinstance(pitch,(list,tuple)) or len(pitch)!=3
            or any(type(n) not in (int,float) or not math.isfinite(n) or n<=0 for n in pitch)):
        raise ValueError('scalar grid pitch must be three finite positive values')
    count=math.prod(dimensions)
    if type(grid.get('point_count')) is not int or grid['point_count']!=count:
        raise ValueError('scalar grid point count differs')
    expected=HEADER.size+8*count
    maximum=1.0
    for path,is_mask in ((potential,False),(mask,True)):
        if path.suffix.lower()!='.pa' or not path.is_file() or path.is_symlink() or path.stat().st_size!=expected:
            raise ValueError('scalar raw payload path or length differs: '+str(path))
        with path.open('rb') as stream:
            if stream.read(HEADER.size)!=bytes(HEADER.size):
                raise ValueError('scalar raw header placeholder differs: '+str(path))
            remaining=count
            while remaining:
                block=np.fromfile(stream,dtype='<f8',count=min(remaining,PA_CHUNK_NODES))
                if not block.size or not np.isfinite(block).all():
                    raise ValueError('scalar raw payload is truncated or nonfinite: '+str(path))
                if is_mask:
                    if not np.logical_or(block==0.0,block==1.0).all():
                        raise ValueError('scalar validity payload must contain only zero or one')
                else:
                    maximum=max(maximum,float(np.max(np.abs(block))))
                remaining-=int(block.size)
            if stream.read(1):
                raise ValueError('scalar raw payload has trailing bytes: '+str(path))
    for path,limit in ((potential,maximum),(mask,1.0)):
        header=PaHeader(-2,1,limit,*dimensions,COLLISION_NOTREFINABLE_FLAG,*pitch)
        with path.open('r+b') as stream:
            if stream.write(header.pack())!=HEADER.size:
                raise OSError('scalar PA header write incomplete: '+str(path))
        if collision_pa_header(path)!=header:
            raise ValueError('final scalar PA header differs: '+str(path))
