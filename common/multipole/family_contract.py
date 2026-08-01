"""Normalized family contract shared by quadrupole, hexapole and octupole projects."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FAMILY_CONTRACT_PATH = Path(__file__).with_name("family_contract.json")


@dataclass(frozen=True)
class MultipoleIdentity:
    """Normalized electrode identity and ideal radial order."""

    family_id: str
    project_id: str
    radial_order_n: int
    electrode_count: int
    coordinate_convention_id: str
    voltage_convention_id: str
    r0_convention_id: str


@dataclass(frozen=True)
class MultipoleGeometry:
    """Normalized ideal field radius and effective rod length in millimetres."""

    r0_mm: float
    effective_length_mm: float


@dataclass(frozen=True)
class VoltageDrive:
    """One two-group RF/DC drive using the family zero-to-peak convention."""

    waveform: str
    rf_amplitude_v_per_group: float
    dc_amplitude_v_per_group: float
    common_mode_offset_v: float
    frequency_hz: float
    phase_rad: float


@dataclass(frozen=True)
class MultipoleOperatingContract:
    """Normalized cross-project identity, geometry and voltage drive."""

    identity: MultipoleIdentity
    geometry: MultipoleGeometry
    voltage: VoltageDrive


def load_family_contract(path: Path = FAMILY_CONTRACT_PATH) -> dict[str, Any]:
    """Load the versioned family contract."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 5 or document.get("role") != "rf_multipole_family_contract":
        raise ValueError("RF multipole family contract schema or role differs")
    foundation = document.get("foundation")
    if not isinstance(foundation, dict) or foundation.get("api_status") != "frozen":
        raise ValueError("RF multipole family API is not frozen")
    validation = foundation.get("functional_validation", {})
    if (
        validation.get("status") != "unqualified_pending_contract_v2_rerun"
        or validation.get("particle_count") != 100
    ):
        raise ValueError("RF multipole family contract-v2 qualification status differs")
    return document


def _positive(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _finite(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _identity(project_id: str, order: int, electrode_count: int, baseline: dict[str, Any]) -> MultipoleIdentity:
    family = load_family_contract()
    if baseline.get("family_contract_id") != family["family_id"]:
        raise ValueError("baseline family_contract_id differs from the RF multipole family")
    if order not in family["supported_radial_orders"] or electrode_count != 2 * order:
        raise ValueError("electrode_count must equal twice a supported radial_order_n")
    return MultipoleIdentity(
        family_id=family["family_id"],
        project_id=project_id,
        radial_order_n=order,
        electrode_count=electrode_count,
        coordinate_convention_id=family["coordinate_convention_id"],
        voltage_convention_id=family["voltage_convention_id"],
        r0_convention_id=family["r0_convention_id"],
    )


def from_high_order_baseline(baseline: dict[str, Any]) -> MultipoleOperatingContract:
    """Normalize one ideal hexapole or octupole baseline."""
    multipole = baseline["multipole"]
    conventions = baseline["conventions"]
    identity = _identity(
        str(baseline["project_id"]),
        int(multipole["radial_order_n"]),
        int(multipole["electrode_count"]),
        baseline,
    )
    if identity.radial_order_n < 3:
        raise ValueError("high-order baseline adapter requires radial_order_n >= 3")
    expected = (identity.coordinate_convention_id, identity.voltage_convention_id, identity.r0_convention_id)
    actual = (conventions["coordinate_id"], conventions["voltage_id"], conventions["r0_id"])
    if actual != expected:
        raise ValueError("high-order baseline conventions differ from the family contract")
    geometry = baseline["geometry_mm"]
    rf = baseline["rf"]
    return MultipoleOperatingContract(
        identity=identity,
        geometry=MultipoleGeometry(
            r0_mm=_positive("inscribed_radius_r0", geometry["inscribed_radius_r0"]),
            effective_length_mm=_positive("effective_length", geometry["effective_length"]),
        ),
        voltage=VoltageDrive(
            waveform=str(rf["waveform"]),
            rf_amplitude_v_per_group=_positive("amplitude_V_peak", rf["amplitude_V_peak"]),
            dc_amplitude_v_per_group=0.0,
            common_mode_offset_v=_finite("common_mode_offset_V", rf["common_mode_offset_V"]),
            frequency_hz=_positive("frequency_Hz", rf["frequency_Hz"]),
            phase_rad=_finite("phase_rad", rf["phase_rad"]),
        ),
    )


def from_high_order_resolved_design(
    resolved: dict[str, Any],
) -> MultipoleOperatingContract:
    """Normalize one compiler-produced hexapole or octupole resolved design."""
    identity_source = resolved["identity"]
    family = load_family_contract()
    if identity_source.get("family_id") != family["family_id"]:
        raise ValueError("resolved design family_id differs from the RF multipole family")
    order = int(identity_source["radial_order_n"])
    electrode_count = int(identity_source["electrode_count"])
    if order < 3 or order not in family["supported_radial_orders"]:
        raise ValueError("high-order resolved adapter requires radial_order_n >= 3")
    if electrode_count != 2 * order:
        raise ValueError("electrode_count must equal twice radial_order_n")
    coordinate_id = str(resolved["coordinate"]["coordinate_id"])
    if coordinate_id != family["coordinate_convention_id"]:
        raise ValueError("resolved design coordinate convention differs from the family contract")
    geometry = resolved["geometry_mm"]
    drive = resolved["drive"]
    return MultipoleOperatingContract(
        identity=MultipoleIdentity(
            family_id=family["family_id"],
            project_id=str(identity_source["project_id"]),
            radial_order_n=order,
            electrode_count=electrode_count,
            coordinate_convention_id=coordinate_id,
            voltage_convention_id=family["voltage_convention_id"],
            r0_convention_id=family["r0_convention_id"],
        ),
        geometry=MultipoleGeometry(
            r0_mm=_positive("inscribed_radius_r0", geometry["inscribed_radius_r0"]),
            effective_length_mm=_positive("rod_length", geometry["rod_length"]),
        ),
        voltage=VoltageDrive(
            waveform=str(drive["waveform"]),
            rf_amplitude_v_per_group=_positive(
                "rf_amplitude_V_zero_to_peak_per_group",
                drive["rf_amplitude_V_zero_to_peak_per_group"],
            ),
            dc_amplitude_v_per_group=_finite(
                "dc_amplitude_V_per_group", drive["dc_amplitude_V_per_group"]
            ),
            common_mode_offset_v=_finite(
                "common_mode_offset_V", drive["common_mode_offset_V"]
            ),
            frequency_hz=_positive("frequency_Hz", drive["frequency_Hz"]),
            phase_rad=_finite("phase_rad", drive["phase_rad"]),
        ),
    )


def l1_l2_transport_contract_from_resolved_design(
    resolved: dict[str, Any],
) -> dict[str, Any]:
    """Project a governed resolved design onto the legacy analytic solver API.

    The projection keeps the deterministic L1/L2 validation policy local to the
    analytic runner while taking every physical geometry and drive value from the
    current profile compiler.  It is deliberately not a design authority.
    """
    operating = from_high_order_resolved_design(resolved)
    enclosure = resolved["geometry_mm"]["enclosure"]
    energy = resolved["particle_source"]["energy_model"]
    if energy.get("kind") != "monoenergetic":
        raise ValueError("analytic L1/L2 projection requires a monoenergetic source")
    return {
        "schema_version": 1,
        "role": "multipole_l1_l2_internal_transport_projection",
        "status": "generated_from_current_resolved_design",
        "project_id": operating.identity.project_id,
        "family_contract_id": operating.identity.family_id,
        "field_model_id": "multipole.ideal_2n.v1",
        "trajectory_model_id": "multipole.ideal_finite_length.time_domain.v1",
        "model_level": "L1",
        "multipole": {
            "electrode_count": operating.identity.electrode_count,
            "radial_order_n": operating.identity.radial_order_n,
            "orientation_rad": float(resolved["coordinate"]["orientation_rad"]),
        },
        "conventions": {
            "coordinate_id": operating.identity.coordinate_convention_id,
            "voltage_id": operating.identity.voltage_convention_id,
            "r0_id": operating.identity.r0_convention_id,
        },
        "geometry_mm": {
            "inscribed_radius_r0": operating.geometry.r0_mm,
            "usable_radius": _positive(
                "working_region_radius_mm", enclosure["working_region_radius_mm"]
            ),
            "effective_length": operating.geometry.effective_length_mm,
            "round_rod_geometry_selected": False,
        },
        "rf": {
            "waveform": operating.voltage.waveform,
            "amplitude_V_peak": operating.voltage.rf_amplitude_v_per_group,
            "frequency_Hz": operating.voltage.frequency_hz,
            "phase_rad": operating.voltage.phase_rad,
            "common_mode_offset_V": operating.voltage.common_mode_offset_v,
        },
        "particle_source": {
            "count": 100,
            "seed": 20260722,
            "mass_amu": 100.0,
            "charge_state": int(resolved["particle_source"]["charge_state"]),
            "kinetic_energy_eV": _positive("kinetic_energy_eV", energy["kinetic_energy_eV"]),
            "maximum_source_radius_mm": 0.5,
            "maximum_divergence_deg": 5.0,
            "birth_phase_distribution": "uniform_one_rf_period",
        },
        "numerics": {"rf_steps_per_period": 80},
        "assumptions": {
            "collision_model": "disabled",
            "space_charge_model": "disabled",
            "magnetic_field_model": "disabled",
            "axial_field_model": "disabled",
        },
        "functional_acceptance": {
            "minimum_rf_transmission": 0.8,
            "minimum_improvement_over_zero_rf": 0.2,
        },
        "claim_limit": (
            "Generated internal L1/L2 analytic projection; physical values come from the "
            "current governed resolved design and this document is not a design authority."
        ),
    }
def from_quadrupole_contract(
    baseline: dict[str, Any],
    mode: dict[str, Any],
    project_id: str = "rf_quadrupole_ion_optics",
    rf_amplitude_v_per_group: float | None = None,
    frequency_hz: float | None = None,
) -> MultipoleOperatingContract:
    """Normalize one quadrupole mode, including explicit per-run RF bindings."""
    identity = _identity(project_id, 2, 4, baseline)
    geometry = baseline["geometry_mm"]
    rf = mode.get("rf")
    if isinstance(rf, dict) and "amplitude_V_zero_to_peak_per_group" in rf:
        amplitude = rf["amplitude_V_zero_to_peak_per_group"]
        dc_amplitude = rf["dc_amplitude_V_per_group"]
        common_mode = rf["axis_common_mode_offset_V"]
        phase_rad = math.radians(float(rf["phase_deg"]))
    elif isinstance(rf, dict):
        amplitude = rf["amplitude_V_peak"]
        dc_amplitude = float(rf["rod_dc_differential_V"]) / 2.0
        common_mode = rf["axis_offset_V"]
        phase_rad = rf["phase_rad"]
    else:
        policy = mode.get("operating_point_policy", {})
        physics = mode.get("physics", {})
        if physics.get("mass_filter_dc") is not False:
            raise ValueError("quadrupole mode without an rf block must explicitly disable mass-filter DC")
        if rf_amplitude_v_per_group is None:
            raise ValueError("quadrupole mode requires an explicit per-run RF amplitude")
        amplitude = rf_amplitude_v_per_group
        dc_amplitude = 0.0
        common_mode = 0.0
        phase_rad = policy["phase_reference_rad"]
        frequency_hz = policy["rf_frequency_Hz"] if frequency_hz is None else frequency_hz
    if rf_amplitude_v_per_group is not None:
        amplitude = rf_amplitude_v_per_group
    resolved_frequency = rf["frequency_Hz"] if frequency_hz is None and isinstance(rf, dict) else frequency_hz
    rod_length = _finite("rod_z_max", geometry["rod_z_max"]) - _finite(
        "rod_z_min", geometry["rod_z_min"]
    )
    return MultipoleOperatingContract(
        identity=identity,
        geometry=MultipoleGeometry(
            r0_mm=_positive("field_radius_r0", geometry["field_radius_r0"]),
            effective_length_mm=_positive("rod axial span", rod_length),
        ),
        voltage=VoltageDrive(
            waveform="sine",
            rf_amplitude_v_per_group=_positive("RF amplitude", amplitude),
            dc_amplitude_v_per_group=_finite("DC amplitude", dc_amplitude),
            common_mode_offset_v=_finite("common-mode offset", common_mode),
            frequency_hz=_positive("frequency_Hz", resolved_frequency),
            phase_rad=_finite("phase", phase_rad),
        ),
    )


def rf_waveform_voltage(drive: VoltageDrive, time_s: float) -> float:
    """Return the signed instantaneous RF contribution in volts."""
    argument = 2.0 * math.pi * drive.frequency_hz * float(time_s) + drive.phase_rad
    if drive.waveform == "sine":
        return drive.rf_amplitude_v_per_group * math.sin(argument)
    if drive.waveform == "cosine":
        return drive.rf_amplitude_v_per_group * math.cos(argument)
    raise ValueError(f"unsupported RF waveform: {drive.waveform}")


def electrode_group_voltages(drive: VoltageDrive, time_s: float) -> tuple[float, float]:
    """Return positive- and negative-group voltages under the family convention."""
    differential = drive.dc_amplitude_v_per_group + rf_waveform_voltage(drive, time_s)
    return drive.common_mode_offset_v + differential, drive.common_mode_offset_v - differential


def operating_contract_document(contract: MultipoleOperatingContract) -> dict[str, Any]:
    """Serialize a normalized operating contract with explicit units."""
    return {
        "schema_version": 1,
        "role": "rf_multipole_normalized_operating_contract",
        "identity": {
            "family_id": contract.identity.family_id,
            "project_id": contract.identity.project_id,
            "radial_order_n": contract.identity.radial_order_n,
            "electrode_count": contract.identity.electrode_count,
            "coordinate_convention_id": contract.identity.coordinate_convention_id,
            "voltage_convention_id": contract.identity.voltage_convention_id,
            "r0_convention_id": contract.identity.r0_convention_id,
        },
        "geometry_mm": {
            "r0": contract.geometry.r0_mm,
            "effective_length": contract.geometry.effective_length_mm,
        },
        "voltage": {
            "waveform": contract.voltage.waveform,
            "rf_amplitude_V_zero_to_peak_per_group": contract.voltage.rf_amplitude_v_per_group,
            "dc_amplitude_V_per_group": contract.voltage.dc_amplitude_v_per_group,
            "common_mode_offset_V": contract.voltage.common_mode_offset_v,
            "frequency_Hz": contract.voltage.frequency_hz,
            "phase_rad": contract.voltage.phase_rad,
        },
    }
