"""Continuous RF-IP software contract."""
import tempfile
import unittest
from pathlib import Path
from integrations.tests import test_ip_compiler as ip_fixture
from common.contracts import test_simion_tracking_execution as tracking_fixture
from msplatform.backends.simion.ip_compiler import compile_ip_assembly_geometry
from msplatform.backends.simion.rf_tracking_execution import plan_rf_tracking_workbench
from msplatform.execution.resources import resource_path


class RfIpTrackingPlanTests(unittest.TestCase):
    def test_actual_joint_source_produces_one_parent_with_all_native_ids(self):
        fixture=ip_fixture.IpCompilerTests(methodName='runTest');fixture.setUp()
        compiled=compile_ip_assembly_geometry(fixture.assembly,numerics=fixture.numerics)
        sources=tracking_fixture.TrackingExecutionPlanTests(methodName='runTest');sources.setUp()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();base=root/'producer/parent'
            rec=lambda suffix: {'path':str(base)+suffix,'bytes':1,'sha256':'A'*64}
            asset=dict(carrier_record=rec('.pa0'),family_records=[rec('.pa-surf')],witness_record=rec('.csv'))
            plan=plan_rf_tracking_workbench(compiled,carriers={'parent':asset},run_directory=root/'run',
                program='-- inert',native_source_rows=sources.plan()['native_source_rows'],native_path_resource=resource_path('native_run_path.lua'))
            self.assertEqual(len(plan.input_copies),1)
            self.assertEqual(Path(plan.input_copies[0]['source_record']['path']).name,'1_instance_seed.iob')
            self.assertEqual([op['success_marker'] for op in plan.operations],['RF_IP_TRACKING_IOB=PASS','RF_IP_TRACKING_IOB_REOPEN=PASS'])
            spec=plan.materializations[str(root/'run/inputs/tracking_iob.lua')]
            self.assertIn('rf_ip_tracking_iob',spec);self.assertIn('parent.pa0',spec)
            self.assertEqual(len(compiled.frontend_geometry['electrode_bindings']['ion_processor']),15)
            with self.assertRaisesRegex(ValueError,'exact field domains'):
                plan_rf_tracking_workbench(compiled,carriers={'ion_processor':asset},run_directory=root/'run',
                    program='-- inert',native_source_rows=sources.plan()['native_source_rows'],native_path_resource=resource_path('native_run_path.lua'))
