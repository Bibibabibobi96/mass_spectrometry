"""Render the existing paired OA static-field SIMION sample task."""
from __future__ import annotations
import json
from pathlib import Path

ROLE = 'oatof_paired_accelerator_static_field_plan'


def render_simion_sample_task(plan: dict, *, pa: Path, points: Path, output: Path,
                              native_facts: Path, exporter: Path) -> str:
    """Bind the prepared common BVP and exact points to its existing Lua exporter."""
    if plan.get('role') != ROLE:
        raise ValueError('paired static sample plan identity differs')
    grid = plan['native_geometry_compilation']['grid']
    quote = lambda path: json.dumps(str(path).replace('\\', '/'), ensure_ascii=False)
    pitch, origin, dimensions = grid['cell_mm_xyz'], grid['instance_origin_mm'], grid['dimensions']
    return ("local export=dofile(%s)\n"
            "local plan={schema_version=1,role='%s',coordinate_frame='oatof_global',"
            "native_geometry_compilation={grid={dimensions={nx=%s,ny=%s,nz=%s},"
            "cell_mm_xyz={x=%s,y=%s,z=%s},instance_origin_mm={x=%s,y=%s,z=%s}}},"
            "sample_points={path=%s,count=%s}}\n"
            "local count=export(%s,plan,%s,%s)\nprint('PAIRED_FIELD_EXPORT=PASS samples='..count)\n") % (
        quote(exporter), ROLE, dimensions['nx'], dimensions['ny'], dimensions['nz'],
        repr(pitch['x']), repr(pitch['y']), repr(pitch['z']),
        repr(origin['x']), repr(origin['y']), repr(origin['z']),
        quote(points), plan['sample_points']['count'], quote(pa), quote(output), quote(native_facts))
