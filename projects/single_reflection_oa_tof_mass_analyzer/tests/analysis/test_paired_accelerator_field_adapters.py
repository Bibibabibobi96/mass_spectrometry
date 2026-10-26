"""Adapter wiring and real Lua execution with inert PA API; no native solve."""
from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
LUA = Path('C:/Program Files/SIMION-2020/lua.exe')
EXPORT = PROJECT / 'simion/export_paired_accelerator_field.lua'
COMSOL = PROJECT / 'comsol/build_and_export_paired_accelerator_field.m'


class PairedFieldAdapterTests(unittest.TestCase):
    def lua_case(self, root, *, points=None, overrides='', outside=False, native_field='-2,6,-4', suffix='.pa'):
        points_path = root/'points.csv'
        points_path.write_text(points or 'point_id,x_mm,y_mm,z_mm\n8,10.5,22,31\n7,11,24,31.5\n', encoding='utf-8')
        output, facts = root/'samples.csv', root/'facts.txt'
        script=root/'inert.lua'
        # This is an inert API implementation, not a fabricated field solution.
        # Known API values test only transport, units/sign, coverage and cleanup.
        script.write_text(f'''
local pa={{potential_type='electric',refined=false,refinable=true,
 nx=20,ny=20,nz=20,dx_mm=.5,dy_mm=2,dz_mm=.25}}
local closed=false
function pa:close() closed=true end
function pa:inside_vc(x,y,z) return {str(not outside).lower()} end
local calls=0
function pa:field_vc(x,y,z)
 calls=calls+1
 if calls==1 then assert(x==1 and y==1 and z==4,'axis coordinate conversion differs') end
 return {native_field}
end
{overrides}
simion={{pas={{open=function(self,path) assert(path=='ordinary{suffix}'); return pa end}}}}
local plan={{schema_version=1,role='oatof_paired_accelerator_static_field_plan',coordinate_frame='oatof_global',
 native_geometry_compilation={{grid={{dimensions={{nx=20,ny=20,nz=20}},
 cell_mm_xyz={{x=.5,y=2,z=.25}},instance_origin_mm={{x=10,y=20,z=30}}}}}},
 sample_points={{path='{points_path.as_posix()}',count=2}}}}
local export=dofile('{EXPORT.as_posix()}')
local ok,result=pcall(export,'ordinary{suffix}',plan,'{output.as_posix()}','{facts.as_posix()}')
if '{suffix}'=='.pa' then assert(closed,'PA not closed after export/failure') end
if not ok then error(result) end
assert(result==2)
''',encoding='utf-8',newline='\n')
        result=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding="utf-8",timeout=30,check=False)
        return result,output,facts

    @unittest.skipUnless(LUA.is_file(),'standalone Lua unavailable')
    def test_anisotropic_units_sign_original_ids_and_native_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            result,output,facts=self.lua_case(Path(directory))
            self.assertEqual(result.returncode,0,result.stderr)
            with output.open() as stream:
                rows=list(csv.DictReader(stream))
            self.assertEqual([int(row['point_id']) for row in rows],[8,7])
            self.assertEqual([float(rows[0][key]) for key in ('x_mm','y_mm','z_mm')],[10.5,22.,31.])
            self.assertEqual([float(rows[0][key]) for key in ('Ex_V_per_m','Ey_V_per_m','Ez_V_per_m')],[-4000.,3000.,-16000.])
            text=facts.read_text()
            self.assertIn('native_field_unit=V/gu',text)
            self.assertIn('field_sign=negative_potential_gradient',text)
            self.assertIn('8,10.5,22,31,-2,6,-4',text)

    @unittest.skipUnless(LUA.is_file(),'standalone Lua unavailable')
    def test_invalid_native_inputs_fail_before_export_and_close_pa(self):
        cases=[dict(outside=True),dict(overrides='pa.dx_mm=1'),
               dict(native_field='0/0,1,2'),dict(overrides="pa.potential_type='magnetic'"),
               dict(points='point_id,x_mm,y_mm,z_mm\n8,10.5,22,31\n8,11,24,31.5\n'),
               dict(points='point_id,x_mm,y_mm,z_mm\n8,10.5,22,31\n'),dict(suffix='.pa0')]
        for case in cases:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                result,output,_=self.lua_case(Path(directory),**case)
                self.assertNotEqual(result.returncode,0)
                self.assertFalse(output.exists())

    def test_comsol_uses_provider_solids_and_real_mechanical_port(self):
        text=COMSOL.read_text(encoding='utf-8')
        for required in ('scope.components.(id).ports.side_entry',
                         "strcmp(plan.coordinate_frame,'oatof_global')", 'numel(selected)==1',
                         'oatof_build_accelerator_geometry(geom,numel(g.ring_z_mm),opening,g)',
                         'build_accelerator_grids(geom,sheets)',
                         "roles={'grid1','intermediate2','grid2'}",'g.shield_inner_width_mm'):
            self.assertIn(required,text)
        for forbidden in ('oatof_build_model_core(', 'oatof_build_grid_geometry(',
                          "'ChargedParticleTracing'",'V_repeller','ring_count+1',
                          'instances(selected).transform', 'pose.translation_mm', 'pose.rotation'):
            self.assertNotIn(forbidden,text)

    def test_comsol_domain_boundary_mesh_and_native_export_contract(self):
        text=COMSOL.read_text(encoding='utf-8')
        for required in ("set('keepsubtract','on')","set('intbnd','on')",
                         "es.selection.named('sel_vac')", "tet.selection.named('sel_vac')",
                         'outer=setdiff(allVac,electrodes)',"'ZeroCharge',2",
                         'domain.comsol_mesh.global_automatic_level',
                         'domain.comsol_mesh.electrode_boundary_maximum_element_size_mm',
                         'domain.comsol_mesh.electrode_boundary_growth_rate',
                         'plan.static_on_electrode_voltages_v.(key)',
                         "'coord',points{:,{'x_mm','y_mm','z_mm'}}.'",
                         "'edim','domain','ext',0,'unit',{'V/m','V/m','V/m'}",
                         'all(strcmp(units,\'V/m\'))','isfinite([ex(:);ey(:);ez(:)])'):
            self.assertIn(required,text)
        solve=text.split('\nfunction modelPath=solve_and_save(',1)[1].split('\nfunction facts=export_field_samples',1)[0]
        prepared_save=solve.index('mphsave(model,modelPath);')
        prepared_fact=solve.index("'status','prepared_saved'")
        prepared_publication=solve.index('write_native_facts(')
        compute=solve.index('sol.runAll;')
        solved_save=solve.index('mphsave(model,modelPath);',prepared_save+1)
        solved_fact=solve.index("facts.status='solved_saved'")
        solved_publication=solve.index('write_native_facts(',prepared_publication+1)
        order=[prepared_save,prepared_fact,prepared_publication,compute,solved_save,solved_fact,solved_publication]
        self.assertEqual(order,sorted(order))
        main=text.split('\nfunction modelPath=solve_and_save(',1)[0]
        self.assertLess(main.rindex('modelPath=solve_and_save('),main.rindex('facts=export_field_samples('))
        self.assertNotIn("'Ground'",text)
        self.assertNotIn('mphstart',text)
        self.assertIn('sol.attach(\'std1\')',text)
        self.assertIn('%.0f,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g',text)
        self.assertNotIn('writetable(',text)

    def test_local_mesh_uses_actual_boundary_union_and_checks_native_configuration(self):
        text = COMSOL.read_text(encoding='utf-8')
        for expected in ("plan.schema_version==2", "s.geom('geom1',2); s.set(electrodes)",
                         "'geom1',2,'sel_electrode_mesh'", "localSize.set('hgradactive','on')",
                         "localSize.selection.entities(2)", "mesh.feature('ftet1').selection.entities(3)",
                         "model.param.evaluate(char(localSize.getString('hmax')),'mm')",
                         "'global_minimum_element_size_expression',char(globalSize.getString('hmin'))",
                         "'geometry_length_unit',char(comp.geom('geom1').lengthUnit())",
                         "globalSize.getDouble('hauto')", "localSize.getDouble('hgrad')",
                         'sort(selected(:)),sort(electrodes(:))',
                         '["size";"paired_electrode_size";"ftet1"]', "'mesh_contract',meshFacts"):
            self.assertIn(expected, text)
        self.assertNotIn("'geom1',3,'sel_vac',domain.comsol_mesh", text)
        self.assertNotIn("model.param.evaluate(char(globalSize.getString('hmin'))", text)
        self.assertLess(text.index("localSize=add_comsol_size_feature"), text.index("mesh.create('ftet1'"))
        self.assertLess(text.index('read_mesh_contract(model,plan);'), text.index('mesh.run;'))
        self.assertLess(text.index('meshFacts=read_mesh_contract(model,plan);'), text.index('mphinterp(model,'))
        self.assertNotIn('maximum_element_size_mm', text.replace('electrode_boundary_maximum_element_size_mm', ''))

    def test_explicit_saved_solution_branch_only_loads_checks_and_exports(self):
        text=COMSOL.read_text(encoding='utf-8')
        branch=text.split('if ~isempty(SavedModelPath)',1)[1].split('\nend',1)[0]
        for expected in ('mphload(SavedModelPath,tag)',"model.sol('sol1').isEmpty()",
                         'export_field_samples(model,plan,planPath,points,outputDir,SavedModelPath)',
                         'return'):
            self.assertIn(expected,branch)
        for forbidden in ('mphsave(','.runAll','.mesh(',"ModelUtil.create("):
            self.assertNotIn(forbidden,branch)
        solved=branch.split("if strcmp(SavedModelStage,'solved_saved')",1)[1].split('\n    else',1)[0]
        self.assertIn("assert(~model.sol('sol1').isEmpty()",solved)
        self.assertIn('export_field_samples(model,plan,planPath,points,outputDir,SavedModelPath)',solved)
        self.assertNotIn('solve_and_save(',solved)
        prepared=branch.split('\n    else',1)[1].split('\n    end',1)[0]
        self.assertIn("assert(model.sol('sol1').isEmpty()",prepared)
        self.assertLess(prepared.index('modelPath=solve_and_save('),prepared.index('facts=export_field_samples('))
        self.assertEqual(text.count('mphinterp(model,'),1)


if __name__=='__main__':
    unittest.main()
