"""Static scheduling contracts for MR-TOF SIMION flight and field-sampling entries."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


SIMION_DIR = Path(__file__).resolve().parents[2] / "simion"


def _source(name: str) -> str:
    return (SIMION_DIR / name).read_text(encoding="utf-8-sig")


class SimionResourceStageBoundaryTests(unittest.TestCase):
    def assert_light_prepare_flight_postprocess(
        self, source: str, *, prepare_marker: str, flight_marker: str, postprocess_marker: str
    ) -> None:
        enter = "Enter-HostExecutionLease -Role SIMION -Stage prepare"
        flight = re.search(
            r"Update-HostResourceStage\s+-Lease\s+\$\w+\s+-Stage\s+flight", source
        )
        postprocess = re.search(
            r"Update-HostResourceStage\s+-Lease\s+\$\w+\s+-Stage\s+postprocess", source
        )
        self.assertEqual(source.count(enter), 1)
        self.assertIsNotNone(flight)
        self.assertIsNotNone(postprocess)
        assert flight is not None and postprocess is not None
        self.assertEqual(source.count("Update-HostResourceStage -Lease"), 2)
        self.assertLess(source.index(enter), source.index(prepare_marker))
        self.assertLess(source.index(prepare_marker), flight.start())
        self.assertLess(flight.start(), source.index(flight_marker))
        self.assertLess(source.index(flight_marker), postprocess.start())
        self.assertLess(postprocess.start(), source.index(postprocess_marker))
        self.assertNotIn("-Stage pa_prepare", source)
        self.assertNotIn("-Stage pa_refine", source)

    def test_first_prism_inspection_is_light_and_native_flight_is_heavy(self) -> None:
        self.assert_light_prepare_flight_postprocess(
            _source("run_three_component_first_prism_flight.ps1"),
            prepare_marker="Invoke-MrtofSimionStep -Stage 'inspect_iob'",
            flight_marker="Invoke-MrtofSimionStep -Stage 'native_first_prism_flight'",
            postprocess_marker="$rawLog=Join-Path",
        )

    def test_interface_field_sampling_never_requests_flight(self) -> None:
        source = _source("run_analyzer_local_interface_convergence.ps1")
        self.assertEqual(source.count("Enter-HostExecutionLease -Role SIMION -Stage prepare"), 1)
        self.assertEqual(source.count("Update-HostResourceStage -Lease"), 1)
        self.assertNotIn("-Stage flight", source)
        self.assertNotIn("-Stage pa_refine", source)
        self.assertLess(source.index("-Stage prepare"), source.index("compare_dirichlet_patch_interface.lua"))
        self.assertLess(source.index("compare_dirichlet_patch_interface.lua"), source.index("-Stage postprocess"))
        self.assertLess(source.index("-Stage postprocess"), source.index("analyze_interfaces"))

    def test_portal_field_sampling_never_requests_flight(self) -> None:
        source = _source("run_analyzer_local_portal_interface_convergence.ps1")
        self.assertEqual(source.count("Enter-HostExecutionLease -Role SIMION -Stage prepare"), 1)
        self.assertEqual(source.count("Update-HostResourceStage -Lease"), 1)
        self.assertNotIn("-Stage flight", source)
        self.assertNotIn("-Stage pa_refine", source)
        self.assertLess(source.index("-Stage prepare"), source.index("compare_pa_fields_at_samples.lua"))
        self.assertLess(source.index("compare_pa_fields_at_samples.lua"), source.index("-Stage postprocess"))
        self.assertLess(source.index("-Stage postprocess"), source.index("analyze_portals"))


if __name__ == "__main__":
    unittest.main()
