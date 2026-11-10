import tempfile
import unittest
import json
import subprocess
import sys
from msplatform.execution.inputs import enumerate_python_sources, freeze_file
from pathlib import Path

from msplatform.analysis.rf_transport_metrics import evaluate


HEADER = "particle_id,event,status\n"


class AnalyzeSimionTransportMetricsTests(unittest.TestCase):
    @staticmethod
    def summary(transmission: float = 0.5) -> dict:
        return {"solver": "SIMION 2020", "particles": 4, "transmission": transmission}

    def test_base_paired_preserves_summary_transmission_difference(self) -> None:
        result = evaluate(
            metric_kind="base_paired", project_id="fixture", parent_resolved_design_sha256="A" * 64,
            case_set="primary_and_zero_axial_control", primary_case_id="rf_on",
            primary_summary=self.summary(0.75), primary_state=None,
            control_case_id="zero_rf_control", control_summary=self.summary(0.25), control_state=None,
        )
        self.assertEqual(result["role"], "multipole_simion_finite_3d_transport_metrics")
        self.assertEqual(result["cases"]["rf_on"]["transmission_fraction"], 0.75)
        self.assertEqual(result["rf_minus_zero_transmission"], 0.5)

    def test_primary_and_rf_off_count_only_canonical_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, control = root / "primary.csv", root / "control.csv"
            primary.write_text(HEADER + "1,handoff,transmitted\n2,terminal,transmitted\n")
            control.write_text(HEADER + "1,handoff,transmitted\n2,handoff,transmitted\n")
            primary_result = evaluate(
                metric_kind="primary", project_id="fixture", parent_resolved_design_sha256="A" * 64,
                case_set="primary_only", primary_case_id="rf_on", primary_summary=self.summary(),
                primary_state=primary,
            )
            control_result = evaluate(
                metric_kind="rf_off_energy_control", project_id="fixture", parent_resolved_design_sha256="A" * 64,
                case_set="primary_and_rf_off_energy_control", primary_case_id="rf_on",
                primary_summary=self.summary(), primary_state=primary,
                control_case_id="rf_off", control_summary=self.summary(), control_state=control,
            )
        self.assertEqual(primary_result["primary_handoff_transmission"], 0.25)
        self.assertEqual(control_result["primary_handoff_transmission"], 0.25)
        self.assertEqual(control_result["control_handoff_transmission"], 0.5)

    def test_base_primary_preserves_its_existing_no_control_contract(self) -> None:
        result = evaluate(
            metric_kind="base_primary", project_id="fixture", parent_resolved_design_sha256="A" * 64,
            case_set="primary_only", primary_case_id="rf_on", primary_summary=self.summary(),
            primary_state=None,
        )
        self.assertNotIn("primary_handoff_transmission", result)
        self.assertIn("no zero-RF control", result["claim_limit"])


class FrozenTransportMetricsTests(unittest.TestCase):
    def test_actual_frozen_module_is_stdlib_only_and_missing_module_cannot_fallback(self):
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "code"
            paths = enumerate_python_sources(repo, package_roots=["src/msplatform"],
                                             provider_root="src/msplatform")
            selected = "src/msplatform/analysis/rf_transport_metrics.py"
            self.assertIn(selected, paths)
            self.assertNotIn("projects/rf_multipole_ion_optics/analysis/analyze_simion_transport_metrics.py", paths)
            for relative in paths:
                (snapshot / relative).parent.mkdir(parents=True, exist_ok=True)
                freeze_file(repo / relative, snapshot / relative)
            code = """import sys,pathlib
sys.path.insert(0,sys.argv[1])
from msplatform.analysis import rf_transport_metrics as metrics
assert pathlib.Path(metrics.__file__).is_relative_to(pathlib.Path(sys.argv[1]))
assert not any(k.split('.')[0] in ('projects','common','integrations','numpy','scipy') for k in sys.modules)
result=metrics.evaluate(metric_kind='base_primary',project_id='fixture',parent_resolved_design_sha256='A'*64,case_set='primary_only',primary_case_id='rf_on',primary_summary={'particles':4,'transmission':0.5},primary_state=None)
assert result['status']=='UNQUALIFIED'
"""
            command = [sys.executable, "-I", "-S", "-B", "-c", code, str(snapshot / "src")]
            positive = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            (snapshot / selected).unlink()
            negative = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn("ImportError", negative.stderr)

    def test_actual_cli_preserves_four_modes_and_missing_csv_rejects(self):
        from msplatform.analysis import rf_transport_metrics as metrics
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            summary=root/'summary.json';summary.write_text(json.dumps(dict(particles=4,transmission=.5)))
            state=root/'state.csv';state.write_text(HEADER+'1,handoff,transmitted\n2,terminal,unknown\n')
            for kind in ('base_paired','base_primary','rf_off_energy_control','primary'):
                output=root/(kind+'.json')
                command=[sys.executable,'-I','-S','-B',str(Path(metrics.__file__)),
                         '--metric-kind',kind,'--project-id','fixture','--parent-resolved-design-sha256','A'*64,
                         '--case-set','primary_only','--primary-case-id','rf_on','--primary-summary',str(summary),
                         '--primary-state',str(state),'--control-case-id','rf_off','--control-summary',str(summary),
                         '--control-state',str(state),'--output',str(output)]
                actual=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
                self.assertEqual(actual.returncode,0,actual.stderr)
                expected=metrics.evaluate(metric_kind=kind,project_id='fixture',parent_resolved_design_sha256='A'*64,
                    case_set='primary_only',primary_case_id='rf_on',primary_summary=dict(particles=4,transmission=.5),
                    primary_state=state,control_case_id='rf_off',control_summary=dict(particles=4,transmission=.5),control_state=state)
                self.assertEqual(json.loads(output.read_text()),expected)
            state.unlink()
            failed=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn('FileNotFoundError',failed.stderr)
