"""Validate the single full-device piecewise-swept RF mesh experiment."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];PATH=ROOT/"config"/"rf_piecewise_swept_mesh_candidate.json"
def validate(path:Path=PATH)->dict:
    c=json.loads(path.read_text(encoding="utf-8"));g=json.loads((ROOT/c["inputs"]["resolved_geometry"]).read_text(encoding="utf-8"))["geometry_mm"]
    if c.get("schema_version")!=1 or c.get("status")!="closed_after_topology_incompatibility":raise ValueError("piecewise swept closure identity invalid")
    expected=[0.0,float(g["entrance_plate_z_min"]),float(g["entrance_plate_z_max"]),float(g["rod_z_min"]),float(g["rod_z_min"])+4.0,float(g["rod_z_max"])-4.0,float(g["rod_z_max"]),float(g["exit_enclosure_z_min"]),float(g["exit_enclosure_front_wall_end_z"])]
    if c["geometry_mm"]["segment_boundaries_z"]!=expected:raise ValueError("piecewise swept axial topology is stale")
    if c["geometry_mm"]["fine_core_radius"]!=8.0 or c["transverse_mesh"]["fine_core_and_rod_boundary_hmax_mm"]!=0.2:raise ValueError("piecewise swept transverse mesh changed")
    axial=c["axial_mesh"]
    if axial["coarse_layer_count_by_segment"]!=[5,4,20,20,40,20,20,4] or axial["fine_layer_count_by_segment"]!=[10,8,40,40,40,40,40,8]:raise ValueError("piecewise swept layer profiles changed")
    if c["decision"].get("third_mesh_profile_allowed") is not False:raise ValueError("piecewise swept experiment must stop after two profiles")
    if c["decision"].get("further_topology_repairs_allowed") is not False:raise ValueError("piecewise swept strategy must remain closed")
    return c
if __name__=="__main__":validate();print("RF_PIECEWISE_SWEPT_MESH=PASS STATUS=closed FURTHER_REPAIRS=false")
