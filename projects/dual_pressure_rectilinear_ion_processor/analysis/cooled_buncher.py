"""HP-end cooler/buncher CSG provider and actual-field diagnostic theory.

This optional component retains the original guide/source and reuses IP HP
metal. The terminal well and axial gate are new design assumptions, not a
reconstruction of the published LP extractor. All fields must be solved from
the assembled electrodes; fitted/pseudopotential values never drive ions.
"""
from __future__ import annotations

import copy
import itertools
import math
from typing import Any

import numpy as np
import pandas as pd

from common.contracts.particle_physics import (
    AMU_KG, BOLTZMANN_CONSTANT_J_K, ELEMENTARY_CHARGE_C,
)
from common.contracts.rigid_transform import FramedPosition, RigidTransform
from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import shape_bounds
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import (
    native_projection, render_projection_electrodes,
)

BUNCHER_ELECTRODE_NAMES = (
    "hp_rf_a", "hp_rf_b", "hp_auxiliary", "entrance_gate", "hp_shield",
    "end_inner_auxiliary", "exit_gate",
)


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


def _axial_shape(shape: dict, *, old_center: float, new_center: float, scale: float) -> dict:
    result = copy.deepcopy(shape)
    def mapped(value):
        return new_center + scale * (value-old_center)
    if shape["shape"] == "box":
        result["min_mm"][0] = mapped(shape["min_mm"][0])
        result["max_mm"][0] = mapped(shape["max_mm"][0])
    elif shape["shape"] == "cylinder_x":
        result["x_min_mm"] = mapped(shape["x_min_mm"])
        result["x_max_mm"] = mapped(shape["x_max_mm"])
    elif shape["shape"] == "convex_polyhedron":
        for point in result["vertices_mm"]:
            point[0] = mapped(point[0])
    else:
        raise ValueError("unsupported native CSG axial placement")
    return result


def _bounds(electrodes: list[dict]) -> tuple[list[float], list[float]]:
    bounds = [shape_bounds(s) for e in electrodes for s in e["solids"]]
    return np.min([b[0] for b in bounds], axis=0).tolist(), np.max([b[1] for b in bounds], axis=0).tolist()


def _world_bounds(low: list[float], high: list[float], pose: RigidTransform) -> dict:
    points = [pose.transform_position(FramedPosition(pose.from_frame_id, p)).coordinates_mm
              for p in itertools.product(*zip(low, high))]
    return dict(min_mm=np.min(points, axis=0).tolist(), max_mm=np.max(points, axis=0).tolist())


def _validate_inner_clearance(inner: dict, retained: list[dict], start: float, stop: float) -> None:
    """Conservative solid-bound test: reject overlap, never shave the metal."""
    for shape in inner["solids"]:
        a, b = np.asarray(shape_bounds(shape), dtype=float)
        if not start < a[0] < b[0] < stop:
            raise ValueError("end inner auxiliary must fit inside the finite HP RF length")
        for electrode in retained:
            for other in electrode["solids"]:
                c, d = np.asarray(shape_bounds(other), dtype=float)
                if np.all(np.maximum(a, c) < np.minimum(b, d)):
                    raise ValueError(f"end inner auxiliary overlaps {electrode['name']}")


def build_cooled_buncher_contract(
    resolved_model: dict, *, guide_contract: dict, native_to_assembly: dict,
    request: dict, electrode_ids: dict[str, int],
) -> dict:
    """Return actual native CSG, MR pose/ports and gas-domain semantics.

    Consumes caller-verified frozen inputs and performs no file I/O, Refine,
    source generation or particle filtering. Missing/unknown geometry, reused
    IDs, non-native MR poses and overlapping new inner metal fail closed.
    """
    if set(request) != {"schema_version", "role", "inner_center_inset_mm", "inner_length_mm"}:
        raise ValueError("cooled buncher request fields differ")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1 or request["role"] != "ion_processor_hp_end_buncher_request":
        raise ValueError("unsupported cooled buncher request")
    inset = _number(request["inner_center_inset_mm"], "inner center inset", positive=True)
    length = _number(request["inner_length_mm"], "inner length", positive=True)
    if set(electrode_ids) != set(BUNCHER_ELECTRODE_NAMES) or any(type(i) is not int or i <= 0 for i in electrode_ids.values()):
        raise ValueError("seven named positive physical electrode IDs required")
    if len(set(electrode_ids.values())) != len(electrode_ids):
        raise ValueError("cooled buncher physical IDs must be distinct")
    model = resolved_model
    baseline, numerics = model["baseline"], model["numerics"]
    projection = native_projection(baseline, numerics)
    source = {e["electrode_id"]: e for e in projection["electrodes"]}
    pose = RigidTransform.from_contract(native_to_assembly)
    if pose.to_frame_id != "mrtof_global_cartesian":
        raise ValueError("cooled buncher destination must be the declared MR assembly frame")
    if pose.from_frame_id != projection["frame_id"] or not np.allclose(np.asarray(pose.rotation)[:, 0], [0, 1, 0]):
        raise ValueError("HP native axis must be the retained guide's global +y axis")
    electric, clock = baseline["electric"], baseline["clock"]
    if (guide_contract["drive"]["waveform"] != "cosine" or
            guide_contract["drive"]["frequency_hz"] != electric["rf_frequency_hz"] or
            guide_contract["drive"]["phase_rad"] != clock["rf_phase_rad"]):
        raise ValueError("single differential RF response requires phase-locked guide and HP drives")
    hp_amplitude = _number(electric["rf_peak_to_peak_v"], "HP RF peak-to-peak voltage", positive=True)/2
    guide_amplitude = _number(guide_contract["drive"]["rf_amplitude_v"], "guide RF peak amplitude", positive=True)
    g, n = baseline["geometry"], baseline["native_geometry"]
    start, stop = g["guide_length_mm"], g["guide_length_mm"]+g["hp_length_mm"]
    center = stop-inset
    retained = []
    for name, old_id in zip(BUNCHER_ELECTRODE_NAMES[:5], (3, 4, 9, 12, 15), strict=True):
        electrode = copy.deepcopy(source[old_id])
        electrode.update(name=name, electrode_id=electrode_ids[name])
        retained.append(electrode)
    inner = copy.deepcopy(source[11])
    inner.update(name="end_inner_auxiliary", electrode_id=electrode_ids["end_inner_auxiliary"])
    inner["solids"] = [_axial_shape(s, old_center=g["lp_center_mm"], new_center=center,
                                    scale=length/(2*n["lp_inner_half_length_x_mm"])) for s in inner["solids"]]
    inner["cutouts"] = []
    _validate_inner_clearance(inner, retained, start+n["segment_end_gap_mm"], stop-n["segment_end_gap_mm"])
    gate = copy.deepcopy(source[12])
    gate.update(name="exit_gate", electrode_id=electrode_ids["exit_gate"])
    shift_center = stop+n["lens_thickness_mm"]/2
    for key in ("solids", "cutouts"):
        gate[key] = [_axial_shape(s, old_center=start-n["lens_thickness_mm"]/2,
                                  new_center=shift_center, scale=1.) for s in gate[key]]
    electrodes = [*retained, inner, gate]
    low, high = _bounds(electrodes)
    def world(point):
        return list(pose.transform_position(FramedPosition(pose.from_frame_id, point)).coordinates_mm)
    return dict(
        schema_version=1, role="ion_processor_hp_end_buncher_provider", frame_id="mrtof_global_cartesian",
        native_projection_fragment=dict(frame_id=projection["frame_id"], electrodes=electrodes),
        native_to_mr=pose.to_contract(), electrode_ids=dict(electrode_ids),
        bounds_native_mm=dict(min_mm=low, max_mm=high), bounds_mr_mm=_world_bounds(low, high, pose),
        geometry=dict(hp_start_native_x_mm=start, hp_end_native_x_mm=stop,
                      entrance_face_native_x_mm=start-n["lens_thickness_mm"],
                      gate_thickness_mm=n["lens_thickness_mm"], aperture_radius_mm=n["entrance_aperture_diameter_mm"]/2,
                      trap_center_native_mm=[center, 0., 0.], trap_center_mr_mm=world([center, 0., 0.]),
                      entrance_center_mr_mm=world([start, 0., 0.]),
                      exit_face_native_x_mm=stop+n["lens_thickness_mm"],
                      exit_face_center_mr_mm=world([stop+n["lens_thickness_mm"], 0., 0.]),
                      inner_center_inset_mm=inset, inner_length_mm=length),
        gas=dict(parameters=copy.deepcopy(baseline["gas"]),
                 domain_native_mm=dict(x_min=start, x_max=stop, transverse_halfwidth=g["r0_mm"]),
                 boundary_policy="x_start_inclusive_end_exclusive__abs_transverse_strictly_less_than_r0",
                 model="prescribed_HS1_bath_not_gas_flow_solution"),
        drive=dict(waveform="cosine", frequency_hz=electric["rf_frequency_hz"], phase_rad=clock["rf_phase_rad"],
                   rf_amplitude_v=hp_amplitude, hp_to_guide_amplitude_ratio=hp_amplitude/guide_amplitude,
                   group_polarities=dict(hp_rf_a=1, hp_rf_b=-1)),
        source_policy="original_births_IDs_and_instrument_clock_unchanged__no_handoff_survivor_source",
        assumptions=["HP RF/corner auxiliary/entrance/shield retained from native_projection",
                     "Terminal well is a new design: symmetric original LP inner sheets moved/scaled axially inside HP",
                     "Axial exit gate duplicates the finite entrance lens/aperture at the HP end",
                     "No LP outer sheets: they would intersect unsplit HP RF plates",
                     "Well stability, barriers and release energy require actual assembled field probes"],
    )


def export_cooled_buncher_assembly_interface(contract: dict, guide_contract: dict) -> dict:
    """Publish local finite gate faces and physical metal IDs; never a PA boundary."""
    geometry = contract["geometry"]
    ports = {}
    for name, center, normal in (
        ("entrance_gate_outer_face", geometry["entrance_face_native_x_mm"], [-1, 0, 0]),
        ("exit_gate_outer_face", geometry["exit_face_native_x_mm"], [1, 0, 0]),
    ):
        ports[name] = dict(surface_kind="aperture_outer_face", center_mm=[center, 0, 0],
                           outward_normal=normal, wall_thickness_mm=geometry["gate_thickness_mm"],
                           cross_section=dict(shape="circle", radius_mm=geometry["aperture_radius_mm"]))
    return dict(schema_version=1, role="component_geometry_interface",
                project_id="dual_pressure_rectilinear_ion_processor", variant_id="hp_end_cooler",
                geometry_profile_id=None, local_frame_id=contract["native_projection_fragment"]["frame_id"],
                length_unit="mm", ports=ports,
                component_electrodes=[
                    *[dict(component_electrode_id=r["physical_electrode_id"], role="guide_rod",
                           electrical_group_id=r["electrode_group"]) for r in guide_contract["rod_array"]["rods"]],
                    *[dict(component_electrode_id=i, role=name) for name, i in contract["electrode_ids"].items()],
                ])


def render_cooled_buncher_gem_fragment(contract: dict) -> str:
    """Return native-frame e/fill metal body; caller applies native_to_mr once."""
    if contract.get("role") != "ion_processor_hp_end_buncher_provider" or contract.get("schema_version") != 1:
        raise ValueError("unsupported cooled buncher provider")
    return render_projection_electrodes(contract["native_projection_fragment"])


def prepare_buncher_probe_points(contract: dict, offsets_mm: list[float]) -> list[dict]:
    """Create a full Cartesian local stencil in MR mm around the proposed well.

    Offsets are explicit numerical inputs, not a hidden sampling resolution.
    The consumer samples both actual DC potential and unit-RF electric field.
    """
    offsets = [_number(v, "probe offset") for v in offsets_mm]
    if len(set(offsets)) != len(offsets) or len(offsets) < 3 or min(offsets) >= 0 or max(offsets) <= 0:
        raise ValueError("probe stencil requires distinct offsets on both sides of zero")
    center = contract["geometry"]["trap_center_mr_mm"]
    return [dict(point_id=i, **{f"{axis}_mm": center[k]+delta[k] for k, axis in enumerate("xyz")})
            for i, delta in enumerate(itertools.product(offsets, repeat=3))]


def _rf_pseudopotential_ev(fields_v_per_mm: np.ndarray, mass_kg: float, charge: int,
                          frequency_hz: float, amplitude_v: float) -> np.ndarray:
    # Q虏 E虏/(4m 惟虏), with measured unit-voltage fields scaled to peak V/m;
    # divide the result by the elementary charge to report energy in eV.
    return charge**2*ELEMENTARY_CHARGE_C*amplitude_v**2*np.sum(fields_v_per_mm**2, axis=1)*1e6/(4*mass_kg*(2*math.pi*frequency_hz)**2)


def analyze_buncher_field_samples(
    samples: pd.DataFrame, *, center_mr_mm: list[float], mass_amu: float, charge_state: int,
    temperature_k: float, rf_frequency_hz: float, rf_peak_amplitude_v: float,
) -> dict:
    """Fit actual DC+RF effective-energy curvature; never prescribe a field.

    Columns: MR x/y/z_mm, dc_potential_v, and unit_rf_ex/ey/ez_v_per_mm
    for a 1 V alternating RF electrode response. The pseudopotential assumes
    adiabatic single-frequency motion; positive fitted curvature is a local
    diagnostic, not global capture, exact RF stability or space-charge proof.
    """
    columns = ["x_mm", "y_mm", "z_mm", "dc_potential_v", *[f"unit_rf_e{a}_v_per_mm" for a in "xyz"]]
    values = samples[columns].to_numpy(dtype=float)
    if len(values) < 10 or not np.isfinite(values).all():
        raise ValueError("finite actual field samples and a full quadratic stencil required")
    center = np.asarray(center_mr_mm, dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("finite MR fit center required")
    mass = _number(mass_amu, "mass", positive=True)*AMU_KG
    temperature = _number(temperature_k, "temperature", positive=True)
    frequency = _number(rf_frequency_hz, "RF frequency", positive=True)
    amplitude = _number(rf_peak_amplitude_v, "RF peak amplitude", positive=True)
    if type(charge_state) is not int or charge_state == 0:
        raise ValueError("nonzero integer charge state required")
    xyz = values[:, :3]-center
    x, y, z = xyz.T
    design = np.column_stack((np.ones(len(x)), x, y, z, x*x/2, x*y, x*z, y*y/2, y*z, z*z/2))
    pseudo = _rf_pseudopotential_ev(values[:, 4:], mass, charge_state, frequency, amplitude)
    energy = charge_state*values[:, 3]+pseudo
    coeff, _, rank, _ = np.linalg.lstsq(design, energy, rcond=None)
    if rank != 10:
        raise ValueError("actual field stencil does not identify the full 3D quadratic")
    hessian = np.array([[coeff[4], coeff[5], coeff[6]], [coeff[5], coeff[7], coeff[8]], [coeff[6], coeff[8], coeff[9]]])
    eigen = np.linalg.eigvalsh(hessian)
    stable = bool(np.all(eigen > 0))
    covariance = BOLTZMANN_CONSTANT_J_K*temperature/ELEMENTARY_CHARGE_C*np.linalg.inv(hessian) if stable else None
    equilibrium = center-np.linalg.solve(hessian, coeff[1:4]) if stable else None
    low, high = values[:, :3].min(axis=0), values[:, :3].max(axis=0)
    inside = bool(stable and np.all(low <= equilibrium) and np.all(equilibrium <= high))
    return dict(role="actual_field_local_buncher_curvature", sample_count=len(values),
                center_mr_mm=center.tolist(), effective_energy_hessian_ev_per_mm2=hessian.tolist(),
                effective_energy_gradient_ev_per_mm=coeff[1:4].tolist(), eigenvalues_ev_per_mm2=eigen.tolist(),
                locally_positive_effective_curvature=stable,
                fit_sample_bounds_mr_mm=dict(min_mm=low.tolist(), max_mm=high.tolist()),
                equilibrium_within_sample_bounds=inside,
                equilibrium_mr_mm=equilibrium.tolist() if stable else None,
                thermal_position_covariance_mm2=covariance.tolist() if stable else None,
                thermal_sigma_xyz_mm=np.sqrt(np.diag(covariance)).tolist() if stable else None,
                fit_residual_sigma_ev=float(np.sqrt(np.mean((energy-design@coeff)**2))),
                rf_pseudopotential_ev_range=[float(pseudo.min()), float(pseudo.max())],
                scope="local adiabatic thermal diagnostic; not a prescribed field or global capture qualification")


def analyze_buncher_axial_barriers(
    profile: pd.DataFrame, *, well_center_y_mm: float, mass_amu: float,
    charge_state: int, temperature_k: float, rf_frequency_hz: float, rf_peak_amplitude_v: float,
) -> dict:
    """Measure two barriers on an actual-field axial line, not 3D escape saddles.

    Uses the same measured DC and unit-RF columns as the 3D fit. Linear
    interpolation is confined to the supplied y domain. Both sides of the
    requested reference well must be sampled; negative barriers are reported,
    not clamped to manufacture capture.
    """
    columns = ["y_mm", "dc_potential_v", *[f"unit_rf_e{a}_v_per_mm" for a in "xyz"]]
    values = profile[columns].to_numpy(dtype=float)
    center = _number(well_center_y_mm, "well center")
    mass = _number(mass_amu, "mass", positive=True)*AMU_KG
    temperature = _number(temperature_k, "temperature", positive=True)
    frequency = _number(rf_frequency_hz, "RF frequency", positive=True)
    amplitude = _number(rf_peak_amplitude_v, "RF amplitude", positive=True)
    if type(charge_state) is not int or charge_state == 0:
        raise ValueError("nonzero integer charge state required")
    if len(values) < 3 or not np.isfinite(values).all():
        raise ValueError("finite axial field profile required")
    y = values[:, 0]
    if not np.all(np.diff(y) > 0) or not y[0] < center < y[-1]:
        raise ValueError("axial profile must be increasing and bracket the well")
    pseudo = _rf_pseudopotential_ev(values[:, 2:], mass, charge_state, frequency, amplitude)
    energy = charge_state*values[:, 1]+pseudo
    reference = float(np.interp(center, y, energy))
    left = float(energy[y < center].max()-reference)
    right = float(energy[y > center].max()-reference)
    kt_ev = BOLTZMANN_CONSTANT_J_K*temperature/ELEMENTARY_CHARGE_C
    return dict(role="actual_field_axial_line_barriers", reference_y_mm=center, reference_effective_energy_ev=reference,
                upstream_line_barrier_ev=left, downstream_line_barrier_ev=right,
                upstream_line_barrier_over_kbt=left/kt_ev, downstream_line_barrier_over_kbt=right/kt_ev,
                sample_y_mm=y.tolist(), effective_energy_ev=energy.tolist(),
                scope="sampled axial line only; not minimum 3D escape saddles, dynamic capture or measured cooling time")
