"""Test-only installed static-field comparison witness; no solver execution."""
import copy
import json
import pathlib
import subprocess
import sys
import sysconfig


def run_static_field_probe(fixture, root, blocked_source_roots, case, timer):
    """Exercise installed comparison with explicit inert inputs in one arm."""
    with timer('static_field_comparison', case):
        import pandas as pd
        from msplatform.analysis import field_comparison
        from msplatform.contracts.rigid_transform import RigidTransform

        module = pathlib.Path(field_comparison.__file__).resolve()
        assert module == pathlib.Path(sysconfig.get_path('purelib')).resolve() / 'msplatform/analysis/field_comparison.py'
        reference = pd.DataFrame([
            dict(point_id='p1', x_mm=1., y_mm=2., z_mm=3., Ex_V_per_m=0., Ey_V_per_m=2., Ez_V_per_m=0., potential_V=0., status='valid'),
            dict(point_id='p2', x_mm=0., y_mm=0., z_mm=0., Ex_V_per_m=0., Ey_V_per_m=0., Ez_V_per_m=0., potential_V=0., status='valid'),
        ])
        candidate = pd.DataFrame([
            dict(point_id='p1', x_mm=1., y_mm=3., z_mm=3., Ex_V_per_m=2., Ey_V_per_m=1., Ez_V_per_m=0., potential_V=3., status='valid'),
            dict(point_id='p3', x_mm=0., y_mm=0., z_mm=0., Ex_V_per_m=0., Ey_V_per_m=0., Ez_V_per_m=0., potential_V=0., status='excluded'),
        ])
        metadata = dict(source={'id':'explicit-inert-source'}, bvp={'electrodes':{'ground_V':0.}}, frame_id='world',
            units={'length':'mm','electric_field':'V/m','potential':'V'}, potential_reference={'electrode':'ground'})
        other = copy.deepcopy(metadata)
        other['source'] = {'id':'explicit-inert-candidate'}
        other['frame_id'] = 'local'
        transform = RigidTransform('local','world',((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)),(4.,1.,0.))
        original_reference = reference.copy(deep=True)
        original_candidate = candidate.copy(deep=True)
        original_metadata = copy.deepcopy((metadata, other))
        def compare(left=metadata, right=other):
            return field_comparison.compare_static_field_samples(reference, candidate,
                reference_metadata=left, candidate_metadata=right,
                reference_transform=RigidTransform.identity('world'), candidate_transform=transform,
                coordinate_tolerance_mm=0.)
        report = compare()
        assert report['status']=='DESCRIPTIVE_ONLY' and report['paired_valid_count']==1
        assert report['coverage_counts']['total_union']==3
        assert report['coverage_counts']['reference']['missing']==1
        assert report['coverage_counts']['candidate']['missing']==1
        assert report['coverage_counts']['candidate']['excluded']==1
        assert report['metrics']['field_components']['Ex']['difference_rms_V_per_m']==1.
        assert report['metrics']['field_components']['Ex']['relative_to_reference_rms_pct'] is None
        assert report['metrics']['potential']['rms_difference_V']==3.
        assert report['metrics']['potential']['relative_to_reference_rms_pct'] is None
        assert report['metrics']['field_components']['Ey']['difference_rms_V_per_m']==0.
        for label, key, value, reason in (
            ('bvp', 'bvp', {'electrodes':{'ground_V':1.}}, 'BVP differs'),
            ('gauge', 'potential_reference', {'electrode':'other'}, 'potential reference differs'),
            ('units', 'units', {'length':'mm','electric_field':'V/mm','potential':'V'}, 'units differ'),
        ):
            invalid = copy.deepcopy(other)
            invalid[key] = value
            try:
                compare(right=invalid)
            except ValueError as error:
                assert reason in str(error), (label, str(error))
            else:
                raise AssertionError(label + ' mismatch accepted')
        pd.testing.assert_frame_equal(reference, original_reference)
        pd.testing.assert_frame_equal(candidate, original_candidate)
        assert (metadata,other)==original_metadata
        original = module.read_bytes()
        held = module.with_name(module.name+'.static-field-held')
        assert not held.exists()
        module.rename(held)
        try:
            code = r"""import importlib.abc,json,os,pathlib,sys
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[1])]
def deny(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
  p=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(p.is_relative_to(b) for b in blocked): raise AssertionError('author access: '+str(p))
sys.addaudithook(deny)
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}: raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,Deny())
import msplatform.analysis.field_comparison
"""
            missing = subprocess.run([sys.executable,'-I','-B','-X','utf8','-c',code,
                json.dumps([str(path) for path in blocked_source_roots])],cwd=root,
                capture_output=True,text=True,encoding='utf-8',timeout=30,check=False)
            assert missing.returncode!=0 and "No module named 'msplatform.analysis.field_comparison'" in missing.stderr,missing.stderr
        finally:
            held.rename(module)
        assert module.read_bytes()==original
        print('INSTALLED_STATIC_FIELD_SOFTWARE=PASS')
