from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_ion_optics.analysis import (
    validate_pulse_capture as validator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class PulseCaptureContractTests(unittest.TestCase):
    def test_repository_contract_is_pulse_only(self) -> None:
        contract = validator.validate_contract()
        self.assertEqual(contract["phase"], "pulse_capture")
        self.assertEqual(contract["topology_source"], "resolved_connection")
        for forbidden in (
            "source",
            "identity_contract",
            "local_exit_adapter",
            "spatial_registration",
            "connector",
        ):
            self.assertNotIn(forbidden, contract)

    def test_waveform_or_qualification_drift_is_rejected(self) -> None:
        for field, value, message in (
            ("rise_fall_model", "ideal_edge", "waveform"),
            ("phase_pass_allowed", True, "qualification"),
        ):
            changed = copy.deepcopy(validator.validate_contract())
            if field in changed["waveform"]:
                changed["waveform"][field] = value
            else:
                changed["permissions"][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "pulse_capture.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    validator.validate_contract(path)

    def test_runner_uses_pre_pulse_and_resolved_authorities(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "comsol"
            / "run_pulse_capture.ps1"
        ).read_text(encoding="utf-8")
        for required in (
            "--pre-pulse-contract",
            "--pulse-capture-contract",
            "--resolved-connection",
            "RF_OATOF_RESOLVED_CONNECTION",
            "rf_pulse_capture_local_exit_adapter",
            "rf_pulse_capture_pulse_chain_auditor",
        ):
            self.assertIn(required, runner)
        for forbidden in (
            "run_s3",
            "rf_s3",
            "resolve_s2",
            "resolved_rf_to_oatof_s2",
        ):
            self.assertNotIn(forbidden, runner)


if __name__ == "__main__":
    unittest.main()
