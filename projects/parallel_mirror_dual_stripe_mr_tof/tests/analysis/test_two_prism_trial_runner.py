"""Native-only contract tests for the MR-TOF flight runner."""
from pathlib import Path
import unittest

RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"

class TwoPrismTrialRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_requires_native_bank_and_system_bundle(self):
        self.assertIn("NativeCorridorBankRunPath is required for the native-only flight runner.", self.source)
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", self.source)

    def test_no_legacy_five_region_public_inputs_remain(self):
        for name in ("LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
                     "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
                     "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
                     "BootstrapGlobalOperatingPa", "localWorkbenchRun",
                     "useNativeCorridor", "hybridFixedResponseScreening",
                     "localOperatingCacheReceipt", "batchTemplateRecord"):
            self.assertNotIn(name, self.source)

    def test_native_runtime_preserves_four_instance_and_bundle_identity(self):
        for token in ("build_native_corridor_iob.lua", "4_instance_seed.iob",
                      "native_system_runtime", "NativeCorridorRuntimeSession",
                      "native_corridor_private_fast_adjust_family"):
            self.assertIn(token, self.source)

    def test_retained_gui_workbench_is_run_local_and_lifecycle_managed(self):
        for token in (
            "[switch]$RetainGuiWorkbench",
            "'solver_review'",
            "Retained SIMION GUI workbench with private run-local IOB companions.",
            "Join-Path $artifactSolverDir 'gui_workbench'",
            "Join-Path $temporarySolverDir 'pa_inputs'",
            "Retained GUI workbench requires a private native runtime family",
            "PA payloads have already been bound through the runtime and published",
            "pa_dependencies=$guiPaDependencies",
        ):
            self.assertIn(token, self.source)
        self.assertIn(
            "if($null-ne$iobInputCopyDir-and-not$RetainGuiWorkbench)", self.source
        )
        self.assertNotIn(
            "Get-ChildItem -LiteralPath $temporarySolverDir -Recurse -File", self.source
        )

    def test_bunch_batches_do_not_clone_the_native_pa_family(self):
        self.assertIn("A batch owns only its source and IOB", self.source)
        self.assertIn("shared_native_corridor_runtime__four_instances__no_refine", self.source)
        self.assertNotIn("build_local_refinement_iob.lua", self.source)
        self.assertNotIn("build_three_component_iob.lua", self.source)

    def test_provider_runtime_receipt_is_the_only_accelerator_input(self):
        self.assertIn("AcceleratorProviderReceiptPath", self.source)
        self.assertNotIn("AcceleratorRunPath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)
        self.assertIn("published_read_only", self.source)
        self.assertIn("Provider receipt input identity differs from its declared record.", self.source)

if __name__ == "__main__":
    unittest.main()
