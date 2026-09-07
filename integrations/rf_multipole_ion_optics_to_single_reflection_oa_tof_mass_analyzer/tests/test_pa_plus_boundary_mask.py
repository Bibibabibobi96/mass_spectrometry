from __future__ import annotations

import re
import unittest
from pathlib import Path


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


class PaPlusBoundaryMaskContractTests(unittest.TestCase):
    """Static contracts; these do not replace native field/trajectory checks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.lua = (RUNTIME / "restore_pa_plus_boundary_mask.lua").read_text(
            encoding="utf-8"
        )
        cls.runner = (RUNTIME / "run_single_flight.ps1").read_text(encoding="utf-8")
        cls.code = re.sub(r"--[^\n]*", "", cls.lua)

    def test_restoration_never_refines_or_rewrites_potential(self) -> None:
        self.assertNotRegex(self.code, r":refine\s*\(")
        self.assertNotRegex(self.code, r":refine\s*\{")
        self.assertNotRegex(self.code, r":point\s*\(")
        self.assertNotRegex(self.code, r":potential\s*\([^)]*,[^)]*,[^)]*,")
        self.assertNotIn("convergence", self.code)

    def test_interface_has_template_modes_and_report(self) -> None:
        for argument in ("arg[1]", "arg[2]", "arg[3]"):
            self.assertIn(argument, self.code)
        self.assertIn("%.pa#$", self.code)
        self.assertIn(":save()", self.code)

    def test_only_synthetic_flags_are_removed_and_physical_loss_is_rejected(self) -> None:
        compact = re.sub(r"\s+", "", self.code)
        self.assertIn("localphysical=template:electrode(ix,iy,iz)", compact)
        self.assertIn("localelectrode=fine:electrode(ix,iy,iz)", compact)
        self.assertIn("assert(notphysicalorelectrode,", compact)
        self.assertIn(
            "ifnotphysicalandelectrodethenfine:electrode(ix,iy,iz,false)", compact
        )
        self.assertEqual(compact.count("fine:electrode(ix,iy,iz,false)"), 1)
        self.assertNotIn("fine:electrode(ix,iy,iz,true)", compact)
        self.assertIn("fine.nx==template.nx", compact)
        self.assertIn("fine.dz_mm==template.dz_mm", compact)

    def test_faces_are_disjoint_and_complete_not_a_volume_scan(self) -> None:
        compact = re.sub(r"\s+", "", self.code)
        for loop in (
            "foriz=0,fine.nz-1doforiy=0,fine.ny-1dorestore(0,iy,iz);restore(fine.nx-1,iy,iz)endend",
            "foriz=0,fine.nz-1doforix=1,fine.nx-2dorestore(ix,0,iz);restore(ix,fine.ny-1,iz)endend",
            "foriy=1,fine.ny-2doforix=1,fine.nx-2dorestore(ix,iy,0);restore(ix,iy,fine.nz-1)endend",
        ):
            self.assertIn(loop, compact)
        self.assertIn("assert(visited==expected,", compact)
        self.assertNotIn(":points()", compact)
        self.assertNotIn("seen=", compact)

    def test_receipt_follows_save_and_idempotent_no_change_skips_write(self) -> None:
        self.assertIn("if changed>0 then fine:save() end", self.code)
        self.assertLess(self.code.index("fine:save()"), self.code.index("report:write("))
        for field in (
            '"policy_id":"physical_geometry_boundary_flags_v1"',
            '"potential_operation":"unchanged_official_electrode_setter"',
            '"restored_flags"',
        ):
            self.assertIn(field, self.code)

    def test_runner_restores_only_materialized_field_bearing_pa_plus_before_iob(self) -> None:
        start = self.runner.index("foreach ($domainSplitFineBuild in $domainSplitRuntimeBuilds)")
        end = self.runner.index("$domainSplitFineBuild.pa0 =", start)
        block = self.runner[start:end]
        self.assertLess(block.index("Copy-RfPaCacheFamilyToRuntime"), block.index("$maskRestorer ="))
        self.assertIn("'geometry_collision_zero_field_v1' -and", block)
        self.assertIn("$null -ne $domainSplitFineBuild.geometry.pa_plus_solution_model", block)
        self.assertIn("if ($runtimeProjectionIds.Count -gt 0)", block)
        self.assertIn("$domainSplitFineBuild.geometry.pa_plus_solution_model.mode_ids", block)
        self.assertIn("Copy-RfStableFile -SourceRunRoot $repoRoot", block)
        self.assertIn("-Destination $maskRestorer", block)
        self.assertIn("$maskResult = Invoke-ResourceBudgetedProcess", block)
        self.assertIn("-ResolvedBudgetPath $budget.stage_budget", block)
        self.assertIn("(Join-Path $runtimeDir ($domainSplitFineBuild.name + '.pa#'))", block)
        self.assertIn("$maskResult.resource_budget_exceeded", block)
        self.assertIn("$maskResult.exit_code -ne 0", block)
        self.assertNotIn("Publish-RfVerifiedCacheEntry", block)

    def test_main_and_local_domains_share_one_frozen_restorer(self) -> None:
        loop = self.runner.index("foreach ($domainSplitFineBuild in $domainSplitRuntimeBuilds)")
        self.assertRegex(self.runner[:loop], r"\$maskRestorer = \$null\s*$")
        end = self.runner.index("$maskSolutionIds =", loop)
        freeze = self.runner[loop:end]
        guard = freeze.index("if ($null -eq $maskRestorer) {")
        guarded = freeze[guard:]
        self.assertEqual(guarded.count("Copy-RfStableFile"), 1)
        self.assertIn("-Destination $maskRestorer", guarded)
        self.assertRegex(guarded, r"\| Out-Null\s*}\s*$")
        self.assertNotIn("$maskRestorer = $null", freeze)


if __name__ == "__main__":
    unittest.main()
