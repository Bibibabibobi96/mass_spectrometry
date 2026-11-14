"""Classify only invalid scalar-grid nodes against explicit Assembly geometry."""
from __future__ import annotations

import copy
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from msplatform.components.shape_query import query_members


def _sheet_is_zero_thickness(shape: Mapping[str, Any]) -> bool:
    kind = shape.get('kind')
    if kind == 'box': return any(value == 0 for value in shape['size_mm'])
    if kind == 'cylinder': return shape['height_mm'] == 0
    if kind in {'rod', 'annulus'}: return shape['z_min_mm'] == shape['z_max_mm']
    return False


class InvalidNodeClassifier:
    """Stream explicit invalid nodes; supply voltage only for a unique solid interior.

    ``projection`` and ``request`` must be independently verified frozen input
    documents. This helper does not own records, launch processes or mutate them.
    Node indices are one-based MATLAB order (x fastest), strictly increasing.
    """

    def __init__(self, projection: Mapping[str, Any], request: Mapping[str, Any], grid: Mapping[str, Any]) -> None:
        frame = projection['assembly_frame_id']
        if not isinstance(frame, str) or not frame or grid.get('frame_id') != frame:
            raise ValueError('grid and Assembly frame must match exactly')
        dimensions = grid['dimensions']; origin = grid['origin_mm']; pitch = grid['pitch_mm']
        if any(not isinstance(value, (list, tuple)) or len(value) != 3 for value in (dimensions, origin, pitch)):
            raise ValueError('grid needs explicit three-dimensional coordinates')
        if any(type(v) is not int or v < 2 for v in dimensions):
            raise ValueError('grid dimensions must be integers at least two')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in origin):
            raise ValueError('grid origin must be finite')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in pitch):
            raise ValueError('grid pitch must be finite and positive')
        if type(grid.get('point_count')) is not int or grid['point_count'] != math.prod(dimensions):
            raise ValueError('grid point count differs from dimensions')
        groups = projection['electrode_groups']; members = projection['members']
        identities = [(row['instance_id'], row['electrode_group_id']) for row in groups]
        if not identities or len(set(identities)) != len(identities):
            raise ValueError('scientific group identity must be unique')
        if any(not isinstance(a, str) or not a or not isinstance(b, str) or not b for a, b in identities):
            raise ValueError('scientific group names must be nonempty strings')
        expected = set(identities); values: dict[tuple[str, str], float] = {}
        declared_members = {}
        for row, key in zip(groups, identities, strict=True):
            names = row['member_ids']
            if (not isinstance(names, (list, tuple)) or not names
                    or any(not isinstance(name, str) or not name for name in names)
                    or len(set(names)) != len(names)):
                raise ValueError('scientific group member list differs')
            declared_members[key] = set(names)
        actual_members = {key: set() for key in expected}
        for row in request['group_voltages']:
            if not isinstance(row, Mapping) or set(row) != {'instance_id', 'electrode_group_id', 'voltage_v'}:
                raise ValueError('invalid scientific voltage row')
            key = (row['instance_id'], row['electrode_group_id']); voltage = row['voltage_v']
            if key in values or type(voltage) not in (int, float) or not math.isfinite(voltage):
                raise ValueError('scientific group voltage is duplicated or nonfinite')
            values[key] = float(voltage)
        if set(values) != expected:
            raise ValueError('scientific group voltage coverage differs')
        for member in members:
            if (member['instance_id'], member['electrode_group_id']) not in expected:
                raise ValueError('member has no declared scientific group')
            key = (member['instance_id'], member['electrode_group_id'])
            name = member['member_id']
            if not isinstance(name, str) or not name or name in actual_members[key]:
                raise ValueError('member identity is missing or duplicated')
            actual_members[key].add(name)
            role = member['representation_role']
            if role not in {'physical_solid', 'ideal_surface'}:
                raise ValueError('unsupported member representation role')
            if role == 'ideal_surface' and not _sheet_is_zero_thickness(member['shape']):
                raise ValueError('ideal surface is not represented as zero thickness')
        if actual_members != declared_members:
            raise ValueError('scientific group member coverage differs')
        self._members = tuple(copy.deepcopy(members)); self._voltages = values; self._frame = frame
        self._dimensions = tuple(dimensions); self._origin = tuple(origin); self._pitch = tuple(pitch)
        self._count = grid['point_count']; self.counts: Counter[str] = Counter()

    def classify(self, invalid_nodes: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
        """Yield one ordered decision per input; uncertainty never emits a voltage."""
        previous = 0
        nx, ny, _ = self._dimensions
        for row in invalid_nodes:
            if not isinstance(row, Mapping) or set(row) != {'index', 'world_mm'}:
                raise ValueError('invalid node needs only index and world_mm')
            index = row['index']; world = row['world_mm']
            if type(index) is not int or not previous < index <= self._count:
                raise ValueError('invalid node indices must be unique, increasing and in bounds')
            if not isinstance(world, (list, tuple)) or len(world) != 3 or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in world):
                raise ValueError('invalid node coordinates must be finite')
            n = index - 1
            xyz_index = (n % nx, (n // nx) % ny, n // (nx * ny))
            expected = tuple(self._origin[i] + self._pitch[i] * xyz_index[i] for i in range(3))
            if tuple(world) != expected:
                raise ValueError('invalid node coordinate differs from its grid index')
            previous = index
            decision = query_members(self._members, world, frame_id=self._frame)
            status = decision['status']; self.counts[status] += 1
            if status == 'interior':
                yield {'index': index, 'classification': status, 'group': decision['group'],
                       'voltage_v': self._voltages[decision['group']]}
            else:
                yield {'index': index, 'classification': status}


def fill_invalid_scalar_pa(potential_path: str | Path, mask_path: str | Path,
                           output_potential_path: str | Path, output_mask_path: str | Path,
                           *, projection: Mapping[str, Any], request: Mapping[str, Any],
                           grid: Mapping[str, Any], chunk_nodes: int = 65536) -> dict[str, Any]:
    """Fill strict conductor interiors into two new scalar PAs; caller guards inputs.

    Grid positions/pitches are in mm and group potentials in volts; chunk size is
    an engineering memory bound. Inputs are immutable verified samples.
    The caller owns exclusive private staging and publishes only after success.
    Failed calls may leave newly created partial staging files for that owner.
    The PA pair is not a field qualification or a native geometry change.
    """
    import os
    from dataclasses import replace
    from pathlib import Path
    from contextlib import ExitStack
    import numpy as np
    from msplatform.backends.simion.collision_overlay import COLLISION_NOTREFINABLE_FLAG, collision_pa_header
    from msplatform.backends.simion.standalone_pa_composition import HEADER, _read_block

    if type(chunk_nodes) is not int or chunk_nodes < 1:
        raise ValueError('chunk_nodes must be a positive integer')
    paths = [Path(p).absolute() for p in (potential_path, mask_path, output_potential_path, output_mask_path)]
    if any(p.suffix.lower() != '.pa' for p in paths):
        raise ValueError('scalar inputs and outputs require .pa')
    identities = [p.resolve() for p in paths]
    if len(set(identities)) != 4:
        raise ValueError('input and output paths must be distinct')
    for p in paths:
        if p.with_suffix('.pa-surf').exists():
            raise ValueError('scalar PA sidecars are unsupported')
    for out in paths[2:]:
        if out.exists() or out.is_symlink():
            raise ValueError('output exists')
        if not out.parent.is_dir():
            raise ValueError('output parent must exist')
    if os.path.samefile(paths[0], paths[1]):
        raise ValueError('input paths refer to the same file')
    classifier = InvalidNodeClassifier(projection, request, grid)
    hp, hm = [collision_pa_header(p) for p in paths[:2]]
    if any(h.mode != -2 or h.symmetry != 1 or h.raw_mirror != COLLISION_NOTREFINABLE_FLAG for h in (hp,hm)):
        raise ValueError('expected non-refinable 3D planar scalar PAs')
    if hp.grid_identity != hm.grid_identity:
        raise ValueError('potential and mask grids differ')
    if ((hp.nx,hp.ny,hp.nz) != tuple(grid['dimensions']) or
            (hp.dx_mm,hp.dy_mm,hp.dz_mm) != tuple(grid['pitch_mm'])):
        raise ValueError('PA header differs from explicit world grid')
    if not all(math.isfinite(2*h.max_voltage) for h in (hp,hm)):
        raise ValueError('PA voltage encoding range overflows')
    if hm.max_voltage < 1:
        raise ValueError('mask range cannot encode one')
    with ExitStack() as stack:
        source_p, source_m = [stack.enter_context(p.open('rb')) for p in paths[:2]]
        dest_p, dest_m = [stack.enter_context(p.open('xb')) for p in paths[2:]]
        for src,dst in ((source_p,dest_p),(source_m,dest_m)):
            header=src.read(HEADER.size)
            if len(header)!=HEADER.size:raise ValueError('truncated PA header')
            dst.write(header)
        nx,ny,_=grid['dimensions']; origin=grid['origin_mm']; pitch=grid['pitch_mm']
        offset=0; filled=0; maximum=hp.max_voltage
        while offset < hp.node_count:
            count=min(chunk_nodes,hp.node_count-offset)
            values, flags=_read_block(source_p,count,hp)
            mask, mask_flags=_read_block(source_m,count,hm)
            if np.any(flags) or np.any(mask_flags):raise ValueError('scalar PA electrode flags are forbidden')
            if not np.all((mask==0)|(mask==1)):raise ValueError('scalar mask must be binary')
            invalid=np.flatnonzero(mask==0)
            def nodes():
                for local in invalid:
                    index=offset+int(local)+1; n=index-1
                    ijk=(n%nx,(n//nx)%ny,n//(nx*ny))
                    yield {'index':index,'world_mm':[origin[a]+pitch[a]*ijk[a] for a in range(3)]}
            for row in classifier.classify(nodes()):
                if row['classification']=='interior':
                    j=row['index']-offset-1
                    maximum=max(maximum,abs(row['voltage_v']))
                    if not math.isfinite(2*maximum):raise ValueError('filled voltage encoding range overflows')
                    values[j]=row['voltage_v'];mask[j]=1.;filled+=1
            values.astype('<f8',copy=False).tofile(dest_p)
            mask.astype('<f8',copy=False).tofile(dest_m)
            offset+=count
        dest_p.seek(0);dest_p.write(replace(hp,max_voltage=maximum).pack())
        for dst in (dest_p,dest_m):dst.flush();os.fsync(dst.fileno())
    return {'status':'success','filled_conductor_count':filled,'classifications':dict(classifier.counts),
            'nodes':hp.node_count,'qualification':False}
