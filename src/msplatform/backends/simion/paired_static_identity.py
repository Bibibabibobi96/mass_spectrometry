"""Pure identity of the paired OA static operating field."""
from __future__ import annotations


def paired_static_pa_identity(plan: dict, *, gem_sha256: str, simion_bytes: int,
                              simion_sha256: str, builder_sha256: dict[str, str]) -> dict:
    """Bind only inputs consumed by the static field solve, not sample points."""
    grid = plan['native_geometry_compilation']['grid']
    return dict(geometry=plan['accelerator_geometry'], gem=gem_sha256,
        working_points=[dict(kind='static_on', voltages_v=plan['static_on_electrode_voltages_v'],
                             refine_policy='installed_default')],
        mesh=grid['cell_mm_xyz'], grid_phase=grid['instance_origin_mm'], surface='none',
        boundary_policy=plan['numerical_domain']['boundary_policy'],
        simion_identity=dict(release='SIMION 2020', executable_bytes=simion_bytes,
                             executable_sha256=simion_sha256), builder_identity=dict(builder_sha256))
