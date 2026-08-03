"""Static regression tests for mandatory run-local integration inputs."""

from __future__ import annotations

from pathlib import Path
import unittest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BINDING = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
WORKFLOW_ENTRY = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
)
RUNNERS = (
    INTEGRATION_ROOT / "runtime" / "run_transfer.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pre_pulse_interface_transport.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pulse_capture.ps1",
    INTEGRATION_ROOT / "stages" / "cross_solver" / "run_analyzer_transport.ps1",
)


class RuntimeRunLocalContractTests(unittest.TestCase):
    def test_all_runtime_boundaries_require_four_run_local_identities(self) -> None:
        parameters = (
            "ResolvedSourceContract",
            "ResolvedSourceContractSha256",
            "UpstreamResolvedDesign",
            "UpstreamResolvedDesignSha256",
        )
        for path in (RUNTIME_BINDING, *RUNNERS):
            text = path.read_text(encoding="utf-8")
            for parameter in parameters:
                self.assertRegex(
                    text,
                    rf"\[Parameter\(Mandatory\)\]\[string\]\${parameter}\b",
                    (path, parameter),
                )
            self.assertNotIn("SourceContractOverride", text, path)
            self.assertNotIn("UpstreamResolvedDesignOverride", text, path)

    def test_runtime_accepts_only_active_v3_and_fixed_parent_run_files(self) -> None:
        text = RUNTIME_BINDING.read_text(encoding="utf-8")
        self.assertIn("$binding.schema_version -ne 3", text)
        self.assertNotRegex(text, r"sourceContract\.schema_version\s+-eq\s+1")
        self.assertIn("filename = 'resolved_source_contract.json'", text)
        self.assertIn("filename = 'upstream_resolved_design.json'", text)
        self.assertIn("-Root $parentRunRoot", text)
        self.assertIn("contractPaths.resolved_source_contract", text)
        self.assertNotIn("binding.contracts.source_contract", text)
        self.assertNotIn("binding.contracts.upstream_resolved_design", text)

    def test_stage_modes_and_manifest_roles_are_particle_count_neutral(self) -> None:
        joined = "\n".join(path.read_text(encoding="utf-8") for path in RUNNERS)
        for forbidden in (
            "rf_to_oatof_pre_pulse_interface_transport_n100",
            "rf_to_oatof_pulse_capture_n100",
            "rf_to_oatof_analyzer_transport_n100",
        ):
            self.assertNotIn(forbidden, joined)
        for path in RUNNERS[1:]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("resolved_source_contract", text, path)
            self.assertIn("upstream_resolved_design", text, path)

    def test_pulse_capture_uses_run_local_design_not_repository_inventory(self) -> None:
        text = RUNNERS[2].read_text(encoding="utf-8")
        self.assertIn(
            "Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design "
            "-Destination $rf",
            text.replace("`\n    ", ""),
        )
        self.assertNotIn("'rf_resolved_design'", text)

    def test_validate_cleanup_tolerates_parallel_empty_root_removal(self) -> None:
        self.assertIn(
            "Remove-Item -LiteralPath $validationRoot -Force "
            "-ErrorAction SilentlyContinue",
            WORKFLOW_ENTRY.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
