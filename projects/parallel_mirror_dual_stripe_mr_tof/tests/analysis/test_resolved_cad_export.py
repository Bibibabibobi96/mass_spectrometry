"""Pure geometry/BOM checks; no SolidWorks licence or external PA dependency."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import (
    compile_parts,rectangle,member,bounds_mm,verify_assembly_leaves,PROJECT_TRANSFORM,reopen_owned_part,close_owned_parts,
    open_reference_document,save_step_document,original_stripe_instances,save_exchange_document,inspect_exchange_geometry,
    delivery_paths,publish_validated_delivery,verify_preserved_bspline_edges,omit_mounting_holes,electrical_step_groups,mass_property_volume_levels,save_trimmed_curve_samples,compare_trimmed_curve_samples,individual_step_groups,connected_step_groups)


def fixture():
    def box(lo,hi):
        return {f'{a}_{s}_mm':(lo if s=='min' else hi)[i] for s in ('min','max') for i,a in enumerate('xyz')}
    detector=dict(id=25,box=[-1,-4,5,1,-2,6])
    g=dict(mirror_electrodes=[dict(id=2,box=[-5,-10,10,5,10,12],beam_slot=[-1,-9,9,1,9,13])],
           mirror_ground_shields=[],mirror_e_closures=[],stripe_electrodes=[],
           central_ground_electrodes=[],central_ground_slots=[],prism_electrodes=[],prism_ground_shields=[],detector=detector)
    oa=dict(local_to_pa_translation_mm=[0,2,0],grounded_enclosure=dict(component_electrode_id=15,
           outer_box_mm=box([-3,-3,0],[3,3,5]),cavity_box_mm=box([-2,-2,0],[2,2,4]),
           exit_opening_box_mm=box([-1,-1,0],[1,1,1])),
           repeller=dict(component_electrode_id=22,solid_box_mm=box([-2,-2,4],[2,2,5])),grid_supports=[],rings=[])
    a=dict(analyzer_electrode_voltages_v=list(range(20)),assembly=dict(accelerator_resolved_electrodes=oa,
           accelerator_iob_origin_mm=[0,-12,-1],detector=detector),
           component_voltages_v=[dict(component_namespace=ns,component_electrode_id=i,voltage_v=v)
             for ns,i,v in [('accelerator',15,0),('accelerator',22,300),('detector',25,0)]],
           boundary_contract=dict(box_mm=[0,-20,-20,10,20,20]))
    return g,a


def publication_fixture(directory):
    root=Path(directory)/'source';root.mkdir();(root/'inputs').mkdir();(root/'cad').mkdir()
    parts=[dict(name=f'part_{i:02}',native=str(root/'cad'/f'part_{i:02}.SLDPRT'),
        exchange=str(root/'cad'/f'part_{i:02}.x_t'),solid_count=int(i<45),sheet_count=int(i>=45),
        original_native_source='audited_fixture' if i<5 else None,
        machining_hole_variant={'variant':'validated_no_hole_fixture'} if i<5 else None) for i in range(53)]
    assemblies=[dict(name=name,assembly_native=str(root/'cad'/(name+'.SLDASM')),
        assembly_exchange=str(root/'cad'/(name+'.x_t'))) for name in ['mrtof_assembly']+[f'assembly_group_{i}' for i in range(6)]]
    validation=dict(status='PASS',component_count=53,parts=parts,subassemblies=assemblies[1:],mounting_holes_omitted=True,
        qualification='engineering_geometry_only',**assemblies[0])
    paths=delivery_paths(validation,root,original_curves=True)
    for path in paths:path.write_bytes(b'fixture payload')
    (root/'cad_validation.json').write_text(json.dumps(validation))
    (root/'run_config.json').write_text('{}')
    source_zip=root/'mrtof_cad_delivery.zip'
    with zipfile.ZipFile(source_zip,'w') as archive:
        for path in paths:archive.write(path,path.relative_to(root).as_posix())
    def record(path):
        payload=path.read_bytes();return dict(path=str(path),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
    physical={key:root/'inputs'/name for key,name in
              [('geometry','resolved_geometry.json'),('authority','frozen_input.json'),('materialization','assembly_materialization.json')]}
    manifest=dict(status='success',project='parallel_mirror_dual_stripe_mr_tof',run_id='sealed-fixture',
        run_config=record(root/'run_config.json'),inputs={k:record(p) for k,p in physical.items()},
        outputs=[record(p) for p in paths+[source_zip]])
    (root/'run_manifest.json').write_text(json.dumps(manifest))
    guide=Path(directory)/'overview.docx'
    doc_manifest=document_fixture(guide,'\n'.join(p['name'] for p in parts+assemblies))
    return root,guide,physical,manifest,doc_manifest


def document_fixture(path,text):
    # A real minimal WordprocessingML package; split runs exercise name recovery.
    paragraphs=''.join('<w:p><w:r><w:t>'+escape(p[:-2])+'</w:t></w:r><w:r><w:t>'+escape(p[-2:])+'</w:t></w:r></w:p>' for p in text.splitlines())
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as document:
        document.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        document.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        document.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+paragraphs+'</w:body></w:document>')
    manifest=path.with_suffix('.manifest.json');payload=path.read_bytes()
    manifest.write_text(json.dumps(dict(status='success',run_id='word-fixture',outputs=[dict(path=str(path),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())])))
    return manifest


class CadPlanTests(unittest.TestCase):
    def test_tilted_mirror_uses_resolved_polygons_and_slots_not_bounds(self):
        geometry,authority=fixture()
        electrode=geometry['mirror_electrodes'][0]
        polygon=[[-10,10.2],[10,9.8],[10,11.8],[-10,12.2]]
        hole=[[-9,9.18],[9,8.82],[9,12.82],[-9,13.18]]
        electrode.update(x=[-5,5],polygon_yz_mm=polygon,
            holes=[dict(x=[-1,1],polygon_yz_mm=hole)])
        shield=copy.deepcopy(electrode)
        shield['role']='inner_stripe_facing_4mm_slot'
        geometry['mirror_ground_shields']=[shield]
        geometry['mirror_inner_shield_slot']=electrode['beam_slot']
        closure=copy.deepcopy(electrode)
        closure.update(id=5,holes=[])
        geometry['mirror_e_closures']=[closure]
        parts=compile_parts(geometry,authority)
        for part in parts[:3]:
            self.assertEqual(part['solids'],[dict(x=[-5,5],polygon_yz_mm=polygon)])
            self.assertNotEqual(part['solids'],[rectangle(electrode['box'])])
        self.assertEqual(parts[0]['cuts'],[dict(x=[-1,1],polygon_yz_mm=hole)])
        self.assertEqual(parts[1]['cuts'],parts[0]['cuts'])
        self.assertEqual(parts[2]['cuts'],[])
        self.assertEqual(parts[2]['voltage_v'],authority['analyzer_electrode_voltages_v'][4])

    def test_individual_step_splits_same_voltage_and_excludes_c0_from_view(self):
        with tempfile.TemporaryDirectory() as task:
            root=Path(task);raw=root/'sample.json';raw.write_text('{}')
            def row(name):return dict(name=name,solid_count=1,sheet_count=0,project_transform=list(PROJECT_TRANSFORM),project_box_mm=[0]*6,trimmed_curve_sample_files=[str(raw)])
            names=['positive','negative','c0_reference_x_0'];rows=[row(name) for name in names]
            groups=[dict(name='grounded',voltage_v=0,optional_boundary_reference=False,rows=rows[:2],parts=[dict(name=name,voltage_v=0) for name in names[:2]]),
                dict(name='c0_boundary_reference',voltage_v=0,optional_boundary_reference=True,rows=rows[2:],parts=[dict(name=names[2],voltage_v=0)])]
            state=root/'cad_api_state.json';state.write_text(json.dumps(dict(electrical_step_reopen={g['name']:dict(expected=g['rows']) for g in groups})))
            records=[dict(path=str(path.resolve()),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in (state,raw)]
            (root/'run_manifest.json').write_text(json.dumps(dict(status='success',outputs=records)))
            result=individual_step_groups(groups,root)
            self.assertEqual([g['name'] for g in result],['positive','negative','c0_reference_x_negative','mrtof_electrode_assembly'])
            self.assertEqual([r['name'] for r in result[-1]['rows']],names[:2])
            self.assertTrue(result[-1]['overview_only'])
            raw.write_text('tampered')
            with self.assertRaisesRegex(ValueError,'identity'):individual_step_groups(groups,root)
    def test_zero_thickness_sheet_does_not_require_solid_mass_object(self):
        document=SimpleNamespace(ClearSelection2=lambda _:None,Extension=SimpleNamespace(CreateMassProperty2=None),GetBodies2=lambda kind,_:[])
        self.assertEqual(mass_property_volume_levels(document),{'0':0.0,'1':0.0,'2':0.0})
        document.GetBodies2=lambda kind,_:[object()]
        with self.assertRaisesRegex(RuntimeError,'unavailable'):mass_property_volume_levels(document)
    def test_step_line_endpoints_roundoff_does_not_require_interior_overlap(self):
        with tempfile.TemporaryDirectory() as task:
            files=[]
            for name,points in [('native',[[0,0,0],[1,0,0]]),('step',[[1e-12,0,0],[1-1e-12,0,0]])]:
                path=Path(task)/(name+'.json');path.write_text(json.dumps(dict(edges=[dict(edge_ordinal=0,is_bspline=False,world_points_mm=points)])));files.append(str(path))
            result=compare_trimmed_curve_samples(files[:1],files[1:])
            self.assertLess(result['max_sampled_delta_mm'],1e-10)
    def test_finite_step_geometry_uses_world_points_not_curve_parameters(self):
        with tempfile.TemporaryDirectory() as task:
            root=Path(task);edges=[]
            for offset in (0,0.001,0.006):
                points=[[i/2000,offset+(i/2000)**2,3] for i in range(2001)]
                edge=dict(edge_ordinal=1,is_bspline=True,world_points_mm=points)
                path=root/f'{offset}.json';path.write_text(json.dumps(dict(edges=[edge])));edges.append(str(path))
            result=compare_trimmed_curve_samples(edges[:1],edges[1:2])
            self.assertAlmostEqual(result['max_sampled_delta_mm'],0.001)
            with self.assertRaisesRegex(RuntimeError,'approved'):compare_trimmed_curve_samples(edges[:1],edges[2:])

    def test_step_engineering_volume_is_reported_native_remains_strict(self):
        with tempfile.TemporaryDirectory() as task:
            path=Path(task)/'raw.json';path.write_text(json.dumps(dict(edges=[])))
            row=dict(name='part',native='owned/part.SLDPRT',project_box_mm=[0]*6,volume_mm3=100,
                solid_count=1,sheet_count=0,trimmed_curve_sample_files=[str(path)])
            leaf=dict(name='part',native_reference=row['native'],world_box_mm=[0.001]*6,volume_mm3=100.002,
                solid_count=1,sheet_count=0,trimmed_curve_sample_files=[str(path)],transform=list(PROJECT_TRANSFORM))
            inspected=dict(leaf_count=1,leaves=[leaf])
            verify_assembly_leaves(inspected,[row],native=False,engineering_step=True)
            self.assertAlmostEqual(leaf['volume_delta_mm3'],0.002)
            with self.assertRaisesRegex(RuntimeError,'geometry/volume'):verify_assembly_leaves(inspected,[row],native=True,engineering_step=True)
    def test_curve_samples_are_saved_before_later_comparison_failure(self):
        curve=SimpleNamespace(IsBcurve=True,Identity=3006,Evaluate2=lambda u,d:[u,.02,.03],GetClosestPointOn=lambda x,y,z:[x,y,z,x,0])
        packed=struct.unpack('d',struct.pack('ii',0,1))[0]
        edge=SimpleNamespace(GetCurve=curve,GetCurveParams2=[0,.02,.03,1,.02,.03,0,1,0,0,packed])
        body=SimpleNamespace(GetEdges=[edge]);document=SimpleNamespace(GetBodies2=lambda kind,hidden:[body])
        with tempfile.TemporaryDirectory() as folder:
            paths=save_trimmed_curve_samples(document,PROJECT_TRANSFORM,Path(folder),sample_count=5)
            with self.assertRaises(RuntimeError):verify_assembly_leaves({'leaf_count':0},[{}],native=False)
            result=json.loads(Path(paths[0]).read_text())
            self.assertEqual(result['edges'][0]['endpoint_delta_m'],0)
            self.assertEqual(result['edges'][0]['local_points_m'][2],[.5,.02,.03])
            self.assertEqual(result['edges'][0]['world_points_mm'][2],[30.,500.,20.])
            self.assertFalse(Path(paths[0]+'.part').exists())

    def test_high_accuracy_mass_properties_use_official_levels_and_com_member(self):
        class Mass:
            AccuracyLevel=0
            Recalculate=True
            @property
            def Volume(self):return (10+self.AccuracyLevel)*1e-9
        mass=Mass();document=SimpleNamespace(ClearSelection2=lambda all:None,Extension=SimpleNamespace(CreateMassProperty2=mass))
        result=mass_property_volume_levels(document)
        for key,expected in [('0',10.),('1',11.),('2',12.)]:self.assertAlmostEqual(result[key],expected)
        self.assertTrue(mass.UseSystemUnits)

    def test_electrical_step_groups_keep_world_poses_and_separate_c0(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory);(source/'cad').mkdir();(source/'inputs').mkdir()
            specs=[dict(name=name,electrode_namespace=ns,electrode_id=i,voltage_v=v,geometry_kind='reference_sheet' if ns=='boundary' else 'physical_conductor')
                for name,ns,i,v in [('ground','analyzer',15,0),('s1a','analyzer',11,-27),('s1b','analyzer',12,-27),('c0','boundary',0,0)]]
            parts=[]
            for spec in specs:
                path=source/'cad'/(spec['name']+'.SLDPRT');path.write_bytes(b'native')
                parts.append(dict(name=spec['name'],native=str(path),project_transform=PROJECT_TRANSFORM))
            (source/'cad_parts_plan.json').write_text(json.dumps(specs))
            (source/'cad_validation.json').write_text(json.dumps(dict(status='PASS',mounting_holes_omitted=True,parts=parts)))
            physical={}
            for key,name in [('geometry','resolved_geometry.json'),('authority','frozen_input.json'),('materialization','assembly_materialization.json')]:
                path=source/'inputs'/name;path.write_bytes(b'physical');physical[key]=path
            records=[dict(path=str(path),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                for path in [source/'cad_parts_plan.json',source/'cad_validation.json']+[Path(p['native']) for p in parts]]
            (source/'run_manifest.json').write_text(json.dumps(dict(status='success',project='parallel_mirror_dual_stripe_mr_tof',outputs=records)))
            groups=electrical_step_groups(source,physical)
            self.assertEqual([g['name'] for g in groups],['grounded_conductors','potential_s1a','c0_boundary_reference'])
            self.assertEqual([len(g['rows']) for g in groups],[1,2,1])
            self.assertEqual(groups[1]['rows'][0]['project_transform'],PROJECT_TRANSFORM)
            self.assertTrue(groups[2]['optional_boundary_reference'])
            Path(parts[1]['native']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Sealed electrical CAD source differs'):electrical_step_groups(source,physical)

    def test_exact_modified_curve_check_preserves_controls_knots_and_all_edges(self):
        edge=dict(order=4,knots=[0,0,0,0,1,1,1,1],control_points_local_m=[[0,0,0],[.1,0,0],[.2,0,0],[.3,0,0]])
        reverse=copy.deepcopy(edge);reverse['control_points_local_m'].reverse()
        self.assertEqual(verify_preserved_bspline_edges([reverse],[edge])['max_control_delta_mm'],0)
        reverse['control_points_local_m'][0][0]+=2e-8
        with self.assertRaisesRegex(RuntimeError,'controls or knots'):verify_preserved_bspline_edges([reverse],[edge])
        with self.assertRaisesRegex(RuntimeError,'count'):verify_preserved_bspline_edges([],[edge])

    def test_no_hole_variant_selects_only_circular_owners_and_checks_fill_volume(self):
        features=[dict(name='hole',type='HoleWzd',underlying_type='HoleWzd',parents=['hole_profile'],suppressed=False),
            dict(name='pattern',type='MirrorPattern',underlying_type='MirrorPattern',parents=['hole','plane'],suppressed=False),
            dict(name='hole_profile',type='ProfileFeature',underlying_type='ProfileFeature',parents=[],suppressed=False),
            dict(name='beam_slot',type='ICE',underlying_type='Cut',parents=[],suppressed=False)]
        circles=[dict(native_center_mm=[0,0,0]),dict(native_center_mm=[.008*1000,0,0])]
        before=dict(features=features,cylindrical_faces=[dict(feature_name='hole' if i<3 else 'pattern',radius_mm=2.5,circular_trim_edges=circles) for i in range(6)],
            conical_faces=[dict(feature_name='hole',native_parameters=[0,0,0,0,1,0,.0025,1.0297442586766552])],volume_mm3=10000.)
        fill=6*math.pi*2.5**2*8+math.pi*2.5**3/(3*math.tan(1.0297442586766552))
        after=copy.deepcopy(before);after.update(cylindrical_faces=[],conical_faces=[],volume_mm3=10000+fill,
            planar_faces=[dict(world_normal=[1,0,0],world_root_mm=[x,0,0]) for x in (-2,2)])
        for f in after['features']:f['suppressed']=f['name']!='beam_slot'
        calls=[]
        class Feature:
            IsSuppressed=False
            def SetSuppression2(self,state,config,names):
                self.IsSuppressed=True;calls.append((self.name,state,config));return True
        objects={f['name']:Feature() for f in features}
        for name,obj in objects.items():obj.name=name
        document=SimpleNamespace(FeatureByName=lambda n:objects[n],EditRebuild3=True)
        module='projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad'
        with patch(module+'.machining_feature_inventory',side_effect=[before,after]),patch(module+'.inspect_bspline_edges',return_value=[]),patch(module+'.verify_preserved_bspline_edges',return_value={'edge_count':4}):
            result=omit_mounting_holes(document,dict(name='s1_electrode_11',project_transform=PROJECT_TRANSFORM,original_body_bspline_edges=[]))
        self.assertEqual(calls,[('pattern',0,1),('hole',0,1)])
        self.assertAlmostEqual(result['filled_volume_mm3'],fill)
        self.assertTrue(result['beam_slot_features_retained'])
        self.assertEqual(result['dependent_hole_profiles_suppressed'],['hole_profile'])
        reference=copy.deepcopy(before);reference['project_transform']=PROJECT_TRANSFORM
        document.EditRebuild3=lambda:(_ for _ in ()).throw(AssertionError('Already saved no-hole part must not rebuild'))
        with patch(module+'.machining_feature_inventory',return_value=after),patch(module+'.inspect_bspline_edges',return_value=[]),patch(module+'.verify_preserved_bspline_edges',return_value={'edge_count':4}):
            reused=omit_mounting_holes(document,dict(name='s1_electrode_11',project_transform=PROJECT_TRANSFORM,
                original_volume_mm3=10000,original_body_bspline_edges=[]),reference)
        self.assertTrue(reused['reused_saved_no_hole_geometry'])
        self.assertEqual(calls,[('pattern',0,1),('hole',0,1)])
        document.EditRebuild3=True
        bad=copy.deepcopy(after);bad['volume_mm3']+=1
        with patch(module+'.machining_feature_inventory',side_effect=[before,bad]),patch(module+'.inspect_bspline_edges',return_value=[]),patch(module+'.verify_preserved_bspline_edges',return_value={'edge_count':4}):
            with self.assertRaisesRegex(RuntimeError,'volume change'):
                omit_mounting_holes(document,dict(name='s1_electrode_11',project_transform=PROJECT_TRANSFORM,original_body_bspline_edges=[]))
        shared=copy.deepcopy(before);shared['features'][-1]['parents']=['hole_profile']
        with patch(module+'.machining_feature_inventory',side_effect=[shared,after]):
            with self.assertRaisesRegex(RuntimeError,'Non-hole feature'):
                omit_mounting_holes(document,dict(name='s1_electrode_11',project_transform=PROJECT_TRANSFORM,original_body_bspline_edges=[]))
        bad=copy.deepcopy(after);bad['features'][-1]['suppressed']=True
        with patch(module+'.machining_feature_inventory',side_effect=[before,bad]):
            with self.assertRaisesRegex(RuntimeError,'Non-hole feature'):
                omit_mounting_holes(document,dict(name='s1_electrode_11',project_transform=PROJECT_TRANSFORM,original_body_bspline_edges=[]))

    def test_publication_rejects_original_perforated_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root,guide,physical,manifest,doc_manifest=publication_fixture(directory)
            path=root/'cad_validation.json';validation=json.loads(path.read_text());validation['mounting_holes_omitted']=False
            payload=json.dumps(validation).encode();path.write_bytes(payload)
            record=next(r for r in manifest['outputs'] if r['path']==str(path));record.update(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
            (root/'run_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'no-hole'):
                publish_validated_delivery(root,guide,Path(directory)/'published',physical,doc_manifest,check_only=True)

    def test_document_publication_preserves_each_sealed_member_and_adds_english_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            root,guide,physical,_,doc_manifest=publication_fixture(directory);output=Path(directory)/'published'
            result=publish_validated_delivery(root,guide,output,physical,doc_manifest)
            self.assertFalse(result['commercial_cad_performed'])
            with zipfile.ZipFile(root/'mrtof_cad_delivery.zip') as original,zipfile.ZipFile(output/'mrtof_cad_delivery.zip') as published:
                self.assertEqual(set(published.namelist()),set(original.namelist())|{'CAD_OVERVIEW.docx'})
                for name in original.namelist():self.assertEqual(published.read(name),original.read(name))
                self.assertEqual(published.read('CAD_OVERVIEW.docx'),guide.read_bytes())
                self.assertNotIn('CAD_OVERVIEW.txt',published.namelist())
            with self.assertRaises(FileExistsError):publish_validated_delivery(root,guide,output,physical,doc_manifest)

    def test_document_publication_rejects_missing_guide_name_and_partial_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root,guide,physical,manifest,doc_manifest=publication_fixture(directory);output=Path(directory)/'published'
            with self.assertRaises(FileNotFoundError):publish_validated_delivery(root,guide.with_name('missing.docx'),output,physical,doc_manifest,check_only=True)
            document_fixture(guide,'part_00')
            with self.assertRaisesRegex(ValueError,'missing a delivered name'):publish_validated_delivery(root,guide,output,physical,doc_manifest,check_only=True)
            document_fixture(guide,'中文')
            with self.assertRaisesRegex(ValueError,'CJK'):publish_validated_delivery(root,guide,output,physical,doc_manifest,check_only=True)
            with zipfile.ZipFile(guide,'w') as fake:fake.writestr('plain.txt','renaming a ZIP is not Word')
            payload=guide.read_bytes();doc_manifest.write_text(json.dumps(dict(status='success',run_id='word-fixture',outputs=[dict(path=str(guide),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())])))
            with self.assertRaisesRegex(ValueError,'Word package'):publish_validated_delivery(root,guide,output,physical,doc_manifest,check_only=True)
            manifest['status']='interrupted';(root/'run_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'sealed successful'):publish_validated_delivery(root,guide,output,physical,doc_manifest,check_only=True)
            self.assertFalse(output.exists())

    def test_parasolid_scope_clears_selection_and_restores_preferences(self):
        class Sw:
            version=17;flatten=False
            def GetUserPreferenceIntegerValue(self,key):
                assert key==89;return self.version
            def SetUserPreferenceIntegerValue(self,key,value):
                assert key==89;self.version=value;return True
            def GetUserPreferenceToggle(self,key):
                assert key==12;return self.flatten
            def SetUserPreferenceToggle(self,key,value):
                assert key==12;self.flatten=value;return True
        class Document:
            cleared=False;GetType=2
            def ClearSelection2(self,value):self.cleared=value
        sw=Sw();document=Document()
        def save(doc,path):
            self.assertTrue(doc.cleared);self.assertEqual((sw.version,sw.flatten),(0,True));return (0,0)
        with patch('common.solidworks.import_step_to_solidworks.save_native_document',side_effect=save):
            self.assertEqual(save_exchange_document(sw,document,Path('owned/assembly.x_t')),(0,0))
        self.assertEqual((sw.version,sw.flatten),(17,False))
        with patch('common.solidworks.import_step_to_solidworks.save_native_document',side_effect=RuntimeError('save failure')):
            with self.assertRaisesRegex(RuntimeError,'save failure'):
                save_exchange_document(sw,document,Path('owned/assembly.x_t'))
        self.assertEqual((sw.version,sw.flatten),(17,False))

    def test_parasolid_part_does_not_set_assembly_only_toggle(self):
        class Sw:
            version=0
            def GetUserPreferenceIntegerValue(self,key):return self.version
            def SetUserPreferenceIntegerValue(self,key,value):self.version=value;return False
            def GetUserPreferenceToggle(self,key):raise AssertionError('Assembly option on part')
            def SetUserPreferenceToggle(self,key,value):raise AssertionError('Assembly option on part')
        document=SimpleNamespace(GetType=1,ClearSelection2=lambda value:None)
        with patch('common.solidworks.import_step_to_solidworks.save_native_document',return_value=(0,0)):
            self.assertEqual(save_exchange_document(Sw(),document,Path('owned/part.x_t')),(0,0))

    def test_flat_exchange_matches_world_bodies_and_rejects_sheet_conversion(self):
        class Body:
            def __init__(self,box,volume):self.box=box;self.volume=volume
            def GetExtremePoint(self,x,y,z,*out):
                point=[self.box[i+3] if d>0 else self.box[i] for i,d in enumerate((x,y,z))]
                return (True,*[v/1000 for v in point])
            def GetMassProperties(self,density):return [0,0,0,self.volume/1e9]
        class Document:
            GetType=1
            def GetBodies2(self,kind,visible):return [solid] if kind==0 else [sheet]
        solid=Body([-1,-2,-3,1,2,3],48);sheet=Body([-1,-2,4,1,2,4],0)
        rows=[dict(native='solid.SLDPRT',project_box_mm=solid.box,volume_mm3=48,solid_count=1,sheet_count=0),
              dict(native='sheet.SLDPRT',project_box_mm=sheet.box,volume_mm3=0,solid_count=0,sheet_count=1)]
        evidence=inspect_exchange_geometry(Document())
        verify_assembly_leaves(evidence,rows,native=False)
        evidence['leaves'][0]['solid_count']=0;evidence['leaves'][0]['sheet_count']=1
        with self.assertRaisesRegex(RuntimeError,'world geometry/volume'):
            verify_assembly_leaves(evidence,rows,native=False)

    def test_original_native_controls_are_not_fit_or_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            native=Path(directory)/'ion foil 1.SLDPRT';native.write_bytes(b'pure hash fixture, not supplier CAD')
            identity=[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0]
            points=[[0,0,1],[0,1,2],[0,2,2],[0,3,1]];knots=[0]*4+[1]*4
            curve=dict(basis='cubic_bspline',order=4,knots=knots,control_points_yz_mm=[p[1:] for p in points])
            contract=dict(dual_stripe=dict(theory_profile=dict(set_1=dict(lower_edge=curve))))
            audit=dict(status='success',documents=[dict(name=native.name,path=str(native),exact_local_box_mm=[0,0,1,0,3,2],volume_mm3=0,
                body_bspline_edges=[dict(order=4,knots=knots,edge_index=1,control_points_local_m=[[v/1000 for v in p] for p in points])])])
            geometry=dict(frame_id='frame',cad_body_topology_identity=dict(source_native_sha256=dict(ion_foil_1=hashlib.sha256(native.read_bytes()).hexdigest())))
            parent=dict(status='success',parent=dict(transform=identity));child=dict(components=[dict(instance_name='ion foil 1-3',solidworks_transform_array=identity)])
            frame=dict(target_frame='frame',target_from_source=dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0]))
            parts=[dict(name='s1_electrode_11',electrode_namespace='analyzer',electrode_id=11)]
            others=[dict(name=name,electrode_namespace=namespace,electrode_id=15,geometry_kind='physical_conductor',
                         project_transform=list(PROJECT_TRANSFORM)) for name,namespace in
                    [('mirror_ground_shield_1','analyzer'),('mirror_ground_shield_2','analyzer'),
                     ('oa_enclosure','accelerator'),('detector','detector')]]
            parts.extend(others)
            result=original_stripe_instances(parts,geometry,contract,audit,parent,child,frame)
            self.assertEqual(result[0]['project_transform'],identity)
            self.assertEqual(result[0]['original_curve_matches'][0]['max_control_delta_mm'],0)
            self.assertNotIn('original_native',parts[0])
            self.assertEqual(result[1:],others)
            wrong=copy.deepcopy(parts);wrong[0]['electrode_namespace']='accelerator'
            with self.assertRaisesRegex(ValueError,'electrical identity'):
                original_stripe_instances(wrong,geometry,contract,audit,parent,child,frame)
            curve['control_points_yz_mm'][1][1]+=.001
            with self.assertRaisesRegex(ValueError,'controls/knots differ'):
                original_stripe_instances(parts,geometry,contract,audit,parent,child,frame)

    def test_original_instance_pose_is_checked_per_saved_leaf(self):
        transform=list(PROJECT_TRANSFORM);transform[9]=.03
        row=dict(native='owned/original.SLDPRT',project_box_mm=[0]*6,volume_mm3=1,project_transform=transform)
        leaf=dict(name='original-1',native_reference=row['native'],world_box_mm=[0]*6,volume_mm3=1,transform=list(transform))
        verify_assembly_leaves(dict(leaf_count=1,leaves=[leaf]),[row],native=True)
        leaf['transform']=list(PROJECT_TRANSFORM)
        with self.assertRaisesRegex(RuntimeError,'world pose'):
            verify_assembly_leaves(dict(leaf_count=1,leaves=[leaf]),[row],native=True)
    def test_step_ap214_scope_restores_original_on_success_and_failure(self):
        class Sw:
            value=203
            def GetUserPreferenceIntegerValue(self,key):
                self.assert_key=key;return self.value
            def SetUserPreferenceIntegerValue(self,key,value):
                assert key==75;self.value=value;return True
        sw=Sw()
        with patch('common.solidworks.import_step_to_solidworks.save_native_document',return_value=(0,0)):
            self.assertEqual(save_step_document(sw,object(),Path('owned/assembly.step')),(0,0))
        self.assertEqual(sw.value,203)
        with patch('common.solidworks.import_step_to_solidworks.save_native_document',side_effect=RuntimeError('save failure')):
            with self.assertRaisesRegex(RuntimeError,'save failure'):save_step_document(sw,object(),Path('owned/assembly.step'))
        self.assertEqual(sw.value,203)
    def test_hidden_preload_restores_part_visibility_on_success_and_failure(self):
        class Sw:
            events=[];fail=False
            def DocumentVisible(self,visible,kind):self.events.append((visible,kind))
            def OpenDoc6(self,path,kind,options,configuration,error,warning):
                self.events.append((kind,options))
                if self.fail:raise RuntimeError('vendor failure')
                return object()
        sw=Sw();open_reference_document(sw,'owned/part.SLDPRT',1,None,None)
        self.assertEqual(sw.events,[(False,1),(1,3),(True,1)])
        sw.events=[];sw.fail=True
        with self.assertRaisesRegex(RuntimeError,'vendor failure'):
            open_reference_document(sw,'owned/assembly.SLDASM',2,None,None)
        self.assertEqual(sw.events,[(False,1),(2,3),(True,1)])
    def test_owned_part_windows_are_closed_before_cold_reopen(self):
        class Sw:
            live={'owned/part.SLDPRT'}
            def CloseDoc(self,title):self.live.discard(title)
            def GetOpenDocumentByName(self,path):return object() if path in self.live else None
        sw=Sw();rows=[dict(native='owned/part.SLDPRT')]
        with self.assertRaisesRegex(RuntimeError,'remains open'):
            close_owned_parts(sw,[],rows)
        close_owned_parts(sw,['owned/part.SLDPRT'],rows)

    def test_only_owned_detector_noncritical_property_error_can_repair(self):
        class Sw:
            code=2097152
            def OpenDoc6(self,path,kind,options,configuration,error,warning):
                error.value=self.code;return None
            def GetOpenDocSpec(self,path):return SimpleNamespace(Error=0,Warning=1)
            def OpenDoc7(self,settings):
                assert settings.Silent and settings.AutoRepair and not settings.CriticalDataRepair
                return SimpleNamespace(GetPathName='owned/Repaired_detector.SLDPRT')
        sw=Sw()
        _,repair=reopen_owned_part(sw,Path('owned/detector.SLDPRT'),allow_detector_property_repair=True)
        self.assertEqual(repair['original_error'],2097152)
        for name,allowed,code in [('mirror.SLDPRT',True,2097152),('detector.SLDPRT',False,2097152),('detector.SLDPRT',True,4194304)]:
            sw.code=code
            with self.assertRaisesRegex(RuntimeError,'reopen failed'):
                reopen_owned_part(sw,Path('owned')/name,allow_detector_property_repair=allowed)

    def test_saved_leaf_pose_and_individual_geometry_are_required(self):
        row=dict(project_box_mm=[-1,-2,-3,1,2,3],volume_mm3=12,native='owned/part.SLDPRT')
        leaf=dict(name='part-1',world_box_mm=row['project_box_mm'],volume_mm3=12,transform=list(PROJECT_TRANSFORM),
                  native_reference=row['native'])
        evidence=dict(leaf_count=1,leaves=[leaf])
        verify_assembly_leaves(evidence,[row],native=True)
        leaf['native_reference']='old-run/part.SLDPRT'
        with self.assertRaisesRegex(RuntimeError,'world geometry'):verify_assembly_leaves(evidence,[row],native=True)
        leaf['native_reference']=row['native']
        leaf['transform'][9]=.001
        with self.assertRaisesRegex(RuntimeError,'world pose'):verify_assembly_leaves(evidence,[row],native=True)
        leaf['world_box_mm']=[-1,-2,-3,1,2,4]
        with self.assertRaisesRegex(RuntimeError,'box_delta_mm.*volume_delta_mm3'):verify_assembly_leaves(evidence,[row],native=False)

    def test_bounds_use_exact_extrema_not_approximate_body_box(self):
        class Body:
            def GetBodyBox(self):raise AssertionError('Approximate boxes cannot validate dimensions')
            def GetExtremePoint(self,x,y,z,*out):
                return (True,*[[-.01,-.02,-.03][i] if d<0 else [.04,.05,.06][i] for i,d in enumerate((x,y,z))])
        class Document:
            def GetBodies2(self,kind,_):return [Body()] if kind==0 else []
        self.assertEqual(bounds_mm(Document()),[-30,-10,-20,60,40,50])

    def test_dispatch_object_is_not_invoked_as_default_member(self):
        class Dispatch:
            _oleobj_=object()
            def __call__(self):raise AssertionError('Feature has no default member')
        value=Dispatch();self.assertIs(member(value),value)
        self.assertEqual(member(lambda:'value'),'value')
    def test_box_pose_and_slot_preserved(self):
        g,a=fixture();parts=compile_parts(g,a);p=parts[0]
        self.assertEqual(p['solids'],[rectangle(g['mirror_electrodes'][0]['box'])])
        self.assertEqual(p['cuts'],[rectangle(g['mirror_electrodes'][0]['beam_slot'])])
        self.assertEqual(p['voltage_v'],1)

    def test_oa_full_translation_not_old_minus50_default(self):
        g,a=fixture();p=next(p for p in compile_parts(g,a) if p['name']=='oa_repeller')
        self.assertEqual(p['solids'][0],rectangle([-2,-12,3,2,-8,4]))
        self.assertEqual(p['voltage_v'],300)

    def test_oa_open_cavity_retains_redundant_exit_provenance(self):
        g,a=fixture();p=next(p for p in compile_parts(g,a) if p['name']=='oa_enclosure')
        self.assertEqual(len(p['cuts']),1)
        self.assertEqual(p['declared_redundant_cuts'][0]['source'],'exit_opening_box_mm')
        self.assertEqual(p['declared_redundant_cuts'][0]['reason'],'fully_contained_in_declared_cavity')
        e=a['assembly']['accelerator_resolved_electrodes']['grounded_enclosure']
        e['exit_opening_box_mm']['z_max_mm']=5
        p=next(p for p in compile_parts(g,a) if p['name']=='oa_enclosure')
        self.assertEqual(len(p['cuts']),2)
        self.assertNotIn('declared_redundant_cuts',p)

    def test_reference_boundary_has_no_manufacturing_thickness(self):
        g,a=fixture();refs=[p for p in compile_parts(g,a) if p['group']=='reference']
        self.assertEqual(len(refs),6)
        for p in refs:
            b=p['solids'][0]['box_mm']
            self.assertTrue(any(b[i]==b[i+3] for i in range(3)))
            self.assertEqual(p['geometry_kind'],'reference_sheet')

    def test_no_input_mutation(self):
        g,a=fixture();before=copy.deepcopy((g,a));compile_parts(g,a)
        self.assertEqual((g,a),before)

    def test_invalid_voltage_rejected(self):
        g,a=fixture();a['analyzer_electrode_voltages_v'][0]=float('nan')
        with self.assertRaises(ValueError):compile_parts(g,a)

    def test_detector_assembly_drift_rejected(self):
        g,a=fixture();a['assembly']['detector']=dict(id=25,box=[0]*6)
        with self.assertRaises(ValueError):compile_parts(g,a)

    def test_split_prism_parts_share_bias_but_not_merged(self):
        g,a=fixture();poly=[[0,0],[1,0],[0,1]]
        g['prism_electrodes']=[dict(id=16,parts=[dict(x=[-12,-2],polygon_yz_mm=poly),dict(x=[2,12],polygon_yz_mm=poly)])]
        p=[x for x in compile_parts(g,a) if x['group']=='prism']
        self.assertEqual(len(p),2);self.assertEqual([x['voltage_v'] for x in p],[15,15])

    def test_sampled_stripe_not_refitted(self):
        g,a=fixture();poly=[[0,1],[1,2],[2,1],[2,3],[1,4],[0,3]]
        g['stripe_electrodes']=[dict(id=11,x=[-12,12],polygon_yz_mm=poly,terminal_polygon_yz_mm=[[0,1],[-1,1],[-1,3],[0,3]])]
        g['stripe_slot']=[-2,0,-10,2,10,10]
        p=next(x for x in compile_parts(g,a) if x['group']=='stripe')
        self.assertEqual(p['solids'][0]['polygon_yz_mm'],poly)


class ConnectedStepContactsTests(unittest.TestCase):
    def test_real_export_merge_preserves_contact_details_and_boolean_scope(self):
        from unittest.mock import Mock
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import export_parts
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            group=dict(name='mirror_positive_a_ground_shield',voltage_v=0,optional_boundary_reference=False,
                connected_contact_repair=True,parts=[dict(name='mirror_positive_e01',voltage_v=0)],rows=[])
            row=dict(name=group['name'])
            details=dict(source_intersections=[dict(components=['a','shield'],volume_mm3=0)],
                solid_count_before=2,solid_count_after=1,sheet_support_contacts=[])
            sw=Mock();sw.RevisionNumber='30.5.0';sw.GetProcessID=1;sw.GetFirstDocument=None
            sw.GetUserPreferenceStringValue.return_value='saved template';sw.GetUserPreferenceToggle.return_value=False
            client=SimpleNamespace(GetActiveObject=Mock(side_effect=RuntimeError('fixture no active CAD')),
                dynamic=SimpleNamespace(Dispatch=Mock(return_value=sw)))
            modules={'pythoncom':SimpleNamespace(CoInitialize=Mock(),CoUninitialize=Mock(),com_error=RuntimeError),
                'win32com':SimpleNamespace(client=client),'win32com.client':client,
                'common.solidworks.installation':SimpleNamespace(resolve_solidworks_2022_root=lambda:root),
                'common.solidworks.import_step_to_solidworks':SimpleNamespace(CLEAN_PART_TEMPLATE=root/'part',ASSEMBLY_TEMPLATE=root/'assembly',
                    document_title=Mock(),save_native_document=Mock())}
            with patch.dict('sys.modules',modules),patch(
                'projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad.build_connected_step_part',
                return_value=(row,details)) as repair,patch(
                'projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad.save_assembly',return_value=dict(status='PASS')):
                result=export_parts([],root/'cad',electrical_groups=[group],reuse_native_samples=True)
            repair.assert_called_once()
            observed=result['electrical_groups'][0]
            self.assertIs(observed['connected_contact_repair'],True)
            self.assertEqual(observed['connected_contact_repair_details'],details)
            self.assertEqual(observed['voltage_v'],0)

    def test_reused_step_bytes_cannot_restore_old_voltage_metadata(self):
        from unittest.mock import Mock
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import export_parts
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);original=root/'sealed.step';original.write_bytes(b'sealed unchanged geometry')
            current=dict(name='linear_stripe',voltage_v=0,optional_boundary_reference=False,
                parts=[dict(name='linear_stripe',voltage_v=0)],rows=[],
                reuse_sealed_exchange=dict(name='linear_stripe',voltage_v=-27,parts=[dict(name='linear_stripe',voltage_v=-27)],
                    assembly_exchange=str(original),exchange_reopen=dict(leaves=[])))
            sw=Mock();sw.RevisionNumber='30.5.0';sw.GetProcessID=1;sw.GetFirstDocument=None
            sw.GetUserPreferenceStringValue.return_value='saved template'
            sw.GetUserPreferenceToggle.return_value=False
            client=SimpleNamespace(GetActiveObject=Mock(side_effect=RuntimeError('fixture no active CAD')),
                dynamic=SimpleNamespace(Dispatch=Mock(return_value=sw)))
            modules={'pythoncom':SimpleNamespace(CoInitialize=Mock(),CoUninitialize=Mock(),com_error=RuntimeError),
                'win32com':SimpleNamespace(client=client),'win32com.client':client,
                'common.solidworks.installation':SimpleNamespace(resolve_solidworks_2022_root=lambda:root),
                'common.solidworks.import_step_to_solidworks':SimpleNamespace(CLEAN_PART_TEMPLATE=root/'part',ASSEMBLY_TEMPLATE=root/'assembly',
                    document_title=Mock(),save_native_document=Mock())}
            with patch.dict('sys.modules',modules):
                result=export_parts([],root/'cad',electrical_groups=[current],reuse_native_samples=True)
            self.assertEqual(result['electrical_groups'][0]['voltage_v'],0)
            self.assertEqual(result['electrical_groups'][0]['parts'][0]['voltage_v'],0)
            self.assertEqual((root/'cad/linear_stripe.step').read_bytes(),original.read_bytes())

    def frozen_pose_fixture(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import _apply_mirror_convergence
        g,a=fixture();g['frame_id']='project_xyz'
        g['mirror_electrodes']=[]
        for index in range(5):
            lo,hi=10+index*5,14+index*5
            for negative in (False,True):
                g['mirror_electrodes'].append(dict(id=index+1+(5 if negative else 0),
                    box=[-5,-10,-hi if negative else lo,5,10,-lo if negative else hi],
                    beam_slot=[-1,-9,-hi-1 if negative else lo-1,1,9,-lo+1 if negative else hi+1]))
        g['mirror_ground_shields']=[dict(box=[-5,-10,8,5,10,10],role='inner_stripe_facing_4mm_slot'),
            dict(box=[-5,-10,-10,5,10,-8],role='inner_stripe_facing_4mm_slot')]
        g['mirror_e_closures']=[dict(id=5,box=[-5,-10,34,5,10,35]),dict(id=10,box=[-5,-10,-35,5,10,-34])]
        g['mirror_inner_shield_slot']=[-1,-9,-11,1,9,11]
        n=copy.deepcopy(g)
        n['mirror_convergence_transform']=_apply_mirror_convergence(
            dict(inner_face_z_mm=8,convergence_transform=dict(angle_deg=.025688744787259285,pivot_y_mm=0)),
            [n['mirror_electrodes'],n['mirror_ground_shields'],n['mirror_e_closures']],n['mirror_inner_shield_slot'])
        v=copy.deepcopy(a);v['analyzer_electrode_voltages_v']=[x+1 for x in a['analyzer_electrode_voltages_v']]
        return g,n,a,v

    def test_frozen_pose_validates_fourteen_mirrors_and_exact_reflection(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import frozen_mirror_pose_transforms
        values=self.frozen_pose_fixture();poses=frozen_mirror_pose_transforms(*values)
        self.assertEqual(len(poses),14)
        plus,minus=poses['mirror_positive_e01'],poses['mirror_negative_e06']
        self.assertEqual(plus[5],-minus[5]);self.assertEqual(plus[7],-minus[7])
        self.assertEqual(plus[10],minus[10]);self.assertEqual(plus[11],-minus[11])

    def test_frozen_pose_rejects_wrong_pivot_and_non_mirror_geometry(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import frozen_mirror_pose_transforms
        g,n,a,v=self.frozen_pose_fixture()
        wrong=copy.deepcopy(n);wrong['mirror_convergence_transform']['pivot_positive_project_mm'][1]=1
        with self.assertRaisesRegex(ValueError,'declared rigid pose'):
            frozen_mirror_pose_transforms(g,wrong,a,v)
        wrong=copy.deepcopy(n);wrong['detector']['box'][1]-=1
        with self.assertRaisesRegex(ValueError,'Non-mirror'):
            frozen_mirror_pose_transforms(g,wrong,a,v)

    def test_frozen_pose_rejects_aperture_or_component_voltage_changes(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import frozen_mirror_pose_transforms
        g,n,a,v=self.frozen_pose_fixture()
        wrong=copy.deepcopy(n);wrong['mirror_electrodes'][0]['holes'][0]['x'][0]-=.01
        with self.assertRaisesRegex(ValueError,'aperture differs'):
            frozen_mirror_pose_transforms(g,wrong,a,v)
        wrong=copy.deepcopy(n);points=wrong['mirror_electrodes'][0]['holes'][0]['polygon_yz_mm']
        points[0]=copy.deepcopy(points[1])
        with self.assertRaisesRegex(ValueError,'rigid rectangle'):
            frozen_mirror_pose_transforms(g,wrong,a,v)
        wrong=copy.deepcopy(v);wrong['component_voltages_v'][0]['voltage_v']=1
        with self.assertRaisesRegex(ValueError,'Non-analyzer'):
            frozen_mirror_pose_transforms(g,n,a,wrong)

    def test_sealed_native_retarget_uses_new_complete_voltages_and_remeasures_mirrors(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import expected_bounds_mm
        g,n,a,v=self.frozen_pose_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();(source/'inputs').mkdir();(source/'cad').mkdir()
            target=root/'target';target.mkdir();records=[];inputs={}
            def record(path):
                data=path.read_bytes();return dict(path=str(path.resolve()),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            for key,name,old,new in [('geometry','resolved_geometry.json',g,n),('authority','frozen_input.json',a,v),
                                     ('materialization','assembly_materialization.json',{}, {})]:
                prior=source/'inputs'/name;prior.write_text(json.dumps(old));inputs[key]=record(prior)
                (target/name).write_text(json.dumps(new))
            specs=compile_parts(g,a);rows=[]
            for spec in specs:
                native=source/'cad'/(spec['name']+'.SLDPRT');native.write_bytes(b'sealed exact-body fixture')
                records.append(record(native));rows.append(dict(name=spec['name'],native=str(native.resolve()),
                    project_transform=PROJECT_TRANSFORM,project_box_mm=expected_bounds_mm(spec) if spec['solids'] else [0]*6,volume_mm3=1,
                    solid_count=1,sheet_count=0))
            for name,value in [('cad_parts_plan.json',specs),('cad_validation.json',dict(status='PASS',mounting_holes_omitted=True,parts=rows))]:
                path=source/name;path.write_text(json.dumps(value));records.append(record(path))
            (source/'run_manifest.json').write_text(json.dumps(dict(status='success',project='parallel_mirror_dual_stripe_mr_tof',inputs=inputs,outputs=records)))
            paths={key:target/name for key,name in [('geometry','resolved_geometry.json'),('authority','frozen_input.json'),('materialization','assembly_materialization.json')]}
            with self.assertRaisesRegex(ValueError,'frozen input differs'):
                electrical_step_groups(source,paths)
            groups=electrical_step_groups(source,paths,frozen_mirror_pose=True)
            parts={part['name']:part for group in groups for part in group['parts']}
            expected={spec['name']:spec for spec in compile_parts(n,v)}
            self.assertEqual({name:part['voltage_v'] for name,part in parts.items()},
                             {name:part['voltage_v'] for name,part in expected.items()})
            moved=[row for group in groups for row in group['rows'] if row.get('regenerate_trimmed_curve_samples')]
            self.assertEqual(len(moved),14)
            self.assertTrue(all(row['source_project_transform']==PROJECT_TRANSFORM for row in moved))

    def test_boolean_uses_typed_output_parameter_and_preserves_sources(self):
        from unittest.mock import Mock
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import _body_operation
        target, tool = Mock(), Mock()
        result_body = object()
        target.Copy.return_value.Operations2.return_value = ((result_body,), 0)
        dispatch=Mock(side_effect=lambda body:body);client=SimpleNamespace(Dispatch=dispatch)
        with patch.dict('sys.modules',{'win32com':SimpleNamespace(client=client),'win32com.client':client}):
            bodies, error = _body_operation(target, tool, 15903)
        dispatch.assert_called_once_with(result_body)
        self.assertEqual(bodies, [result_body])
        self.assertEqual(error, 0)
        target.Copy.return_value.Operations2.assert_called_once_with(15903, tool.Copy.return_value)
        target.Operations2.assert_not_called()

    def test_connected_repair_rejects_tilted_geometry(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import export_resolved_cad
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);g,a=fixture()
            g['mirror_electrodes'][0]['polygon_yz_mm']=[[0,0],[1,1],[1,2],[0,1]]
            for key in ('mirror_slot','mirror_inner_shield_slot','stripe_slot'):
                g[key]=[]
            materialization=dict(analyzer_electrode_voltages_v=a['analyzer_electrode_voltages_v'],
                detector_box_mm=g['detector']['box'],collision_geometry=g)
            for name,value in [('geometry',g),('authority',a),('materialization',materialization)]:
                (root/(name+'.json')).write_text(json.dumps(value))
            argv=['export_resolved_cad','--geometry',str(root/'geometry.json'),'--authority',str(root/'authority.json'),
                '--materialization',str(root/'materialization.json'),'--output',str(root/'cad'),
                '--electrical-step-cad-run',str(root),'--individual-step-delivery-run',str(root),'--connected-step-contacts','--check-only']
            with patch('sys.argv',argv),patch.object(export_resolved_cad,'electrical_step_groups',return_value=[]),patch.object(export_resolved_cad,'individual_step_groups',return_value=[]):
                with self.assertRaisesRegex(ValueError,'parallel-mirror'):
                    export_resolved_cad.main()

    def contact_fixture(self, root):
        potentials = {
            'mirror_positive_e01':0,'mirror_ground_shield_1':0,
            'mirror_negative_e06':0,'mirror_ground_shield_2':0,
            'mirror_positive_e05':6000,'mirror_outer_closure_1':6000,
            'mirror_negative_e10':6000,'mirror_outer_closure_2':6000,
            'oa_enclosure':0,'oa_grid_frame_2':0,'oa_ideal_grid_sheet_2':0,
            'oa_grid_frame_1':4000,'oa_ideal_grid_sheet_1':4000,
            'p1_ground_shield':0,'p2_ground_shield':0,'c0_reference_x_negative':0,
        }
        groups=[]; previous=[]; records=[]
        for name, voltage in potentials.items():
            exchange=root/(name+'.step');exchange.write_bytes(b'sealed STEP fixture')
            records.append(dict(path=str(exchange.resolve()),bytes=exchange.stat().st_size,
                sha256=hashlib.sha256(exchange.read_bytes()).hexdigest()))
            part=dict(name=name,voltage_v=voltage,electrode_namespace='analyzer',electrode_id=1)
            groups.append(dict(name=name,voltage_v=voltage,optional_boundary_reference=name.startswith('c0_'),parts=[part],rows=[dict(name=name)]))
            previous.append(dict(name=name,assembly_exchange=str(exchange.resolve())))
        validation=root/'cad_validation.json';validation.write_text(json.dumps(dict(electrical_groups=previous)))
        records.append(dict(path=str(validation.resolve()),bytes=validation.stat().st_size,
            sha256=hashlib.sha256(validation.read_bytes()).hexdigest()))
        (root/'run_manifest.json').write_text(json.dumps(dict(status='success',outputs=records)))
        return groups

    def test_only_local_connected_sets_grouped_and_mapping_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);groups=self.contact_fixture(root);before=copy.deepcopy(groups)
            result=connected_step_groups(groups,root)
            repaired=[group for group in result if group.get('connected_contact_repair')]
            self.assertEqual(len(repaired),6)
            self.assertEqual(sum(len(group['parts']) for group in repaired),13)
            self.assertEqual(len(next(group for group in repaired if group['name']=='oa_grounded_enclosure_exit_grid')['parts']),3)
            self.assertEqual([group['name'] for group in result if group.get('reuse_sealed_exchange')],
                ['p1_ground_shield','p2_ground_shield','c0_reference_x_negative'])
            self.assertTrue(result[-1]['connected_overview'])
            self.assertEqual(len(result[-1]['parts']),15)
            self.assertEqual(groups,before)

    def test_different_voltage_contact_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);groups=self.contact_fixture(root)
            groups[1]['voltage_v']=1
            with self.assertRaisesRegex(ValueError,'Different-potential'):
                connected_step_groups(groups,root)

    def test_missing_component_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);groups=self.contact_fixture(root)
            with self.assertRaisesRegex(ValueError,'components missing'):
                connected_step_groups(groups[1:],root)

    def test_unchanged_exchange_identity_remains_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);groups=self.contact_fixture(root)
            (root/'p1_ground_shield.step').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'exchange identity differs'):
                connected_step_groups(groups,root)


class CompletedStepPublicationTests(unittest.TestCase):
    def make_source(self, directory):
        root=Path(directory)/'source';root.mkdir();(root/'cad').mkdir();(root/'inputs').mkdir()
        physical={k:root/'inputs'/k for k in ('geometry','authority','materialization')}
        for path in physical.values():path.write_text('{}')
        physical['authority'].write_text(json.dumps(dict(analyzer_electrode_voltages_v=[0]*20)))
        groups=[]
        names=['oa_first_grid_electrode','oa_grounded_enclosure_exit_grid']+[f'electrode_{i}' for i in range(38)]
        for name in names+[f'c0_{i}' for i in range(6)]+['mrtof_electrode_assembly']:
            path=root/'cad'/(name+'.step');path.write_bytes(name.encode())
            groups.append(dict(name=name,assembly_exchange=str(path),voltage_v=0,parts=[dict(voltage_v=0)],
                optional_boundary_reference=name.startswith('c0_'),overview_only=name=='mrtof_electrode_assembly',
                native_cold_reopen=True,interferences=[],exchange_reopen=dict(leaves=[dict(sheet_count=int(name.startswith('oa_')),
                trimmed_edge_validation=dict(status='PASS'))])))
        validation=dict(status='PASS',exchange_format='step',mounting_holes_omitted=True,
            electrical_groups=groups,qualification='engineering_geometry_only',analyzer_electrode_voltages_v=[0]*20)
        (root/'cad_validation.json').write_text(json.dumps(validation))
        (root/'cad_api_state.json').write_text(json.dumps(dict(preferences_restored=True,restored_preferences_equal_original=True,
            owned_process_exited=True,remaining_documents_retained=[])))
        (root/'summary.json').write_text(json.dumps(dict(status='failed',role='mrtof_cad_export_summary',
            reason='Verified success run manifest was published, but capacity ledger finalization failed; test')))
        (root/'run_config.json').write_text('{}')
        for name in ('README.md','electrode_groups.csv','step_geometry_validation.csv','component_step_mapping.csv'):(root/name).write_text(name)
        with zipfile.ZipFile(root/'mrtof_step_delivery.zip','w') as archive:
            for group in groups:
                folder='assembly' if group['overview_only'] else ('reference' if group['optional_boundary_reference'] else 'electrodes')
                archive.write(group['assembly_exchange'],folder+'/'+group['name']+'.step')
            for name in ('README.md','electrode_groups.csv','step_geometry_validation.csv','component_step_mapping.csv'):archive.write(root/name,name)
        self.seal(root,physical)
        return root,physical

    def seal(self,root,physical):
        def record(path):
            payload=path.read_bytes();return dict(path=str(path),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
        manifest=dict(status='success',project='parallel_mirror_dual_stripe_mr_tof',run_id='completed-step',
            run_config=record(root/'run_config.json'),inputs={k:record(v) for k,v in physical.items()},
            outputs=[record(p) for p in root.rglob('*') if p.is_file() and p.name!='run_manifest.json'])
        (root/'run_manifest.json').write_text(json.dumps(manifest))

    def test_completed_step_republication_preserves_bytes_and_source_failure(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import publish_validated_step_delivery
        with tempfile.TemporaryDirectory() as directory:
            root,physical=self.make_source(directory);old_summary=(root/'summary.json').read_bytes()
            with patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad.export_parts',side_effect=AssertionError('no CAD')):
                result=publish_validated_step_delivery(root,Path(directory)/'published',physical)
            self.assertFalse(result['commercial_cad_performed']);self.assertTrue(result['source_publication_failure'])
            self.assertEqual((root/'summary.json').read_bytes(),old_summary)
            self.assertEqual((Path(directory)/'published/mrtof_step_delivery.zip').read_bytes(),(root/'mrtof_step_delivery.zip').read_bytes())

    def test_step_publication_rejects_tamper_wrong_inputs_and_true_cad_failure(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad import publish_validated_step_delivery
        for mutation in ('tamper','physical','failure','missing','voltage'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as directory:
                root,physical=self.make_source(directory)
                if mutation=='tamper':(root/'mrtof_step_delivery.zip').write_bytes(b'broken')
                if mutation=='physical':
                    wrong=Path(directory)/'wrong';wrong.write_text('wrong');physical=dict(physical,geometry=wrong)
                if mutation=='failure':(root/'summary.json').write_text(json.dumps(dict(status='failed',reason='CAD failed')))
                if mutation in ('missing','voltage'):
                    path=root/'cad_validation.json';data=json.loads(path.read_text())
                    if mutation=='missing':data['electrical_groups'].pop()
                    else:data['electrical_groups'][2]['parts'][0]['voltage_v']=1
                    path.write_text(json.dumps(data));self.seal(root,physical)
                with self.assertRaises(ValueError):publish_validated_step_delivery(root,Path(directory)/'published',physical,check_only=True)


if __name__=='__main__':unittest.main()
