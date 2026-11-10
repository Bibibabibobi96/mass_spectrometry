"""Explicit installed execution resources; no author-tree lookup."""
from importlib.resources import files
from pathlib import Path


RESOURCE_NAMES = frozenset({"frozen_python_package.ps1", "host_execution_lease.ps1", "resource_process_support.ps1", "process_owner.ps1", "native_run_path.lua", "host_resource_policy.json", "artifact_retention.json", "artifact_capacity_policy.json", "run_paths.ps1", "run_paths_owner.ps1", "payload_file_support.ps1", "payload_materialize_owner.ps1", "simion_dispatch_support.ps1", "batch_process_owner.ps1"})


def resource_path(name: str) -> Path:
    """Locate one declared installed script; absent resources fail closed."""
    if name not in RESOURCE_NAMES:
        raise ValueError(f"Unknown execution resource: {name}")
    path = Path(str(files(__package__).joinpath(name)))
    if not path.is_file():
        raise FileNotFoundError(f"Required installed execution resource is missing: {name}")
    return path
