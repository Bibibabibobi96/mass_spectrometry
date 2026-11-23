"""Static contract checks for the native finite-pulse COMSOL microcase."""
from pathlib import Path
import unittest


SOURCE = Path(__file__).parent / "comsol" / "test_finite_pulse_field_superposition.m"


class FinitePulseFieldSuperpositionContractTests(unittest.TestCase):
    def test_field_solver_is_explicit_direct_and_stricter_than_field_budget(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("fieldSolver = model.sol.create('sol_field');", source)
        self.assertIn("fieldSolver.createAutoSequence('std_field');", source)
        self.assertIn("fieldSolver.attach('std_field');", source)
        self.assertIn("stationary.set('control','user');", source)
        self.assertIn("stationary.set('stol','1e-12');", source)
        self.assertIn("stationary.feature('dDef').set('linsolver','pardiso');", source)
        self.assertIn("es.prop('ShapeProperty').set('order_electricpotential','2');", source)
        self.assertIn("fieldSolver.runAll;", source)
        self.assertIn("tolerances = [1e-6, 1e-8];", source)

    def test_single_particle_readout_accepts_only_documented_singleton_forms(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("sample_trace(model,times,fid)", source)
        self.assertIn("function trace = sample_trace(model,times,fid)", source)
        self.assertIn("isequal(positionSize,[numel(times),3])", source)
        self.assertIn("isequal(velocitySize,[numel(times),3])", source)
        self.assertIn("size(data.p,2)==1 && size(data.p,3)==3", source)
        self.assertIn("size(data.v,2)==1 && size(data.v,3)==3", source)
        self.assertIn("PARTICLE_POSITION_SIZE=", source)

    def test_particle_compute_has_a_bounded_internal_step_and_raw_checkpoint(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("maxInternalStep = 1e-9;", source)
        self.assertIn("timeSolver.set('maxstepconstraintgenalpha','const');", source)
        self.assertIn("timeSolver.set('maxstepgenalpha',num2str(maxInternalStep,17));", source)
        self.assertIn("RAW_PARTICLE_CHECKPOINT_LEVEL_%d=", source)
        self.assertIn("mphsave(model,rawCheckpointPath);", source)
        self.assertLess(
            source.index("particleStudy.run;"),
            source.index("mphsave(model,rawCheckpointPath);"),
        )
        self.assertLess(
            source.index("mphsave(model,rawCheckpointPath);"),
            source.index("sample_trace(model,times,fid);"),
        )


if __name__ == "__main__":
    unittest.main()
