from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_ion_optics.analysis import (
    validate_pre_pulse_interface_transport as validator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class PrePulseInterfaceTransportTests(unittest.TestCase):
    def test_repository_contract_passes_without_topology_fields(self) -> None:
        contract = validator.validate_contract()
        self.assertEqual(contract["phase"], "pre_pulse_interface_transport")
        self.assertEqual(contract["topology_source"], "resolved_connection")
        serialized = json.dumps(contract)
        for forbidden in (
            "nominal_registration",
            "connector_gap_mm",
            "rotation_source_to_target",
            "transition_aperture",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_qualification_permission_drift_is_rejected(self) -> None:
        changed = copy.deepcopy(validator.validate_contract())
        changed["permissions"]["phase_pass_allowed"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pre_pulse.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qualification boundary"):
                validator.validate_contract(path)

    def test_comsol_consumers_require_resolved_connection(self) -> None:
        root = (
            INTEGRATION_ROOT / "stages" / "comsol"
        )
        sources = "\n".join(
            (root / name).read_text(encoding="utf-8")
            for name in (
                "build_pre_pulse_interface_transport_model.m",
                "prepare_pre_pulse_interface_transport_field_model.m",
                "solve_pre_pulse_interface_transport_field.m",
                "run_pre_pulse_interface_transport.ps1",
            )
        )
        self.assertIn("resolvedConnection", sources)
        self.assertIn("RF_OATOF_RESOLVED_CONNECTION", sources)
        self.assertIn("upstreamSurface.center_mm(3)", sources)
        self.assertIn(
            "connectorPresent = gapMm > positionToleranceMm;",
            sources,
        )
        self.assertNotIn("connectorPresent = gapMm > 0;", sources)
        for forbidden in (
            "resolve_spatial_registration",
            "resolve_s2_connector_case",
            "nominal_registration",
            "passive_connector_geometry",
            "registration.source_exit_center_local_mm",
        ):
            self.assertNotIn(forbidden, sources)


if __name__ == "__main__":
    unittest.main()
