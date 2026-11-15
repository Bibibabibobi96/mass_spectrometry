"""Pure schedule span arithmetic; no canonical IP owner or native claims."""
import copy
import unittest
from common.contracts import test_generic_scalar_binding as fixture_module
from msplatform.backends.simion.generic_scalar_binding import compile_linear_terms

class NeutralScheduleSpanTests(unittest.TestCase):
    def test_complete_keyed_unit_span_and_missing_basis(self):
        fixture=fixture_module.GenericScalarTests(methodName='runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        drive=copy.deepcopy(fixture.drive);drive.pop('pulse');drive['ip_schedule']={}
        drive['groups']['second']['body']={'kind':'ip_schedule','schedule_index':1}
        samples={key:{'request':value['request'],'weights':value['weights']} for key,value in fixture.samples.items()}
        result=compile_linear_terms(fixture.projection,drive,samples)
        self.assertIn('schedule_0',result['terms'])
        with self.assertRaisesRegex(ValueError,'span'):
            compile_linear_terms(fixture.projection,drive,{'one':samples['one']})
        del drive['ip_schedule']
        with self.assertRaisesRegex(ValueError,'schedule authority'):
            compile_linear_terms(fixture.projection,drive,samples)
