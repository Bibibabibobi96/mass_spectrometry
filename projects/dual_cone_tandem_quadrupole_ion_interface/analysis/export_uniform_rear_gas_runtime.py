"""Compile the declared uniform 400 Pa rear-gas prototype into a SIMION Lua field."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = PROJECT_ROOT / "config" / "uniform_rear_gas_field.json"
DEFAULT_INTERFACE = PROJECT_ROOT / "config" / "gas_field_interface.json"


def _load(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("role") != role:
        raise ValueError(f"unexpected contract role: {path}")
    return value


def export_uniform_runtime(
    output_lua: Path,
    output_manifest: Path,
    *,
    spec_path: Path = DEFAULT_SPEC,
    interface_path: Path = DEFAULT_INTERFACE,
) -> dict[str, Any]:
    spec = _load(spec_path, "dual_cone_uniform_rear_gas_field")
    interface = _load(interface_path, "dual_cone_simion_gas_field_interface")
    contract = interface["runtime_artifact_contract"]
    domain = contract["domain"]
    rear = spec["rear_region"]
    upstream = spec["upstream_collision_proxy"]
    if rear["pressure_pa"] != 400.0:
        raise ValueError("the frozen minimal prototype requires a 400 Pa rear region")
    if not (domain["minimum_z_mm"] <= rear["start_z_mm"] <= domain["maximum_z_mm"]):
        raise ValueError("rear-region start lies outside the gas-field domain")

    lua = f"""-- Generated from uniform_rear_gas_field.json; qualitative prototype only.
local field = {{role=[[{contract['lua_role']}]]}}
local z_min, z_max = {domain['minimum_z_mm']:.17g}, {domain['maximum_z_mm']:.17g}
local r_max = {domain['maximum_radius_mm']:.17g}
local boundary_tolerance_mm = 1e-6
local z_rear = {rear['start_z_mm']:.17g}
local p_rear, p_upstream = {rear['pressure_pa']:.17g}, {upstream['pressure_pa']:.17g}
local temperature = {rear['temperature_k']:.17g}
local uz_rear, ur_rear = {rear['axial_velocity_m_per_s']:.17g}, {rear['radial_velocity_m_per_s']:.17g}
local function check(x, y, z)
  local r = math.sqrt(x*x + y*y)
  assert(z >= z_min-boundary_tolerance_mm and z <= z_max+boundary_tolerance_mm and
    r <= r_max+boundary_tolerance_mm,
    string.format('gas-field query outside declared domain: x=%.9g y=%.9g z=%.9g r=%.9g', x,y,z,r))
  return r
end
field.pressure_pa = function(x, y, z)
  check(x, y, z); return z >= z_rear and p_rear or p_upstream
end
field.temperature_k = function(x, y, z)
  check(x, y, z); return temperature
end
field.velocity_m_s = function(x, y, z)
  check(x, y, z)
  if z < z_rear then return 0, 0, 0 end
  local r = math.sqrt(x*x + y*y)
  if r == 0 then return 0, 0, uz_rear end
  return ur_rear*x/r, ur_rear*y/r, uz_rear
end
return field
"""
    output_lua = output_lua.resolve()
    output_manifest = output_manifest.resolve()
    output_lua.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_lua.write_text(lua, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": contract["manifest_schema_version"],
        "role": contract["manifest_role"],
        "project_id": interface["project_id"],
        "coordinate_frame": contract["coordinate_frame"],
        "domain": domain,
        "runtime_lua": {"path": str(output_lua), "sha256": file_sha256(output_lua)},
    }
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-lua", required=True, type=Path)
    parser.add_argument("--output-manifest", required=True, type=Path)
    args = parser.parse_args()
    export_uniform_runtime(args.output_lua, args.output_manifest)
    print(f"UNIFORM_REAR_GAS_RUNTIME=PASS MANIFEST={args.output_manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
