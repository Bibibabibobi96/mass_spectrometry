"""STEP adapter capability, actual B-rep and transport tests; no solver or GUI."""
import copy
import json
import math
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_geometry_members import real_snapshot
from msplatform.exporters.step import export_assembly_step


class StepExportTests(unittest.TestCase):
    def test_unknown_representation_and_options_reject_before_engine_import(self):
        for representation,options in (('simulation_reference',{}),('physical_solids',{}),
            ('physical_solids',dict(write_pcurves=True,precision_mode=True))):
            with self.subTest(representation=representation,options=options),self.assertRaises(ValueError):
                export_assembly_step({},destination=Path('not_written.step'),representation=representation,options=options)

    def test_missing_optional_engine_is_explicit_and_no_output(self):
        snapshot=real_snapshot()
        original=__import__
        def blocked(name,*args,**kwargs):
            if name=='cadquery': raise ImportError('controlled missing optional engine')
            return original(name,*args,**kwargs)
        with tempfile.TemporaryDirectory() as folder,patch('builtins.__import__',side_effect=blocked):
            path=Path(folder)/'model.step'
            with self.assertRaisesRegex(RuntimeError,'optional cad-step'):
                export_assembly_step(snapshot,destination=path,representation='physical_solids',options=dict(write_pcurves=True,precision_mode=0))
            self.assertFalse(path.exists())

    @unittest.skipUnless(importlib.util.find_spec('cadquery'),'optional CadQuery engine unavailable')
    def test_independent_analytic_solid_volumes_hole_and_off_axis_pose(self):
        import cadquery as cq
        from OCP.Precision import Precision
        from msplatform.exporters.step import _shape
        self.assertEqual(Precision.Approximation_s(),1e-6)
        self.assertEqual(Precision.Confusion_s(),1e-7)
        fixtures=[
            (dict(kind='rod',center_xy_mm=[2,-3],z_min_mm=1,z_max_mm=6,radius_mm=2),math.pi*4*5,2*math.pi*2*5+2*math.pi*4),
            (dict(kind='rod',center_xy_mm=[2,-3],z_min_mm=1,z_max_mm=6,semi_major_axis_mm=3,semi_minor_axis_mm=2,major_axis_angle_rad=.37),math.pi*3*2*5,2*math.pi*3*5+2*math.pi*3*2),
            (dict(kind='annulus',center_xy_mm=[2,-3],z_min_mm=1,z_max_mm=6,inner_radius_mm=1,outer_radius_mm=3),math.pi*(9-1)*5,2*math.pi*(3+1)*5+2*math.pi*(9-1)),
        ]
        for spec,volume,area_upper in fixtures:
            with self.subTest(shape=spec):
                shape=_shape(cq,spec)
                self.assertTrue(shape.isValid())
                self.assertLessEqual(abs(shape.Volume()-volume),1e-6*area_upper)
        annulus=_shape(cq,fixtures[2][0])
        self.assertFalse(annulus.isInside((2,-3,3),1e-7))
        self.assertTrue(annulus.isInside((4,-3,3),1e-7))
        from msplatform.exporters.step import assembly_geometry_members
        members=assembly_geometry_members(real_snapshot())
        shield=next(m for m in members if m['member_id']=='accelerator/grounded_shield')
        body=_shape(cq,shield['shape'])
        cut=shield['shape']['parts'][0]['tools'][1]
        x,y,z=cut['center_mm'];width=cut['size_mm'][1]
        self.assertFalse(any(s.isInside((x,y,z),1e-7) for s in body.Solids()))
        self.assertTrue(any(s.isInside((x,y+width,z),1e-7) for s in body.Solids()))

    @unittest.skipUnless(importlib.util.find_spec('cadquery'),'optional CadQuery engine unavailable')
    def test_real_complete_assembly_step_roundtrip_and_no_source_mutation(self):
        import cadquery as cq
        snapshot=real_snapshot();before=copy.deepcopy(snapshot)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'鐪熷疄 瑁呴厤.step'
            report=export_assembly_step(snapshot,destination=path,representation='physical_solids',options=dict(write_pcurves=True,precision_mode=0))
            self.assertEqual(snapshot,before)
            self.assertEqual(len(report['excluded_members']),5)
            self.assertEqual({m['instance_id'] for m in report['exported_members']},{'multipole','oatof'})
            loaded=cq.importers.importStep(str(path)).val()
            self.assertTrue(loaded.isValid())
            expected=sum(m['volume_mm3'] for m in report['exported_members'])
            self.assertLessEqual(abs(loaded.Volume()-expected),1e-6*sum(m['surface_area_mm2'] for m in report['exported_members']))
            self.assertEqual(report['cad_profile']['occt_approximation'],1e-6)
            # Independent substitution of the real example's cyclic RF rotation.
            rf=snapshot['components_resolved']['multipole']['segmentation']['segmented_rod_array']['electrodes'][0]
            pose=next(r['transform'] for r in snapshot['composition_plan']['recipe']['instances'] if r['instance_id']=='multipole')
            self.assertEqual(pose['rotation'],[[0,0,1],[1,0,0],[0,1,0]])
            tx,ty,tz=pose['translation_mm']
            expected_center=((rf['z_min_mm']+rf['z_max_mm'])/2+tx,rf['center_x_mm']+ty,rf['center_y_mm']+tz)
            centers=[s.Center().toTuple() for s in loaded.Solids()]
            self.assertLessEqual(min(math.dist(c,expected_center) for c in centers),1e-6)
            self.assertEqual(len(loaded.Solids()),sum(m['solid_count'] for m in report['exported_members']))
            with self.assertRaises(ValueError): export_assembly_step(snapshot,destination=path,representation='physical_solids',options=dict(write_pcurves=True,precision_mode=0))


    def _publish_cad(self, root, snapshot, *, report_change=None, step_source=None):
        from msplatform.execution.manifest_records import file_record
        from msplatform.execution.terminal_publication import publish_terminal_state
        options = dict(write_pcurves=True,precision_mode=0)
        path = root / 'assembly.step'
        projection = export_assembly_step(snapshot,destination=path,representation='physical_solids',options=options)
        if step_source is not None:
            path.write_bytes(step_source.read_bytes())
        (root/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
        (root/'options.json').write_text(json.dumps(options),encoding='utf-8')
        data = dict(step=file_record(path),assembly_snapshot=file_record(root/'snapshot.json'),
                    export_options=file_record(root/'options.json'))
        report = dict(schema_version=1,role='owned_assembly_step_export',projection=projection,
            step_record=copy.deepcopy(data['step']),snapshot_record=copy.deepcopy(data['assembly_snapshot']),options_record=copy.deepcopy(data['export_options']))
        if report_change is not None: report_change(report)
        (root/'report.json').write_text(json.dumps(report),encoding='utf-8')
        data['report'] = file_record(root/'report.json')
        manifest = dict(schema_version=2,role='simulation_run_manifest',status='failed',inputs={},outputs=list(data.values()),
            products={'cad':dict(schema_version=1,kind='cad_geometry',status='complete',metadata={},data=data)})
        run = root/'publication';run.mkdir()
        publish_terminal_state(run,{'status':'failed'},manifest)
        return dict(manifest=file_record(run/'run_manifest.json'),product_id='cad')

    @unittest.skipUnless(importlib.util.find_spec('cadquery'),'optional CadQuery engine unavailable')
    def test_public_inspection_cold_step_probes_no_export_tools_or_writes(self):
        from msplatform import api
        from msplatform.exporters.step import assembly_geometry_members
        from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition
        snapshot = real_snapshot()
        shield = next(m for m in assembly_geometry_members(snapshot) if m['member_id']=='accelerator/grounded_shield')
        cut = shield['shape']['parts'][0]['tools'][1]
        x,y,z = cut['center_mm'];width = cut['size_mm'][1]
        transform = RigidTransform.from_contract(shield['transform'])
        # World points are direct transforms of the original independent hole oracle.
        probes = [dict(probe_id=name,point_mm=list(transform.transform_position(FramedPosition(transform.from_frame_id,point)).coordinates_mm))
                  for name,point in [('opening',(x,y,z)),('wall',(x,y+width,z))]]
        checks = dict(schema_version=1,kind='physical_solids_step_v1',probes=probes)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);ref = self._publish_cad(root,snapshot)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('subprocess.Popen',side_effect=AssertionError('tool')), \
                 patch.object(Path,'mkdir',side_effect=AssertionError('mkdir')), \
                 patch.object(Path,'write_text',side_effect=AssertionError('write')), \
                 patch('msplatform.exporters.step.export_assembly_step',side_effect=AssertionError('export')):
                result = api.inspect_cad(ref,checks=checks)
                self.assertEqual(result,api.inspect_cad(api.open_artifact(ref,expected_kind="cad_geometry"),checks=checks))
            self.assertEqual(result['status'],'consistent')
            self.assertEqual([r['actual_step_inside'] for r in result['probes']],[False,True])
            self.assertEqual(result['solid_count'],result['expected_solid_count'])
            self.assertLessEqual(abs(result['volume_residual_mm3']),result['volume_serialization_bound_mm3'])
            self.assertEqual(result['producer']['status'],'failed')
            self.assertEqual(result['scientific_qualification'],'not_granted')
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    @unittest.skipUnless(importlib.util.find_spec('cadquery'),'optional CadQuery engine unavailable')
    def test_inspection_rejects_bound_report_mismatch_and_reports_wrong_step(self):
        import cadquery as cq
        from msplatform import api
        checks = dict(schema_version=1,kind='physical_solids_step_v1',probes=[])
        mutations = [lambda r:r['step_record'].update(sha256='A'*64),
                     lambda r:r['projection'].update(length_unit='m'),
                     lambda r:r['projection']['exported_members'].pop(),
                     lambda r:r['projection']['cad_profile'].update(length_error_bound_mm=1.)]
        for change in mutations:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                ref = self._publish_cad(Path(folder),real_snapshot(),report_change=change)
                with self.assertRaises(ValueError): api.inspect_cad(ref,checks=checks)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);wrong = root/'wrong.step'
            cq.exporters.export(cq.Workplane('XY').box(1,1,1),str(wrong))
            ref = self._publish_cad(root,real_snapshot(),step_source=wrong)
            result = api.inspect_cad(ref,checks=checks)
            self.assertEqual(result['status'],'mismatch')
            self.assertIn('solid_count_differs',result['failed_checks'])
            for bad in (dict(checks,schema_version=True),dict(checks,kind='all_holes'),dict(checks,extra=True),
                        dict(checks,probes=[dict(probe_id='bad',point_mm=[float('nan'),0,0])])):
                with self.subTest(checks=bad),self.assertRaises(ValueError): api.inspect_cad(ref,checks=bad)

    @unittest.skipUnless(importlib.util.find_spec('cadquery'),'optional CadQuery engine unavailable')
    def test_inspection_uses_resolver_locations_and_missing_engine_is_explicit(self):
        from msplatform import api
        import shutil
        checks = dict(schema_version=1,kind='physical_solids_step_v1',probes=[])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);original = root/'original';original.mkdir()
            ref = self._publish_cad(original,real_snapshot())
            moved = root/'relocated';shutil.copytree(original,moved);shutil.rmtree(original)
            def resolver(record, base):
                return (moved/'publication'/Path(record['path']).name if Path(record['path']).parent.name=='publication'
                        else moved/Path(record['path']).name)
            source = api.open_artifact(ref,expected_kind='cad_geometry',resolver=resolver)
            result = api.inspect_cad(source,checks=checks)
            self.assertEqual(result['status'],'consistent')
            self.assertEqual(source.data_path('step'),moved/'assembly.step')
            original_import = __import__
            def blocked(name,*args,**kwargs):
                if name=='cadquery': raise ImportError('controlled missing optional dependency')
                return original_import(name,*args,**kwargs)
            with patch('builtins.__import__',side_effect=blocked),self.assertRaisesRegex(RuntimeError,'optional cad-step'):
                api.inspect_cad(source,checks=checks)
            source.data_path('step').write_bytes(b'tampered STEP')
            with self.assertRaisesRegex(AssertionError,'changed'):
                api.inspect_cad(source,checks=checks)


if __name__=='__main__': unittest.main()
