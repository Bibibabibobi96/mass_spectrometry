"""Installed MATLAB sources for COMSOL backend operations.

MATLAB reserves a folder named ``resources`` and will not add it to its search
path. Executable sources therefore use the ordinary ``matlab`` directory.
See https://www.mathworks.com/help/matlab/ref/genpath.html (checked 2026-11-09
against the installed R2025b runtime).
"""
from importlib.resources import files
from pathlib import Path

NATIVE_RESOURCES = frozenset({
    "build_accelerator_grids.m",
    "build_and_export_paired_accelerator_field.m",
    "build_sectioned_geometry.m",
    "candidate_field.m",
    "classify_corridor_conductor_voltage.m",
    "export_corridor_scalar_field.m",
    "oatof_build_accelerator_geometry.m",
    "update_corridor_workpoint_voltages.m",
    "run_paired_accelerator_pulse.m", "oatof_read_cartesian_release.m", "oatof_cpt_solver_policy.m",
})


def native_resource_path(name: str) -> Path:
    """Return one registered installed MATLAB resource or fail closed."""
    if name not in NATIVE_RESOURCES:
        raise ValueError(f"unsupported COMSOL native resource: {name}")
    resource = files("msplatform.backends.comsol").joinpath("matlab", name)
    if not resource.is_file():
        raise FileNotFoundError(f"installed COMSOL native resource is missing: {name}")
    return Path(str(resource))


def native_resource_directory() -> Path:
    """Return the installed directory containing the complete MATLAB closure."""
    resource = files("msplatform.backends.comsol").joinpath("matlab")
    if not resource.is_dir():
        raise FileNotFoundError("installed COMSOL native resource directory is missing")
    return Path(str(resource))


def native_resource_text(name: str) -> str:
    """Read one registered UTF-8 MATLAB resource without executing it."""
    return native_resource_path(name).read_text(encoding="utf-8")
