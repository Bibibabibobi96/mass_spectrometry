"""Static checks for the COMSOL builder's resolved-contract boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILDER = PROJECT_ROOT.parents[1] / "src/msplatform/backends/comsol/matlab/ms_stage1_ei_source.m"
BUILD_TEST = PROJECT_ROOT / "tests" / "comsol" / "test_build_only.m"


class MatlabContractBindingTests(unittest.TestCase):
    """Keep the MATLAB entry fail-closed and contract-driven."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.builder = BUILDER.read_text(encoding="utf-8")
        cls.build_test = BUILD_TEST.read_text(encoding="utf-8")

    def test_builder_requires_resolved_contract(self) -> None:
        self.assertIn("load_ei_source_contract", self.builder)
        self.assertIn("resolvedContractPath", self.builder)
        self.assertIn("no defaults exist", self.builder)

    def test_builder_requires_owner_path_without_repository_or_environment_discovery(self) -> None:
        self.assertIn('ms_stage1_ei_source(resolvedContractPath, runDirectory, label)', self.builder)
        self.assertIn('if nargin < 2 || isempty(runDirectory)', self.builder)
        self.assertIn('if nargin < 3 || isempty(label)', self.builder)
        self.assertIn("fullfile(runDirectory, 'comsol')", self.builder)
        self.assertIn("fullfile(runDirectory, 'results')", self.builder)
        for forbidden in ('mfilename', 'addpath', 'getenv', 'ei_source_paths'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.builder)
        self.assertIn('MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY', self.build_test)
        self.assertIn("ms_stage1_ei_source(contractPath, runDirectory, 'build_smoke')", self.build_test)

    def test_critical_comsol_nodes_use_named_parameters(self) -> None:
        required_bindings = (
            "set('r', 'R_tube')",
            "set('r', 'r_hole')",
            "set('r', 'release_r')",
            "set('Nd', 'Nd')",
            "set('xsec', 'sigma_ion')",
            "set('dE', 'dE_ion')",
            "set('tlist', 'range(0,dtstep,Tsim)')",
        )
        for binding in required_bindings:
            with self.subTest(binding=binding):
                self.assertIn(binding, self.builder)

    def test_build_only_test_checks_identity_and_gui_bindings(self) -> None:
        self.assertIn("resolved_model.json", self.build_test)
        self.assertIn("contract_project_id", self.build_test)
        self.assertIn("parameter_bindings_verified", self.build_test)
        self.assertIn("candidate_evidence_allowed", self.build_test)

    def test_old_argument_and_duplicate_physical_values_are_absent(self) -> None:
        forbidden = (
            "Nd_val",
            "if nargin < 1, Nd_val",
            "'2e-20[m^2]'",
            "'15[eV]'",
            "zEnd > 99",
            "'1e4[m/s]'",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.builder)


if __name__ == "__main__":
    unittest.main()
