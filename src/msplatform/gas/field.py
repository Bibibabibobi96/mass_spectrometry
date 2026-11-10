"""Pure static uniform, piecewise and legacy-policy r-z gas sampling."""
from __future__ import annotations
from dataclasses import dataclass
import math
from msplatform.contracts.gas import (AxisymmetricRZData, BoxDomain, CylindricalDomain,
    GasFieldSpec, GasSample, GasState, UnboundedDomain)
from msplatform.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform
from .thermodynamics import number_density_m3


def _inside(domain, point):
    x, y, z = point
    if isinstance(domain, UnboundedDomain):
        return True
    if isinstance(domain, CylindricalDomain):
        return domain.minimum_z_mm <= z <= domain.maximum_z_mm and math.hypot(x, y) <= domain.maximum_radius_mm
    return all((v > lo or (closed_lo and v == lo)) and (v < hi or (closed_hi and v == hi))
               for v, lo, hi, closed_lo, closed_hi in zip(point, domain.minimum_mm, domain.maximum_mm, domain.lower_closed, domain.upper_closed))


def _overlap(a: BoxDomain, b: BoxDomain) -> bool:
    for i in range(3):
        lo, hi = max(a.minimum_mm[i], b.minimum_mm[i]), min(a.maximum_mm[i], b.maximum_mm[i])
        if lo > hi:
            return False
        if lo == hi:
            owns_a = (lo != a.minimum_mm[i] or a.lower_closed[i]) and (lo != a.maximum_mm[i] or a.upper_closed[i])
            owns_b = (lo != b.minimum_mm[i] or b.lower_closed[i]) and (lo != b.maximum_mm[i] or b.upper_closed[i])
            if not owns_a or not owns_b:
                return False
    return True


@dataclass(frozen=True)
class GasField:
    spec: GasFieldSpec
    data: AxisymmetricRZData | None


def prepare_gas_field(spec: GasFieldSpec, *, data: AxisymmetricRZData | None = None) -> GasField:
    if not isinstance(spec, GasFieldSpec):
        raise ValueError("a typed GasFieldSpec is required")
    if spec.representation == "axisymmetric_rz_grid":
        if not isinstance(data, AxisymmetricRZData):
            raise ValueError("r-z representation requires explicit validated data")
        if isinstance(spec.domain, UnboundedDomain):
            raise ValueError("r-z data cannot claim unbounded coverage")
        if isinstance(spec.domain, CylindricalDomain):
            if (data.r_values_mm[0] != 0 or spec.domain.maximum_radius_mm > data.r_values_mm[-1]
                    or spec.domain.minimum_z_mm < data.z_values_mm[0] or spec.domain.maximum_z_mm > data.z_values_mm[-1]):
                raise ValueError("r-z data does not cover the declared domain")
        else:
            raise ValueError("r-z data requires its cylindrical envelope")
    elif data is not None:
        raise ValueError("non-grid gas must not carry grid data")
    for i, a in enumerate(spec.regions):
        for b in spec.regions[i+1:]:
            if _overlap(a.domain, b.domain):
                raise ValueError("gas regions overlap without a unique boundary owner")
    return GasField(spec, data)


def _grid_state(data: AxisymmetricRZData, point) -> GasState:
    x, y, z = point
    r = math.hypot(x, y)
    nr, nz = len(data.r_values_mm), len(data.z_values_mm)
    xr = (r-data.r_values_mm[0])/(data.r_values_mm[1]-data.r_values_mm[0])
    xz = (z-data.z_values_mm[0])/(data.z_values_mm[1]-data.z_values_mm[0])
    ir, iz = math.floor(xr), math.floor(xz)
    if ir >= nr-1:
        ir, xr = nr-2, nr-1
    if iz >= nz-1:
        iz, xz = nz-2, nz-1
    fr, fz = xr-ir, xz-iz
    indices = (iz*nr+ir, iz*nr+ir+1, (iz+1)*nr+ir, (iz+1)*nr+ir+1)
    weights = ((1-fr)*(1-fz), fr*(1-fz), (1-fr)*fz, fr*fz)
    total = sum(w for i, w in zip(indices, weights) if data.fluid_mask[i])
    if total <= 0:
        return GasState("no_data")
    def value(values):
        return sum(w*values[i] for i, w in zip(indices, weights) if data.fluid_mask[i])/total
    vr, vz = value(data.radial_velocity_m_s), value(data.axial_velocity_m_s)
    velocity = (0., 0., vz) if r == 0 else (vr*x/r, vr*y/r, vz)
    return GasState("gas", value(data.pressure_pa), value(data.temperature_k), velocity)


def sample_gas(field: GasField, position: FramedPosition, *, placement: RigidTransform | None = None) -> GasSample:
    """Sample in mm; rotate m/s vectors only. Static fields require no epoch."""
    spec = field.spec
    if placement is None:
        if position.frame_id != spec.frame_id:
            raise ValueError("gas query frame differs; explicit placement required")
        local = position
    else:
        if placement.from_frame_id != spec.frame_id:
            raise ValueError("placement must start in the gas field frame")
        local = placement.inverse().transform_position(position)
    region_id = None
    if not _inside(spec.domain, local.coordinates_mm):
        state = GasState("outside_domain")
    elif spec.representation == "uniform":
        state = spec.uniform_state
    elif spec.representation == "piecewise_uniform":
        state = spec.background_state
        for region in spec.regions:
            if _inside(region.domain, local.coordinates_mm):
                state, region_id = region.state, region.region_id
                break
    else:
        state = _grid_state(field.data, local.coordinates_mm)
    if placement is not None and state.bulk_velocity_m_s is not None:
        velocity = placement.transform_vector(FramedVector(spec.frame_id, state.bulk_velocity_m_s)).components
        state = GasState(state.status, state.pressure_pa, state.temperature_k, velocity)
    density = (number_density_m3(state.pressure_pa, state.temperature_k) if state.status == "gas"
               else 0. if state.status == "vacuum" else None)
    return GasSample(state, position.frame_id, region_id, spec.composition_id, density)
