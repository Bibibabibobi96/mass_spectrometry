"""Static gas inputs: no device, file, vendor or execution policy."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from msplatform.io.manifest_records import validate_file_record
import math
from typing import Literal

from .rigid_transform import FramedVector

GasStatus = Literal["gas", "vacuum", "solid", "outside_domain", "no_data"]
Vector3 = tuple[float, float, float]


def _finite(value: float, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + " must be finite")
    return float(value)


@dataclass(frozen=True)
class GasSpecies:
    species_id: str
    mass_amu: float
    mole_fraction: float

    def __post_init__(self) -> None:
        if not isinstance(self.species_id, str) or not self.species_id.strip() or _finite(self.mass_amu, "mass_amu") <= 0:
            raise ValueError("gas species identity and positive mass required")
        if not 0 < _finite(self.mole_fraction, "mole_fraction") <= 1:
            raise ValueError("mole_fraction must lie in (0,1]")


@dataclass(frozen=True)
class GasSource:
    """Actual declared source semantics and an existing, structurally valid identity.

    Reference verification/loading remains the caller/results boundary. Construction
    does not open, resolve or hash it, and never substitutes another producer.
    """
    kind: Literal["prescribed", "prescribed_proxy", "published_cfd"]
    source_id: str
    assumptions: tuple[str, ...]
    reference: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"prescribed", "prescribed_proxy", "published_cfd"}:
            raise ValueError("unsupported gas source kind")
        if not isinstance(self.source_id, str) or not self.source_id or self.source_id.strip() != self.source_id:
            raise ValueError("gas source identity must be explicit")
        if isinstance(self.assumptions, str):
            raise ValueError("gas assumptions must be an explicit sequence")
        assumptions = tuple(self.assumptions)
        if any(not isinstance(value, str) or not value or value.strip() != value for value in assumptions):
            raise ValueError("gas assumptions must be nonempty descriptions")
        if self.kind == "prescribed_proxy" and not assumptions:
            raise ValueError("prescribed proxy requires explicit approximation assumptions")
        object.__setattr__(self, "assumptions", assumptions)
        if self.reference is not None:
            record = validate_file_record(self.reference, "gas source reference")
            # The existing neutral identity is these four scalar fields. Any
            # producer metadata remains in the referenced, hash-bound document;
            # copying arbitrary nested extras here would create mutable authority.
            identity = {key: record[key] for key in ("path", "exists", "bytes", "sha256")}
            object.__setattr__(self, "reference", MappingProxyType(identity))
        elif self.kind == "published_cfd":
            raise ValueError("published CFD requires its existing complete source record")


@dataclass(frozen=True)
class GasState:
    status: GasStatus
    pressure_pa: float | None = None
    temperature_k: float | None = None
    bulk_velocity_m_s: Vector3 | None = None

    def __post_init__(self) -> None:
        if self.status not in {"gas", "vacuum", "solid", "outside_domain", "no_data"}:
            raise ValueError("unsupported gas status")
        if self.status not in {"gas", "vacuum"}:
            if any(x is not None for x in (self.pressure_pa, self.temperature_k, self.bulk_velocity_m_s)):
                raise ValueError("unavailable gas state must not contain guessed values")
            return
        pressure = _finite(self.pressure_pa, "pressure_pa")
        if (self.status == "gas" and pressure <= 0) or (self.status == "vacuum" and pressure != 0):
            raise ValueError("gas pressure must be positive; explicit vacuum pressure must be zero")
        if self.temperature_k is None:
            if self.status == "gas":
                raise ValueError("gas temperature is required")
        elif _finite(self.temperature_k, "temperature_k") <= 0:
            raise ValueError("temperature_k must be positive")
        if self.bulk_velocity_m_s is None:
            if self.status == "gas":
                raise ValueError("gas bulk velocity is required")
        else:
            object.__setattr__(self, "bulk_velocity_m_s", FramedVector("gas_values", self.bulk_velocity_m_s).components)


@dataclass(frozen=True)
class BoxDomain:
    minimum_mm: Vector3
    maximum_mm: Vector3
    lower_closed: tuple[bool, bool, bool]
    upper_closed: tuple[bool, bool, bool]

    def __post_init__(self) -> None:
        for name in ("minimum_mm", "maximum_mm"):
            object.__setattr__(self, name, FramedVector("gas_bounds", getattr(self, name)).components)
        for name in ("lower_closed", "upper_closed"):
            value = tuple(getattr(self, name))
            if len(value) != 3 or any(type(x) is not bool for x in value):
                raise ValueError("box endpoint ownership must have three booleans")
            object.__setattr__(self, name, value)
        if any(a >= b for a, b in zip(self.minimum_mm, self.maximum_mm)):
            raise ValueError("box bounds must be increasing")


@dataclass(frozen=True)
class CylindricalDomain:
    minimum_z_mm: float
    maximum_z_mm: float
    maximum_radius_mm: float

    def __post_init__(self) -> None:
        if (_finite(self.minimum_z_mm, "minimum_z_mm") >= _finite(self.maximum_z_mm, "maximum_z_mm")
                or _finite(self.maximum_radius_mm, "maximum_radius_mm") <= 0):
            raise ValueError("cylindrical bounds must be physical")


@dataclass(frozen=True)
class UnboundedDomain:
    """Explicitly selected unbounded coverage; never a default."""


@dataclass(frozen=True)
class GasRegion:
    region_id: str
    domain: BoxDomain
    state: GasState

    def __post_init__(self) -> None:
        if not self.region_id or not isinstance(self.domain, BoxDomain) or not isinstance(self.state, GasState):
            raise ValueError("piecewise gas requires a named box and explicit state")


@dataclass(frozen=True)
class AxisymmetricRZData:
    r_values_mm: tuple[float, ...]
    z_values_mm: tuple[float, ...]
    fluid_mask: tuple[bool, ...]
    pressure_pa: tuple[float | None, ...]
    temperature_k: tuple[float | None, ...]
    radial_velocity_m_s: tuple[float | None, ...]
    axial_velocity_m_s: tuple[float | None, ...]

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("r_values_mm", "z_values_mm"):
            values = getattr(self, name)
            if len(values) < 2 or any(not math.isfinite(_finite(v, name)) for v in values):
                raise ValueError("r-z axes need at least two finite points")
            step = values[1] - values[0]
            if step <= 0 or any(b <= a or abs((b-a)-step) > 1e-9 for a, b in zip(values, values[1:])):
                raise ValueError("legacy r-z interpolation requires increasing uniform axes")
        if self.r_values_mm[0] < 0:
            raise ValueError("radial coordinates cannot be negative")
        size = len(self.r_values_mm) * len(self.z_values_mm)
        if any(len(getattr(self, name)) != size for name in self.__dataclass_fields__ if name not in {"r_values_mm", "z_values_mm"}):
            raise ValueError("r-z arrays must match z-major/r-minor grid size")
        if any(type(mask) is not bool for mask in self.fluid_mask):
            raise ValueError("fluid mask must contain booleans")
        fields = (self.pressure_pa, self.temperature_k, self.radial_velocity_m_s, self.axial_velocity_m_s)
        for i, fluid in enumerate(self.fluid_mask):
            values = tuple(a[i] for a in fields)
            if not fluid:
                if any(v is not None for v in values):
                    raise ValueError("masked samples must use explicit unavailable values")
            else:
                for v in values:
                    _finite(v, "fluid value")
                if values[0] <= 0 or values[1] <= 0:
                    raise ValueError("fluid pressure and temperature must be positive")
                # At the symmetry axis a finite radial vector has no unique direction.
                # Do not silently discard inconsistent producer data or invent an epsilon.
                if self.r_values_mm[0] == 0 and i % len(self.r_values_mm) == 0 and values[2] != 0:
                    raise ValueError("axisymmetric fluid data requires zero radial velocity at r=0")


@dataclass(frozen=True)
class GasFieldSpec:
    field_id: str
    frame_id: str
    representation: Literal["uniform", "piecewise_uniform", "axisymmetric_rz_grid"]
    composition_id: str
    composition: tuple[GasSpecies, ...]
    domain: BoxDomain | CylindricalDomain | UnboundedDomain
    source: GasSource
    uniform_state: GasState | None = None
    regions: tuple[GasRegion, ...] = ()
    background_state: GasState | None = None
    time_basis: str = "static"
    thermodynamic_closure: str = "ideal_gas_pressure_temperature"
    interpolation_policy: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "composition", tuple(self.composition))
        object.__setattr__(self, "regions", tuple(self.regions))
        if not all(isinstance(v, str) and v.strip() == v and v for v in (self.field_id, self.frame_id, self.composition_id)):
            raise ValueError("gas identity/frame must be explicit")
        if not isinstance(self.source, GasSource):
            raise ValueError("gas source must retain its typed kind, assumptions and reference")
        if self.time_basis != "static":
            raise ValueError("only static gas fields are implemented; no temporal interpolation")
        if self.thermodynamic_closure != "ideal_gas_pressure_temperature":
            raise ValueError("unsupported thermodynamic closure")
        if not self.composition or any(not isinstance(v, GasSpecies) for v in self.composition):
            raise ValueError("explicit gas composition is required")
        if len({s.species_id for s in self.composition}) != len(self.composition) or not math.isclose(sum(s.mole_fraction for s in self.composition), 1, rel_tol=0, abs_tol=1e-12):
            raise ValueError("gas mole fractions must sum to one with unique species")
        if not isinstance(self.domain, (BoxDomain, CylindricalDomain, UnboundedDomain)):
            raise ValueError("explicit supported domain required")
        if self.representation == "uniform":
            if not isinstance(self.uniform_state, GasState) or self.regions or self.background_state is not None or self.interpolation_policy is not None:
                raise ValueError("uniform gas requires exactly one state")
        elif self.representation == "piecewise_uniform":
            if self.uniform_state is not None or not self.regions or not isinstance(self.background_state, GasState) or self.interpolation_policy is not None:
                raise ValueError("piecewise gas requires regions and explicit background state")
            if any(not isinstance(v, GasRegion) for v in self.regions) or len({v.region_id for v in self.regions}) != len(self.regions):
                raise ValueError("gas regions must have unique identities")
        elif self.representation == "axisymmetric_rz_grid":
            if self.uniform_state is not None or self.regions or self.background_state is not None or self.interpolation_policy != "bilinear_fluid_corner_weight_renormalization_v1":
                raise ValueError("r-z gas requires its explicit legacy interpolation policy")
        else:
            raise ValueError("unsupported gas representation")


@dataclass(frozen=True)
class GasSample:
    state: GasState
    frame_id: str
    region_id: str | None
    composition_id: str
    number_density_m3: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, GasState) or not self.frame_id or not self.composition_id:
            raise ValueError("gas sample requires its state, frame and composition identity")
        if self.state.status == "gas":
            if _finite(self.number_density_m3, "number_density_m3") <= 0:
                raise ValueError("gas number density must be positive")
        elif self.state.status == "vacuum":
            if self.number_density_m3 != 0 or type(self.number_density_m3) not in (int, float):
                raise ValueError("explicit vacuum number density must be zero")
        elif self.number_density_m3 is not None:
            raise ValueError("unavailable sample must not invent number density")


@dataclass(frozen=True)
class CollisionSpec:
    model: Literal["none", "hs1", "sds"]
    gas_field_id: str | None
    random_policy: str | None
    cross_section_m2: float | None = None
    mean_free_path_policy: str | None = None
    gas_mass_amu: float | None = None
    gas_diameter_nm: float | None = None
    diffusion_enabled: bool | None = None
    collision_seed: int | None = None

    def __post_init__(self) -> None:
        if self.model == "none":
            if any(v is not None for v in (self.random_policy, self.cross_section_m2, self.mean_free_path_policy, self.gas_mass_amu, self.gas_diameter_nm, self.diffusion_enabled, self.collision_seed)):
                raise ValueError("disabled collisions must not carry model parameters")
            return
        if (not self.gas_field_id or not self.random_policy
                or type(self.collision_seed) is not int or self.collision_seed < 0):
            raise ValueError("collision gas identity, RNG policy and explicit nonnegative integer seed required")
        if self.model == "hs1":
            if _finite(self.cross_section_m2, "cross_section_m2") <= 0 or self.mean_free_path_policy != "from_cross_section":
                raise ValueError("HS1 requires positive total cross section and automatic MFP")
            if any(v is not None for v in (self.gas_mass_amu, self.gas_diameter_nm, self.diffusion_enabled)):
                raise ValueError("SDS parameters cannot be inferred from HS1")
        elif self.model == "sds":
            if _finite(self.gas_mass_amu, "gas_mass_amu") <= 0 or _finite(self.gas_diameter_nm, "gas_diameter_nm") <= 0 or type(self.diffusion_enabled) is not bool:
                raise ValueError("SDS requires explicit mass, diameter and diffusion")
            if self.cross_section_m2 is not None or self.mean_free_path_policy is not None:
                raise ValueError("HS1 parameters are not SDS parameters")
        else:
            raise ValueError("unsupported collision model")
