from __future__ import annotations

import copy
import unittest

from common.contracts.machine_contracts import ContractError
from common.multipole.component_port import build_exit_component_port
from common.multipole.test_compile_design_request import design_request
from common.multipole.compile_design_request import compile_design_request


class MultipoleComponentPortTests(unittest.TestCase):
    def test_builds_port_from_resolved_design(self) -> None:
        request = design_request()
        resolved = compile_design_request(request, expected_identity=request["identity"])
        port = build_exit_component_port(
            resolved,
            design_profile_id="no_acceleration_full_length",
            authority_path=(
                "artifacts/projects/rf_quadrupole_ion_optics/runs/"
                "20260803_000000__sim__simion__fixture/inputs/"
                "multipole_resolved_design.json"
            ),
            authority_sha256="A" * 64,
        )
        self.assertEqual(port["project_id"], "rf_quadrupole_ion_optics")
        self.assertEqual(
            port["mating_surface"]["center_mm"][2],
            resolved["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
        )
        self.assertEqual(
            port["profile_scope"]["scope_id"], "no_acceleration_full_length"
        )

    def test_rejects_stale_resolved_design(self) -> None:
        request = design_request()
        resolved = compile_design_request(request, expected_identity=request["identity"])
        stale = copy.deepcopy(resolved)
        stale["interfaces_mm"]["exit"]["handoff_plane_z_mm"] += 1.0
        with self.assertRaisesRegex(ContractError, "hash is stale"):
            build_exit_component_port(
                stale,
                design_profile_id="no_acceleration_full_length",
                authority_path=(
                    "artifacts/projects/rf_quadrupole_ion_optics/runs/"
                    "20260803_000000__sim__simion__fixture/inputs/"
                    "multipole_resolved_design.json"
                ),
                authority_sha256="A" * 64,
            )


if __name__ == "__main__":
    unittest.main()
