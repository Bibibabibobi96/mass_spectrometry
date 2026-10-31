"""Bind the existing OA workflow's actual release and pure geometry definition."""
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.component_focus_workflow import _load_release, _load_request
from projects.orthogonal_accelerator.analysis.two_zone_geometry import load_geometry_profile


def resolve_execution_binding(repo_root: Path, project_id: str, bindings: dict[str, str],
                              *, request_path: Path | None = None) -> dict[str, Any]:
    if project_id != "orthogonal_accelerator":
        raise ValueError("OA execution binding project identity differs")
    request = _load_request(Path(bindings["component_request_path"]))
    release = _load_release(Path(bindings["release_spec_path"]))
    load_geometry_profile(request["geometry_profile_id"])
    contract = repo_root/"projects"/project_id/"config/component_contract.json"
    return dict(project_id=project_id, structural_variant_id="two_zone", authorized_run_id=None,
                operating_points=[dict(mass=dict(value=release["species"]["mass_amu"], unit="Da"),
                                       charge_state=release["species"]["charge_state"])],
                input_paths=[str(contract.resolve())])
