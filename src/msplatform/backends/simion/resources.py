"""The sole installed source of SIMION templates and native Lua bodies."""
import hashlib
from importlib.resources import files
from pathlib import Path

GEM_TEMPLATES = {
    "flight_tube": "oatof_flight_tube_ground.gem",
    "reflectron": "oatof_reflectron_ideal_10_5.gem",
    "detector": "oatof_detector_ground.gem",
}

NATIVE_RESOURCES = frozenset({
    "oatof_analyzer_component.lua",
    "model_drive.lua",
    "build_model_iob.lua",
    "build_field_iob.lua",
    "build_tracking_iob.lua",
    "voltage_waveforms.lua", "rf_drive.lua", "single_flight_pulse_hook.lua", "single_flight_frontend_hook.lua",
    'build_dirichlet_patch_operating_pa.lua', 'export_detached_standalone_pa.lua', 'export_standalone_pa.lua', 'audit_frontend_working_fields.lua', 'audit_downstream_fields.lua',
    "gem2pa_geometry.lua", "build_frontend_geometry.lua", "build_geometry_iob.lua", "iob_core.lua",
    "build_flight_tube_variant.lua", "build_detector_variant.lua", "build_reflectron_variant.lua",
    "export_paired_accelerator_field.lua", "paired_accelerator_pulse.lua",
})


def native_resource_path(name: str) -> Path:
    if name not in NATIVE_RESOURCES:
        raise ValueError(f"unsupported SIMION native resource: {name}")
    resource = files("msplatform.backends.simion").joinpath("resources", name)
    if not resource.is_file():
        raise FileNotFoundError(f"installed SIMION native resource is missing: {name}")
    return Path(str(resource))


def gem_template_path(role: str, *, source_root: Path | None = None) -> Path:
    """Read the installed resource or an explicit contained frozen source tree.

    An explicit source tree is authoritative: absence never falls back to the
    installed package. Preserve its execution-alias spelling in native argv.
    """
    try:
        name = GEM_TEMPLATES[role]
    except (KeyError, TypeError) as error:
        raise ValueError(f"unsupported downstream GEM role: {role}") from error
    if source_root is None:
        resource = files("msplatform.backends.simion").joinpath("resources", name)
    else:
        root = Path(source_root).absolute()
        canonical_root = root.resolve(strict=True)
        if not canonical_root.is_dir():
            raise ValueError("frozen SIMION source root must be a directory")
        resource = root / "src/msplatform/backends/simion/resources" / name
        if not resource.resolve().is_relative_to(canonical_root):
            raise ValueError("SIMION GEM resource escapes the frozen snapshot")
    if not resource.is_file():
        origin = "installed" if source_root is None else "frozen"
        raise FileNotFoundError(f"{origin} SIMION GEM resource is missing: {name}")
    return Path(str(resource))


def gem_template_text(role: str) -> str:
    return gem_template_path(role).read_bytes().decode("utf-8")


STRUCTURAL_SEEDS = {
    4: (20940, "437d67349bccc25b63da2befe79b5c1b78448a150c768277515e6a2adf5f6daa"),
    5: (20968, "b881934c94008d2b3404595d08607e599e63ca712857453d10772a310362f606"),
}


def structural_seed_path(instance_count: int) -> Path:
    """Read a registered structural template, never a solved field or author PA."""
    if type(instance_count) is not int or instance_count not in STRUCTURAL_SEEDS:
        raise ValueError(f"unsupported SIMION structural seed count: {instance_count}")
    name = f"{instance_count}_instance_seed.iob"
    resource = files("msplatform.backends.simion").joinpath("resources", name)
    if not resource.is_file():
        raise FileNotFoundError(f"installed SIMION structural seed is missing: {name}")
    content = resource.read_bytes()
    if (len(content), hashlib.sha256(content).hexdigest()) != STRUCTURAL_SEEDS[instance_count]:
        raise ValueError(f"installed SIMION structural seed identity differs: {name}")
    return Path(str(resource))
