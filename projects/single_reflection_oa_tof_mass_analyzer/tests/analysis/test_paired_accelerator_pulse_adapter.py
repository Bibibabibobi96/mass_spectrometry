"""Static native-boundary guards; these do not execute or qualify COMSOL APIs."""
from pathlib import Path
import re
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "comsol/run_paired_accelerator_pulse.m"


class PairedPulseAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.main = cls.text.split("\nfunction [static,release,data]=", 1)[0]

    def test_export_recovery_does_not_compute_save_or_reconfigure(self):
        branch = self.main.split("\nelse\n", 1)[1].split("\nend\nfacts=", 1)[0]
        self.assertIn("verify_particle_study(model,plan)", branch)
        self.assertIn("model.sol('sol_pulse').isEmpty()", branch)
        for forbidden in (".run", "mphsave(", "configure_particle_study("):
            self.assertNotIn(forbidden, branch)
        self.assertEqual(self.text.count("mphsave("), 1)

    def test_raw_native_solution_is_saved_before_particle_reads(self):
        positions = [self.main.index(token) for token in (
            "model.study('std_pulse').run;", "mphsave(model,modelPath);",
            "write_json(fullfile(outputDir,'paired_pulse_solution.json')",
            "facts=export_particles(",
        )]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.text.count("mphparticle(model,"), 1)
        for forbidden in (".mesh(", ".geom(", "ModelUtil.create(", "mphstart", ".runAll"):
            self.assertNotIn(forbidden, self.text)

    def test_release_clock_and_units_do_not_use_native_coordinate_defaults(self):
        for required in (
            "oatof_read_cartesian_release(plan.source_csv.path,plan.mass_amu,plan.particle_count)",
            "rel.set('rt','paired_source_time')", "times(1)==plan.source_time_us",
            "qx/1[mm]", "cpt.vx/1[m/s]", "cpt.st/1[us]",
            "data.t(:)*1e6", "native_particle_indices", "native_expression_shape",
            "initial-expected", "Native trajectory columns changed particle identity",
            "'mp',sprintf('%.17g[kg]',plan.mass_kg)",
        ):
            self.assertIn(required, self.text)
        self.assertNotIn("[u]", self.text)
        self.assertNotIn("1.6605", self.text)

    def test_finite_gate_and_native_vacuum_do_not_apply_probe_clearance(self):
        for required in (
            "if(t>=paired_pulse_on&&t<paired_pulse_off,1,0)",
            "(%s)*withsol(''sol1'',es.E%c)",
            "plan.off_electrode_voltages_v", "v==0",
            "'edim','domain','ext',0", "cpt.selection.named('sel_vac')",
            "{'wall_metal',metal,'Freeze'}", "{'wall_outer',outer,'Freeze'}",
            "{'wall_grids',sheets,'Pass'}",
            "oatof_cpt_solver_policy(", "'maxstepconstraintgenalpha','const'",
            "'atolglobalmethod','scaled'",
        ):
            self.assertIn(required, self.text)
        code = "\n".join(line for line in self.text.splitlines() if not line.lstrip().startswith("%"))
        self.assertNotRegex(code, re.compile(r"clearance\s*[=(:,]"))
        self.assertNotIn("detector", self.text)
        self.assertIn("raw status/stop time are not collision-entity identities", self.text)

    def test_transparent_interior_wall_uses_native_64_token(self):
        # 040326 native configuration rejected PassThrough and enumerated Pass.
        # This guard fixes the supported token; native trajectory acceptance
        # remains necessary to establish passage through the actual OA sheets.
        self.assertIn("{'wall_grids',sheets,'Pass'}", self.text)
        self.assertNotIn("PassThrough", self.text)
        self.assertIn("wall.set('WallCondition',item{3})", self.text)
        self.assertIn("{'wall_metal',metal,'Freeze'}", self.text)
        self.assertIn("{'wall_outer',outer,'Freeze'}", self.text)

    def test_charge_readback_evaluates_the_native_expression_property(self):
        # 041645 confirmed that COMSOL stores pp1.Z as an expression, not a
        # double parameter; evaluating it preserves the declared charge check.
        self.assertIn("model.param.evaluate(char(cpt.feature('pp1').getString('Z')))", self.text)
        self.assertNotIn(".getDouble('Z')", self.text)


if __name__ == "__main__":
    unittest.main()
