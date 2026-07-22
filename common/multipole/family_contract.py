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
    if document.get("schema_version") != 2 or document.get("role") != "rf_multipole_family_contract":
        raise ValueError("RF multipole family contract schema or role differs")
    foundation = document.get("foundation")
    if not isinstance(foundation, dict) or foundation.get("status") != "frozen_functional_baseline":
        raise ValueError("RF multipole family foundation is not frozen")
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


def from_quadrupole_contract(
    baseline: dict[str, Any],
    mode: dict[str, Any],
    project_id: str = "rf_quadrupole_collision_cooling",
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
    return MultipoleOperatingContract(
        identity=identity,
        geometry=MultipoleGeometry(
            r0_mm=_positive("field_radius_r0", geometry["field_radius_r0"]),
            effective_length_mm=_positive("rod_length", geometry["rod_length"]),
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
