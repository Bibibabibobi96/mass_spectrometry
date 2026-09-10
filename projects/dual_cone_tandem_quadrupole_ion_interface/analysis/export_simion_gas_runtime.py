"""Compile a validated COMSOL r-z export into a self-contained SIMION Lua field."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.validate_gas_field import (
    validate_gas_field,
)


PROJECT_ID = "dual_cone_tandem_quadrupole_ion_interface"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lua_number(value: str) -> str:
    number = float(value)
    return f"{number:.9g}" if math.isfinite(number) else "false"


def _lua_array(rows: list[dict[str, str]], field: str) -> str:
    return ",".join(_lua_number(row[field]) for row in rows)


def _lua_chunked_array(
    rows: list[dict[str, str]], field: str, *, chunk_size: int
) -> str:
    """Keep each Lua 5.1 function prototype below its constant-table limit."""
    chunks = []
    for start in range(0, len(rows), chunk_size):
        values = _lua_array(rows[start : start + chunk_size], field)
        chunks.append(f"(function() return {{{values}}} end)()")
    return "{\n  " + ",\n  ".join(chunks) + "\n}"


def export_runtime(
    csv_path: Path,
    metadata_path: Path,
    output_lua: Path,
    output_manifest: Path,
    science_path: Path,
    numerics_path: Path,
    geometry_path: Path,
    interface_path: Path,
) -> dict[str, Any]:
    """Validate the COMSOL result, then emit bilinear axisymmetric lookup code."""
    validation = validate_gas_field(
        csv_path, metadata_path, science_path, numerics_path, geometry_path
    )
    metadata = _load(metadata_path)
    interface = _load(interface_path)
    contract = interface["runtime_artifact_contract"]
    if validation["status"] != "PASS":
        raise ValueError("COMSOL gas field did not pass validation")

    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    r_values = [float(value) for value in metadata["grid"]["r_values_mm"]]
    z_values = [float(value) for value in metadata["grid"]["z_values_mm"]]
    if len(r_values) < 2 or len(z_values) < 2:
        raise ValueError("SIMION runtime interpolation requires at least a 2 x 2 grid")
    dr = r_values[1] - r_values[0]
    dz = z_values[1] - z_values[0]
    tolerance = 1e-9
    if any(abs((b - a) - dr) > tolerance for a, b in zip(r_values, r_values[1:])):
        raise ValueError("SIMION runtime requires a uniform radial grid")
    if any(abs((b - a) - dz) > tolerance for a, b in zip(z_values, z_values[1:])):
        raise ValueError("SIMION runtime requires a uniform axial grid")

    domain = contract["domain"]
    if domain["minimum_z_mm"] < z_values[0] or domain["maximum_z_mm"] > z_values[-1]:
        raise ValueError("validated COMSOL field does not cover the governed axial domain")
    if domain["minimum_radius_mm"] < r_values[0] or domain["maximum_radius_mm"] > r_values[-1]:
        raise ValueError("validated COMSOL field does not cover the governed radial domain")

    # The arrays are embedded deliberately: the manifest has one immutable runtime
    # dependency, so SIMION cannot silently read a different CSV after preparation.
    # Each field is split across child function prototypes because SIMION's Lua 5.1
    # compiler has a finite per-prototype constant table.
    chunk_size = 8192
    lua = f"""-- Generated from a validated COMSOL export.  Do not edit.
local field = {{role=[[{contract['lua_role']}]]}}
local nr,nz={len(r_values)},{len(z_values)}
local r0,z0,dr,dz={r_values[0]:.17g},{z_values[0]:.17g},{dr:.17g},{dz:.17g}
local rmin,rmax,zmin,zmax={domain['minimum_radius_mm']:.17g},{domain['maximum_radius_mm']:.17g},{domain['minimum_z_mm']:.17g},{domain['maximum_z_mm']:.17g}
local chunk_size={chunk_size}
local p={_lua_chunked_array(rows, 'p_pa', chunk_size=chunk_size)}
local t={_lua_chunked_array(rows, 'temperature_k', chunk_size=chunk_size)}
local uz={_lua_chunked_array(rows, 'u_z_m_per_s', chunk_size=chunk_size)}
local ur={_lua_chunked_array(rows, 'u_r_m_per_s', chunk_size=chunk_size)}
local function value(a,i)
  local chunk=math.floor((i-1)/chunk_size)+1
  return a[chunk][i-(chunk-1)*chunk_size]
end
local function sample(a,r,z)
  if r < rmin or r > rmax or z < zmin or z > zmax then error('gas-field query outside governed domain') end
  local xr,xz=(r-r0)/dr,(z-z0)/dz
  local ir,iz=math.floor(xr),math.floor(xz)
  if ir >= nr-1 then ir=nr-2; xr=nr-1 end
  if iz >= nz-1 then iz=nz-2; xz=nz-1 end
  local fr,fz=xr-ir,xz-iz
  local i00=iz*nr+ir+1
  local a00,a10,a01,a11=value(a,i00),value(a,i00+1),value(a,i00+nr),value(a,i00+nr+1)
  local w00,w10,w01,w11=(1-fr)*(1-fz),fr*(1-fz),(1-fr)*fz,fr*fz
  local weighted,total=0,0
  if a00 ~= false then weighted,total=weighted+w00*a00,total+w00 end
  if a10 ~= false then weighted,total=weighted+w10*a10,total+w10 end
  if a01 ~= false then weighted,total=weighted+w01*a01,total+w01 end
  if a11 ~= false then weighted,total=weighted+w11*a11,total+w11 end
  if total <= 0 then error('gas-field query has no fluid support in its interpolation cell') end
  return weighted/total
end
field.pressure_pa = function(x,y,z) return sample(p,math.sqrt(x*x+y*y),z) end
field.temperature_k = function(x,y,z) return sample(t,math.sqrt(x*x+y*y),z) end
field.velocity_m_s = function(x,y,z)
  local r=math.sqrt(x*x+y*y)
  local vr=sample(ur,r,z)
  local vz=sample(uz,r,z)
  if r == 0 then return 0,0,vz end
  return vr*x/r,vr*y/r,vz
end
return field
"""
    output_lua.parent.mkdir(parents=True, exist_ok=True)
    output_lua.write_text(lua, encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": contract["manifest_schema_version"],
        "role": contract["manifest_role"],
        "project_id": PROJECT_ID,
        "source": {
            "kind": "validated_comsol_axisymmetric_rz",
            "field_csv": {
                "path": str(csv_path.resolve()),
                "sha256": metadata["field_csv_sha256"],
            },
            "metadata": {
                "path": str(metadata_path.resolve()),
                "sha256": _sha256(metadata_path),
            },
            "source_contract_sha256": metadata["source_contract_sha256"],
        },
        "coordinate_frame": contract["coordinate_frame"],
        "domain": domain,
        "interpolation_policy": contract["interpolation_policy"],
        "runtime_lua": {
            "path": str(output_lua.resolve()),
            "sha256": _sha256(output_lua),
        },
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-lua", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--science", type=Path, default=root / "config" / "gas_flow_science.json")
    parser.add_argument("--numerics", type=Path, default=root / "config" / "comsol_solver_numerics.json")
    parser.add_argument("--geometry", type=Path, default=root / "config" / "resolved_geometry.json")
    parser.add_argument("--interface", type=Path, default=root / "config" / "gas_field_interface.json")
    args = parser.parse_args()
    export_runtime(
        args.csv,
        args.metadata,
        args.output_lua,
        args.output_manifest,
        args.science,
        args.numerics,
        args.geometry,
        args.interface,
    )
    print(f"SIMION_GAS_RUNTIME_EXPORT=PASS MANIFEST={args.output_manifest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
