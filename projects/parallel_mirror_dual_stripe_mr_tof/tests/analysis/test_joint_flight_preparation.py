"""Preparation must bind replacement fields and preserve OA builder behavior."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import json

from common.contracts.write_run_manifest import file_record
from common.contracts.file_identity import file_sha256

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import (
    _lua, render_measured_operating_point, freeze_field_reference,
    audit_field_coverage, prepare_interface_field_audit, summarize_interface_field_audit,
    prepare_event_field_audit, summarize_event_field_audit,
)

PROJECT = Path(__file__).resolve().parents[2]


class JointPreparationTests(unittest.TestCase):
    def test_provider_voltage_projection_freezes_injected_public_waveforms(self):
        from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import REPO, project_provider_voltages
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file():
            self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory)
            shutil.copyfile(PROJECT / 'config/ion_processor_dependency.json', inputs / 'accelerator_dependency.json')
            source = load_config()
            request = dict(policies=dict(energy_adjustment='preserve_measured_workpoint'),
                target=dict(axial_energy_per_charge_v=4000),
                current_measured_baseline=dict(directional_energy=dict(z=dict(mean=4000))))
            result = project_provider_voltages(source, request, inputs, Path(lua))
            self.assertEqual(result['values_v15'][4:8], [3100,4900,3100,4900])
            self.assertEqual(Path(result['source_voltage_waveforms']['path']).read_bytes(),
                (REPO / 'common/simion/voltage_waveforms.lua').read_bytes())
            self.assertEqual(json.loads((inputs / 'provider_voltage_projection.json').read_text()), result)

    def test_five_role_builder_checks_saved_patch_occupancy_and_boundary_priority(self):
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file():
            self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = dict(schema_version=1,role='mrtof_analyzer_collision_overlay',patch_plan_path='sealed_plan.json',
                pa_path='patch.pa',box_mm=[0,2,2,2,4,4],pitch_mm=[1,1,1],dimensions=[3,3,3],
                priority_probes=[dict(label=label,point_mm=p,expected_instance=instance,expected_electrode=metal)
                    for label,p,instance,metal in [('metal',[.5,2.5,2.5],5,True),('vacuum',[1.5,2.5,2.5],5,False),
                        ('boundary_inside',[1.9,3,3],5,False),('boundary_outside',[2.1,3,3],2,False)]])
            roles = ['global_fallback','native_corridor','ion_processor_collision','detector','analyzer_collision_patch']
            request = dict(schema_version=1,role='mrtof_measured_source_workbench_build',seed='5_instance_seed.iob',
                paths=['global.pa','corridor.pa','ip.pa','detector.pa','patch.pa'],
                origins=[[0,0,0],[0,0,0],[0,8,0],[0,0,8],[0,2,2]],output=str(root/'out.iob'),
                program=str(root/'program.lua'),fly2=str(root/'source.fly2'),operating=str(root/'operating.lua'),
                priority=str(root/'priority.lua'))
            priority = dict(schema_version=1,role='mrtof_native_corridor_iob_priority_contract',
                accelerator_provider='dual_pressure_rectilinear_ion_processor',collision_overlay=overlay,
                instances=[dict(role=role,priority_number=i) for i,role in enumerate(roles,1)])
            operating = dict(accelerator_provider='dual_pressure_rectilinear_ion_processor',field_assembly_verified=True,
                measured_source_matches_workpoint=True,static_field=dict(assembly_scope='full_c0_ion_processor_replacement',
                                                                        collision_overlay=overlay))
            for name,value in [('request.lua',request),('priority.lua',priority),('operating.lua',operating)]:
                (root/name).write_text('return '+_lua(value))
            for name in ('program.lua','program.mirror_cycle_counter.lua', 'program.voltage_waveforms.lua','program.source_runtime.lua','source.fly2'):
                (root/name).write_text('-- fixture')
            (root/'fixture.lua').write_text(r'''
local root,builder,fault=unpack(arg)
local instances={}
for i=1,5 do
  local pa={nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='3dplanar[x]'}
  if i==3 then pa.ny=3 elseif i==4 then pa.nz=3 elseif i==5 then pa.nx=3;pa.ny=3;pa.nz=3 end
  if i==5 then pa.refinable=false end
  pa.load=function(self,path) self.path=path end
  instances[i]={pa=pa,_debug_update_size=function() end}
end
local loads,saves,probes=0,0,0
simion={wb={instances=instances}}
function simion.wb:load(path)
  loads=loads+1;self.filename=path
  if loads==2 and fault=='saved_grid' then instances[5].pa.nx=4 end
  if loads==2 and fault=='saved_refinable' then instances[5].pa.refinable=true end
end
function simion.wb:save() saves=saves+1 end
function simion.wb:find_at(x,y,z)
  probes=probes+1
  if probes<=3 then return 0,probes+1 end
  if fault=='priority' then return 0,2 end
  if fault=='metal' then return 0,5 end
  if fault=='boundary' and x>2 then return 0,5 end
  return x==.5 and 1 or 0,x>2 and 2 or 5
end
arg={'--measured-source',root..'/request.lua'}
dofile(builder)
assert(loads==2 and saves==1 and probes==7,'save/reload plus metal/vacuum/boundary probes required')
assert(instances[3].pa.path=='ip.pa' and instances[4].pa.path=='detector.pa' and instances[5].pa.path=='patch.pa')
print('FIVE_ROLE_BUILDER_MOCK=PASS')
''')
            for fault in ('none','saved_grid','saved_refinable','priority','metal','boundary'):
                with self.subTest(fault=fault):
                    actual = subprocess.run([lua,str(root/'fixture.lua'),str(root),str(PROJECT/'simion/build_native_corridor_iob.lua'),fault],
                                            cwd=root,capture_output=True,text=True,timeout=30)
                    if fault=='none':
                        self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr)
                        self.assertIn('IOB_BUILD=PASS instances=5',actual.stdout)
                    else:
                        self.assertNotEqual(actual.returncode,0)

    def test_same_second_default_run_ids_are_distinct_across_providers(self):
        pwsh = shutil.which('pwsh') or 'C:/Program Files/PowerShell/7/pwsh.exe'
        script = PROJECT.parents[1] / 'integrations/workflows/accelerator_interface/execute.ps1'
        command = (
            "$tokens=$null;$errors=$null;"
            "$a=[Management.Automation.Language.Parser]::ParseFile('" + str(script) + "',[ref]$tokens,[ref]$errors);"
            "$f=$a.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'New-AcceleratorInterfaceRunId'},$true);"
            "Invoke-Expression $f.Extent.Text;"
            "New-AcceleratorInterfaceRunId -Provider orthogonal_accelerator;"
            "New-AcceleratorInterfaceRunId -Provider dual_pressure_rectilinear_ion_processor;"
            "New-AcceleratorInterfaceRunId -Provider dual_pressure_rectilinear_ion_processor"
        )
        result = subprocess.run([pwsh, '-NoProfile', '-Command', command], cwd=PROJECT,
                                capture_output=True,
                                text=True, timeout=30, check=True)
        identities = result.stdout.splitlines()
        self.assertEqual(len(identities), 3)
        self.assertEqual(len(set(identities)), 3)
        self.assertRegex(identities[0], r'__analysis__python__accelerator-interface-oa-[0-9a-f]{8}$')
        self.assertRegex(identities[1], r'__analysis__python__accelerator-interface-ip-[0-9a-f]{8}$')

    def test_generated_sidecar_removes_inherited_oa_launch_plane(self):
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file() and shutil.which(lua) is None:
            self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / 'reference.lua'
            reference.write_text('return {accelerator_exit_plane_project_z_mm=0,accelerator_voltages_v={1,2,3},mirror_voltages_v={0,1,2,3,4}}', encoding='utf-8')
            (root / 'generated.lua').write_text(render_measured_operating_point(
                reference, root, dict(assembly_scope='new', analyzer_voltages_v=[0.]*20),
                numerics=dict(trajectory_quality=7,maximum_step_us=.003,full_path_timeout_us=123)), encoding='utf-8')
            check = "local t=dofile(arg[1]);assert(t.accelerator_exit_plane_project_z_mm==nil and t.accelerator_voltages_v==nil and t.mirror_voltages_v[5]==4 and not t.field_assembly_verified and not t.measured_source_matches_workpoint);assert(t.trajectory_quality==7 and t.maximum_step_us==.003 and t.full_path_timeout_us==123)"
            (root / 'check.lua').write_text(check, encoding='utf-8')
            result = subprocess.run([lua, str(root / 'check.lua'), str(root / 'generated.lua')], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reference_json_binds_real_compiler_and_derives_timeout_without_lua_numerics(self):
        import copy
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import _full_path_timeout_us
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import OPPOSITE_MIRROR_TURN
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference"
            (reference / "simion").mkdir(parents=True)
            (reference / "results").mkdir()
            contract = dict(simion=dict(full_path_timeout_axial_path_multiplier=2,
                default_trajectory_profile_id="reference", trajectory_profiles=dict(reference=dict(
                    trajectory_quality=3,maximum_step_us=.004,purpose="synthetic compiler profile"))),
                nominal=dict(target_drift_period_ratio=2.5,fast_path_symmetry=OPPOSITE_MIRROR_TURN),
                particle_source=dict(species=dict(mass_th=524,charge_e=1),
                    mirror_internal_diagnostic=dict(axial_kinetic_energy_ev=1000)),
                mirror=dict(inner_face_z_mm=10,grounded_inner_shield=dict(thickness_z_mm=2),
                    electrode_thicknesses_mm=[2]*5,inter_electrode_gaps_mm=[1]*4))
            compiler = root/"compiler_contract.json"
            compiler.write_text(json.dumps(contract))
            record = file_record(compiler)
            original = dict(inputs=dict(contract_sha256=record["sha256"],trajectory_contract_sha256="B"*64),
                trajectory_profile=dict(trajectory_quality=3,maximum_step_us=.004),target_drift_period_ratio=2.5,
                field_binding=dict(refinement_windows=[]))
            (reference/"simion/mrtof_three_component_candidate.operating_point.lua").write_text(
                "return {static_field={analyzer_voltages_v={"+",".join(["0"]*20)+"}}}")
            authority = reference/"authority.json"
            authority.write_text("{}")
            binding = dict(parent=dict(manifest=str(reference/"run_manifest.json"),
                **{name+"_path":str(authority) for name in ("geometry_authority","voltage_authority","numerical_plan")}),
                refinement_windows=[])
            (reference/"simion/static_field_binding.json").write_text(json.dumps(binding))
            for case in ("valid", "wrong_contract", "wrong_profile", "wrong_phase", "invalid_timeout"):
                with self.subTest(case=case):
                    materialization = copy.deepcopy(original)
                    current = copy.deepcopy(contract)
                    if case == "wrong_contract":
                        materialization["inputs"]["contract_sha256"] = "C"*64
                    elif case == "wrong_profile":
                        materialization["trajectory_profile"]["maximum_step_us"] = .002
                    elif case == "wrong_phase":
                        materialization["target_drift_period_ratio"] = 3.5
                    elif case == "invalid_timeout":
                        current["simion"]["full_path_timeout_axial_path_multiplier"] = 1
                    compiler.write_text(json.dumps(current))
                    current_record = file_record(compiler)
                    if case != "wrong_contract":
                        materialization["inputs"]["contract_sha256"] = current_record["sha256"]
                    (reference/"results/two_prism_trial_materialization.json").write_text(json.dumps(materialization))
                    inputs = root/case
                    inputs.mkdir()
                    with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation.verified_reference",
                               side_effect=lambda owner,relative:owner/relative):
                        if case != "valid":
                            with self.assertRaises(ValueError):
                                freeze_field_reference(reference,inputs,compiler_contract=current_record)
                            continue
                        result = freeze_field_reference(reference,inputs,compiler_contract=current_record)
                    self.assertEqual(result["numerics"],dict(trajectory_quality=3,maximum_step_us=.004,
                        full_path_timeout_us=_full_path_timeout_us(contract,contract["particle_source"],2.5)))
                    self.assertEqual(Path(result["reference_materialization"]["path"]).read_bytes(),
                                     (reference/"results/two_prism_trial_materialization.json").read_bytes())

    def test_measured_builder_uses_four_real_roles_and_rejects_unverified_inputs(self):
        lua = shutil.which('lua') or str(Path('C:/Program Files/SIMION-2020/lua.exe'))
        if not Path(lua).is_file() and shutil.which(lua) is None:
            self.skipTest('plain Lua unavailable; no solver fallback')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, content):
                (root / name).write_text(content, encoding='utf-8')
            for name in ('program.lua', 'program.mirror_cycle_counter.lua', 'program.voltage_waveforms.lua', 'program.source_runtime.lua', 'source.fly2'):
                write(name, '-- test companion\n')
            request = dict(schema_version=1, role='mrtof_measured_source_workbench_build', seed='4_instance_seed.iob',
                           paths=['global.pa', 'collision.pa', 'ip_collision.pa', 'detector.pa'], origins=[[0, 0, 0]] * 4,
                           output=str(root / 'result.iob'), program=str(root / 'program.lua'),
                           fly2=str(root / 'source.fly2'), operating=str(root / 'operating.lua'), priority=str(root / 'priority.lua'))
            write('request.lua', 'return ' + _lua(request))
            provider = 'dual_pressure_rectilinear_ion_processor'
            priority = dict(role='mrtof_native_corridor_iob_priority_contract', schema_version=1, accelerator_provider=provider,
                            instances=[dict(role=role, priority_number=index) for index, role in enumerate(
                                ('global_fallback', 'native_corridor', 'ion_processor_collision', 'detector'), 1)])
            write('priority.lua', 'return ' + _lua(priority))
            operating = dict(accelerator_provider=provider, field_assembly_verified=True, measured_source_matches_workpoint=True,
                             static_field=dict(assembly_scope='full_c0_ion_processor_replacement'))
            fixture = r'''
local root,builder=arg[1],arg[2]
local instances={}
for i=1,4 do
  instances[i]={x=0,y=0,z=0,scale=1,pa={nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1}}
  instances[i].pa.load=function(self,path) self.path=path end
  instances[i]._debug_update_size=function() end
end
simion={wb={instances=instances,load=function(self,path) self.filename=path end,
save=function() end,find_at=function() return 0, _G.probe==nil and 2 or 3 end}}
-- The first overlap must choose corridor, the second detector.
local n=0
function simion.wb:find_at() n=n+1;return 0,n+1 end
arg={'--measured-source',root..'/request.lua'}
dofile(builder)
assert(instances[1].pa.path=='global.pa' and instances[2].pa.path=='collision.pa'
  and instances[3].pa.path=='ip_collision.pa' and instances[4].pa.path=='detector.pa')
assert(n==3,'actual overlap probes required')
print('MEASURED_BUILDER_MOCK=PASS')
'''
            write('fixture.lua', fixture)
            for verified in (True, False):
                operating['field_assembly_verified'] = verified
                write('operating.lua', 'return ' + _lua(operating))
                result = subprocess.run([lua, str(root / 'fixture.lua'), str(root), str(PROJECT / 'simion/build_native_corridor_iob.lua')],
                                        cwd=root, capture_output=True, text=True, timeout=30, check=False)
                if verified:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('MEASURED_BUILDER_MOCK=PASS', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('verified new fields', result.stderr)


    def test_default_oa_builder_preserves_four_roles_and_voltage_guards(self):
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file() and shutil.which(lua) is None:
            self.skipTest('plain Lua unavailable; no solver fallback')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('program.lua', 'program.mirror_cycle_counter.lua', 'program.voltage_waveforms.lua', 'source.fly2'):
                (root / name).write_text('-- test companion\n', encoding='utf-8')
            point = dict(mirror_voltages_v=[0, -10, 20, 30, 50], stripe_biases_v=[-4, 6],
                         prism_voltages_v=[100, -100], accelerator_voltages_v=[40, 30, 0],
                         accelerator_ring_voltages_v=[25, 20, 15, 10, 5], nonaccelerator_scale=1)
            fixture = r"""
local root,builder,mapper,priority_path,bad_priority=unpack(arg)
local instances={}
for i=1,4 do
  instances[i]={x=0,y=0,z=0,scale=1,pa={nx=11,ny=11,nz=11,
    dx_mm=1,dy_mm=1,dz_mm=1,symmetry='3dplanar[x]'}}
  instances[i].pa.load=function(self,path) self.path=path end
  instances[i]._debug_update_size=function() end
end
local saves,probes,loads=0,0,0
simion={wb={instances=instances,load=function(self,path) self.filename=path;loads=loads+1 end,
  save=function() saves=saves+1 end}}
function simion.wb:find_at() probes=probes+1;return 0,probes+1 end
local original_dofile=dofile
dofile=function(path)
  local result=original_dofile(path)
  if path==priority_path then
    if bad_priority=='priority' then result.instances[3].role='detector' end
    if bad_priority=='groups' or bad_priority=='static' then result.corridor_voltage_groups=nil end
    if bad_priority=='unequal' then result.corridor_voltage_groups[1]={2,3} end
  end
  return result
end
arg={'4_instance_seed.iob','global.pa0','corridor.pa0','accelerator.pa0','detector.pa',
  root..'/result.iob',root..'/program.lua',root..'/source.fly2',root..'/operating.lua',mapper,priority_path,
  '0','0','0','0','0','0','0','0','0','0','0','0'}
local ok,err=pcall(original_dofile,builder)
if not ok then
  assert(loads==0 and saves==0,'invalid voltages must fail before Workbench load/save')
  error(err)
end
assert(instances[1].pa.path=='global.pa0' and instances[2].pa.path=='corridor.pa0'
  and instances[3].pa.path=='accelerator.pa0' and instances[4].pa.path=='detector.pa')
assert(saves==1 and loads==2 and probes==3,'four-role OA save/reload and all overlaps required')
print('OA_BUILDER_MOCK=PASS')
"""
            (root / 'priority.lua').write_text("return {schema_version=1,role='mrtof_native_corridor_iob_priority_contract',\n  instances={{role='global_fallback',priority_number=1},{role='native_corridor',priority_number=2},\n    {role='accelerator',priority_number=3},{role='detector',priority_number=4}},\n  corridor_voltage_groups={{2,7},{3,8},{4,9},{5,10},{11,12},{13,14},{16},{17}}}", encoding='utf-8')
            (root / 'fixture.lua').write_text(fixture, encoding='utf-8')
            for invalid in ('none', 'static', 'rings', 'priority', 'groups', 'unequal'):
                scenario = dict(point)
                if invalid == 'static':
                    scenario['static_field'] = {}
                if invalid == 'rings':
                    scenario['accelerator_ring_voltages_v'] = []
                (root / 'operating.lua').write_text('return ' + _lua(scenario), encoding='utf-8')
                result = subprocess.run(
                    [lua, str(root / 'fixture.lua'), str(root), str(PROJECT / 'simion/build_native_corridor_iob.lua'),
                     str(PROJECT / 'simion/candidate_voltage_map.lua'), str(root / 'priority.lua'),
                     invalid],
                    cwd=root, capture_output=True, text=True, timeout=30, check=False)
                if invalid in ('none', 'static'):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('OA_BUILDER_MOCK=PASS', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    expected_error = {'rings': 'ring voltages must be nonempty',
                                      'priority': 'must be accelerator',
                                      'groups': 'exactly eight voltage groups',
                                      'unequal': 'physical voltages differ'}[invalid]
                    self.assertIn(expected_error, result.stderr)


    def test_final_sidecar_preserves_verified_source_field_voltages_and_unqualified_energy(self):
        from integrations.workflows.accelerator_interface.prepare import bind_joint_workbench
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            design, fields, actual = [root / name for name in ("design", "fields", "actual")]
            for folder in (design / "results/joint_flight", design / "inputs", fields / "results", actual / "inputs"):
                folder.mkdir(parents=True)
            (design / "run_manifest.json").write_text("{}")
            def write(path, value):
                path.write_text(json.dumps(value), encoding="utf-8")
            configs = {name: {"identity": name} for name in
                       ("baseline", "native_operating_point", "numerics", "source", "coordinate_transform")}
            configs["source"]["species"] = dict(mass_amu=524, charge_state=1)
            paths = {}
            for name, value in configs.items():
                path = design / "inputs" / (name + ".json")
                write(path, value)
                paths[name] = str(path)
            geometry_path = design / "inputs/geometry.json"
            write(geometry_path, {"ion_processor": "new_geometry"})
            write(actual / "inputs/resolved_model.json", configs)
            materialization = design / "inputs/reference_materialization.json"
            write(materialization, {"physical_diagnostic": "retained"})
            write(design / "results/joint_flight/joint_preparation_receipt.json", {
                "reference_materialization": file_record(materialization),
                "numerics": dict(trajectory_quality=3, maximum_step_us=.004,full_path_timeout_us=100),
                "assembly": {"source_config_paths": paths, "assembly_geometry_path": str(geometry_path)}})
            reference_point = dict(mirror_voltages_v=[0., -10., 20., 30., 50.],
                                   stripe_biases_v=[-4., 0.], prism_voltages_v=[100., -100.],
                                   nonaccelerator_scale=1., source_clock_marker=7500.6370908093995)
            (design / "inputs/reference_operating_point.lua").write_text(
                "return " + _lua(reference_point), encoding="utf-8")
            write(fields / "results/field_binding.json", {"new": "binding"})
            component = root / "component.json"
            write(component, {"source_run": str(actual)})
            handoff = root / "handoff.json"
            write(handoff, {"connection": {"fixture": "verified"}, "inputs": {"component_receipt": file_record(component)}})
            comparison = dict(role="mrtof_measured_exit_energy_comparison", centroid_match_accepted=None,
                              inputs={"component_receipt": file_record(component)})
            grid = dict(origin_mm=[0, -242, -425], pitch_mm=[.5, 1, 1], dimensions=[326, 801, 851])
            roles = ("global_fallback", "native_corridor", "ion_processor_collision", "detector")
            binding = dict(accelerator_provider="dual_pressure_rectilinear_ion_processor",
                           instances=[dict(role=role, pa_path=str(fields / (role + ".pa")),
                                           origin_mm=[0, index, 0]) for index, role in enumerate(roles)],
                           geometry={"ion_processor": "new_geometry"}, grid=grid,
                           sources={"scalar_pa": str(fields / "parent.pa")},
                           authority={"analyzer_electrode_voltages_v": [
                               *reference_point["mirror_voltages_v"], *reference_point["mirror_voltages_v"],
                               -27., -27., 0., 0., 0., 343., -186., 0., 0., 0.]},
                           refinement_windows=[dict(grid=grid, sources={"scalar_pa": str(fields / "ip_local.pa")},
                                                    name="ion_processor_local", active_box_mm=[[-1, 1], [-200, -30], [0, 14]])])
            # Admission/scope rejection is covered by the integration owner tests.
            verified = dict(design=json.loads((design / "results/joint_flight/joint_preparation_receipt.json").read_text()),
                design_path=design / "results/joint_flight/joint_preparation_receipt.json", design_manifest={},
                binding=binding, binding_path=fields / "results/field_binding.json",
                actual_path=actual / "inputs/resolved_model.json", connection={"fixture": "verified"})
            def source_projection(_handoff, output):
                output.mkdir()
                for name in ("source_runtime.lua", "source.fly2"):
                    (output / name).write_text("-- new measured source", encoding="utf-8")
                return {"counts": {"source": 100, "transferred": 97, "not_transferred": 3}}
            with patch("integrations.workflows.accelerator_interface.prepare.verified_reference",
                       side_effect=lambda run, relative, **kwargs: run / relative), patch(
                    "integrations.workflows.accelerator_interface.prepare.verified_preparation_reference", side_effect=lambda run, relative, **kwargs: run / relative), patch(
                    "projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding", return_value=binding), patch(
                    "projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source.materialize_measured_source",
                    side_effect=source_projection), patch(
                    "integrations.workflows.accelerator_interface.prepare.prepare_interface_field_audit",
                    return_value={"mock": "separately_tested_audit_compiler"}):
                result = bind_joint_workbench(design_run=design, field_run=fields, source_run=actual,
                                              handoff_receipt=handoff, energy_comparison=comparison,
                                              output_directory=root / "bound", _verified_inputs=verified)
                self.assertEqual(result["energy_target_acceptance"], "not_declared")
                self.assertFalse(result["six_dimensional_match_qualified"])
                self.assertFalse(result["time_focus_qualified"])
                self.assertFalse(result["joint_simulation_executed"])
                self.assertEqual(result["workbench_build_contract"]["paths"], [item["pa_path"] for item in binding["instances"]])
                sidecar = (root / "bound/runtime/joint.operating_point.lua").read_text()
                self.assertIn("field_assembly_verified=true", sidecar)
                self.assertIn("measured_source_matches_workpoint=true", sidecar)
                self.assertIn("ip_local.pa", sidecar)
                with self.subTest(verification="plain_lua_voltage_projection"):
                    lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
                    if not Path(lua).is_file():
                        self.skipTest('plain Lua unavailable; Python preparation assertions remain active')
                    check = root / "check_finalized_voltages.lua"
                    check.write_text("""local t=dofile(arg[1])
local map=dofile(arg[2])
local actual=map.physical_voltages(t.mirror_voltages_v,t.stripe_biases_v,t.prism_voltages_v,
  {0,0,0},{0},t.nonaccelerator_scale).analyser
assert(#t.static_field.analyzer_voltages_v==20)
for i=1,20 do assert((actual[i] or 0)==t.static_field.analyzer_voltages_v[i],
  'finalized sidecar differs from field at electrode '..i) end
assert(t.stripe_biases_v[1]==-27 and t.prism_voltages_v[1]==343)
assert(t.source_clock_marker==7500.6370908093995)
print('FINALIZED_FIELD_VOLTAGES=PASS')
""", encoding="utf-8")
                    evaluated = subprocess.run([lua, str(check), str(root / "bound/runtime/joint.operating_point.lua"),
                                               str(PROJECT / "simion/candidate_voltage_map.lua")],
                                              cwd=root, capture_output=True, text=True, timeout=30)
                    self.assertEqual(evaluated.returncode, 0, evaluated.stdout + evaluated.stderr)
                    self.assertIn('FINALIZED_FIELD_VOLTAGES=PASS', evaluated.stdout)
                self.assertEqual(result["measured_source"]["counts"],
                                 {"source": 100, "transferred": 97, "not_transferred": 3})
                original_fields = json.loads(json.dumps(binding))
                binding["source_descriptor_path"] = str(fields/"inputs/source_binding.json")
                binding["collision_overlay"] = dict(schema_version=1,role="mrtof_analyzer_collision_overlay",
                    patch_plan_path=str(fields/"inputs/patch_plan.json"),box_mm=[0,-4,-100,2,0,-92],
                    pitch_mm=[.05,.05,.05],dimensions=[41,81,161],priority_probes=[])
                binding["instances"].append(dict(role="analyzer_collision_patch",pa_path=str(fields/"patch.pa"),origin_mm=[0,-4,-100]))
                patched = bind_joint_workbench(design_run=design,field_run=fields,source_run=actual,
                    handoff_receipt=handoff,energy_comparison=comparison,output_directory=root/"bound_five", _verified_inputs=verified)
                self.assertIn("5_instance_seed.iob",patched["workbench_build_contract"]["seed"])
                self.assertEqual(patched["workbench_build_contract"]["paths"][:4],result["workbench_build_contract"]["paths"])
                self.assertIn("analyzer_collision_patch",(root/"bound_five/runtime/joint.priority.lua").read_text())
                self.assertIn("collision_overlay",(root/"bound_five/runtime/joint.operating_point.lua").read_text())
                self.assertIn(str(fields/"patch.pa"),patched["guard_paths"])
                self.assertIn(str(fields/"ip_local.pa"),patched["guard_paths"])
                for key in ("authority","geometry","grid","sources","refinement_windows"):
                    self.assertEqual(binding[key],original_fields[key])
                binding.clear();binding.update(original_fields)

    def test_interface_audit_consumes_sealed_inputs_and_outputs_and_rejects_conflicts(self):
        """Manifest placement does not change control identity or PA size policy."""
        from common.contracts.rigid_transform import RigidTransform
        cases = ('outputs_only', 'inputs_only', 'split', 'identical', 'relative', 'missing_control',
                 'tampered_control', 'conflicting_control', 'conflicting_basis', 'missing_basis',
                 'fresh_declared', 'reused', 'reused_missing_consumption', 'reused_declaration_conflict',
                 'reused_manifest_drift', 'reused_basis_conflict', 'reused_missing_basis', 'reused_wrong_directory')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, output, runtime, states = [root / name for name in ('source', 'output', 'runtime', 'states')]
                controls = source / 'simion'
                for folder in (controls, source / 'inputs', output, runtime, states):
                    folder.mkdir(parents=True)
                transform = RigidTransform.identity('frame').to_contract()
                (source / 'inputs/resolved_model.json').write_text(json.dumps(dict(coordinate_transform=transform)))
                control_names = ('frozen_config.lua', 'native_drive.lua', 'simion_rf_drive.lua', 'voltage_waveforms.lua')
                for name in (*control_names, *(f'processor.pa{i}' for i in range(16))):
                    (controls / name).write_bytes(b'fixture')
                records = [file_record(path) for path in controls.iterdir()]
                input_records = {Path(record['path']).name: record for record in records
                                 if case == 'inputs_only' or case == 'split' and Path(record['path']).name in control_names}
                outputs = [record for record in records if Path(record['path']).name not in input_records]
                if case in ('identical', 'conflicting_control', 'conflicting_basis', 'relative'):
                    name = 'processor.pa0' if case == 'conflicting_basis' else 'frozen_config.lua'
                    duplicate = dict(next(record for record in records if Path(record['path']).name == name))
                    if case.startswith('conflicting'):
                        duplicate['sha256'] = '0' * 64
                    elif case == 'relative':
                        duplicate['path'] = 'simion/frozen_config.lua'
                    input_records['duplicate'] = duplicate
                if case.startswith('missing'):
                    name = 'frozen_config.lua' if case == 'missing_control' else 'processor.pa0'
                    outputs = [record for record in outputs if Path(record['path']).name != name]
                if case == 'fresh_declared':
                    (source / 'inputs/resolved_model.json').write_text(json.dumps(dict(
                        coordinate_transform=transform,
                        native_field=dict(directory=str(controls), source_manifest=None))))
                if case.startswith('reused'):
                    producer = root / 'field_producer'
                    (producer / 'simion').mkdir(parents=True)
                    producer_records = []
                    for index in range(16):
                        path = controls / f'processor.pa{index}'
                        target = producer / 'simion' / path.name
                        path.rename(target)
                        producer_records.append(file_record(target))
                    # Deliberately different producer drive must never be selected.
                    (producer / 'simion/native_drive.lua').write_text('old field producer drive')
                    producer_manifest = producer / 'run_manifest.json'
                    producer_manifest.write_text(json.dumps(dict(
                        project='dual_pressure_rectilinear_ion_processor', status='success',
                        outputs=producer_records)))
                    producer_identity = file_record(producer_manifest)
                    declaration = dict(directory=str(producer / 'simion'), source_manifest=str(producer_manifest),
                        source_manifest_sha256=producer_identity['sha256'],
                        consumer_projection_id='ion_processor_native_field_v1')
                    consumption = source / 'inputs/native_field_consumption.json'
                    consumption.write_text(json.dumps(dict(declaration,
                        verification='RUN_MANIFEST_VERIFY=PASS SCOPE=consumer_projection PROJECTION=ion_processor_native_field_v1')))
                    input_records.update(field_manifest=producer_identity,
                                         consumption=file_record(consumption))
                    input_records.update({f'basis_{i}': dict(record) for i, record in enumerate(producer_records)})
                    outputs = [record for record in outputs if Path(record['path']).name in control_names]
                    if case == 'reused_missing_consumption':
                        del input_records['consumption']
                    elif case == 'reused_declaration_conflict':
                        declaration['source_manifest_sha256'] = '0' * 64
                    elif case == 'reused_manifest_drift':
                        producer_manifest.write_text('{}')
                    elif case == 'reused_basis_conflict':
                        input_records['basis_0']['sha256'] = '0' * 64
                    elif case == 'reused_missing_basis':
                        (producer / 'simion/processor.pa0').unlink()
                    elif case == 'reused_wrong_directory':
                        declaration['directory'] = str(controls)
                    (source / 'inputs/resolved_model.json').write_text(json.dumps(dict(
                        coordinate_transform=transform, native_field=declaration)))
                (source / 'run_manifest.json').write_text(json.dumps(dict(inputs=input_records, outputs=outputs)))
                if case == 'tampered_control':
                    (controls / 'frozen_config.lua').write_bytes(b'changed')
                (output / 'static_field_binding.json').write_bytes(b'{}')
                (runtime / 'mrtof_candidate.scalar_field_adapter.lua').write_bytes(b'fixture')
                (states / 'component_particle_state.csv').write_text(
                    'particle_id,mass_amu,charge_state,instrument_time_us,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n1,524,1,11,0,0,0,0,10,0\n')
                grid = dict(origin_mm=[0,-2,-2], pitch_mm=[.1,.1,.1], dimensions=[21,41,41], symmetry='x')
                arguments = dict(source_run=source, handoff=dict(rigid_transform=transform), source_directory=states,
                    binding=dict(refinement_windows=[dict(name='ion_processor_local', grid=grid,
                        active_box_mm=[[-1,1],[-1,1],[-1,1]])]),
                    native=dict(refinement_windows=[dict(mode='native_static_pa', scalar_pa='fine.pa', **grid)]),
                    runtime=runtime, output=output)
                if case in ('outputs_only', 'inputs_only', 'split', 'identical', 'relative', 'fresh_declared', 'reused'):
                    with patch('common.contracts.write_run_manifest.file_sha256', wraps=file_sha256) as hash_file:
                        result = prepare_interface_field_audit(**arguments)
                    self.assertFalse(any(Path(call.args[0]).name.startswith('processor.pa')
                                         for call in hash_file.call_args_list))
                    request = json.loads(Path(result['request']['path']).read_text())
                    self.assertEqual(len(result['guard_paths']), 16)
                    self.assertEqual(set(request['inputs']['source_controls']), set(control_names))
                    self.assertEqual(Path(result['guard_paths'][0]).name, 'processor.pa0')
                    if case == 'reused':
                        self.assertEqual(Path(result['guard_paths'][0]).parent, producer / 'simion')
                        self.assertFalse((controls / 'processor.pa0').exists())
                        frozen_drive = Path(request['inputs']['source_controls']['native_drive.lua']['path'])
                        self.assertEqual(frozen_drive.read_bytes(), b'fixture')
                        self.assertEqual(request['inputs']['source_field_authority']['producer_manifest'], producer_identity)
                else:
                    with self.assertRaises((ValueError, AssertionError)):
                        prepare_interface_field_audit(**arguments)

    def test_interface_field_audit_uses_actual_clock_basis_route_and_centroid_ledger(self):
        import csv
        from common.contracts.rigid_transform import RigidTransform
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file():
            self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, runtime = root / 'source', root / 'output', root / 'runtime'
            controls, states = source / 'simion', output / 'measured_source'
            for folder in (controls, source / 'inputs', runtime, states):
                folder.mkdir(parents=True)
            # Source local x maps to MR y; free vectors must rotate as well.
            transform = RigidTransform('local', 'project', ((0,0,1),(1,0,0),(0,1,0)), (0,0,0))
            handoff = dict(rigid_transform=RigidTransform.identity('project').to_contract())
            (source / 'inputs/resolved_model.json').write_text(json.dumps(dict(coordinate_transform=transform.to_contract())))
            (controls / 'frozen_config.lua').write_text('return {baseline={clock={epoch_us=10},electric={rf_frequency_hz=1,rf_peak_to_peak_v=2}},numerics={rf_steps_per_period=27},native_projection={origin_mm={-2,-2,-2},maximum_mm={2,2,2},grid_mm=.1}}')
            (controls / 'native_drive.lua').write_text('local w=...;assert(w.producer_marker==731);return {voltages=function(c,t,rf) assert(rf==t+10);local v={t};for id=2,15 do v[id]=0 end;return v end}')
            (controls / 'simion_rf_drive.lua').write_text('return {new=function() return {differential_at=function(t) return t end} end}')
            (controls / 'voltage_waveforms.lua').write_text('return {producer_marker=731}')
            for index in range(16):
                (controls / f'processor.pa{index}').write_text('mock basis')
            (source / 'run_manifest.json').write_text(json.dumps(dict(outputs=[file_record(p) for p in controls.iterdir()])))
            (output / 'static_field_binding.json').write_text('{}')
            (states / 'component_particle_state.csv').write_text('particle_id,mass_amu,charge_state,instrument_time_us,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n1,524,1,11,0,0,0,0,10,0\n7,524,1,13,0,0,0,0,20,0\n')
            grid = dict(origin_mm=[0,-2,-2],pitch_mm=[.1,.1,.1],dimensions=[21,41,41],symmetry='x')
            window = dict(name='ion_processor_local',grid=grid,active_box_mm=[[-1,1],[-1,1],[-1,1]])
            native = dict(refinement_windows=[dict(mode='native_static_pa',scalar_pa='fine.pa',**grid)])
            # Stub adapter proves the production query passes raw_sample and only
            # one fine level, rather than loading a full routed five-level field.
            (runtime / 'mrtof_candidate.scalar_field_adapter.lua').write_text("return function(level,mode) assert(mode=='raw_sample' and level.scalar_pa=='fine.pa' and level.refinement_windows==nil);return function() return 101,0,10,0 end end")
            result = prepare_interface_field_audit(source_run=source, handoff=handoff, source_directory=states,
                binding=dict(refinement_windows=[window]), native=native, runtime=runtime, output=output)
            request = json.loads(Path(result['request']['path']).read_text())
            self.assertEqual(len(result['guard_paths']),16)
            self.assertEqual([p['instrument_time_us'] for p in request['points']], [11,13,12])
            fixture = root / 'mock.lua'
            fixture.write_text("simion={pas={open=function() return {nx=41,ny=41,nz=41,inside_vc=function()return true end,potential_vc=function(self,x,y,z,v)return v[1] end,field_vc=function(self,x,y,z,v)return 1,0,0 end} end}};local program,request=unpack(arg);arg={'--',request};dofile(program)")
            completed = subprocess.run([lua,str(fixture),result['program'],result['lua_request']],cwd=root,timeout=30,capture_output=True,text=True,check=False)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            raw = Path(result['raw_output']).read_bytes()
            report = summarize_interface_field_audit(Path(result['raw_output']).parent)
            self.assertFalse((Path(result['raw_output']).parent / 'joint_flight_preparation.py').exists())
            self.assertEqual(report['particle_count'],2)
            self.assertEqual(report['mean_delta_phi_constant_v'],99)
            self.assertEqual(report['max_abs_delta_phi_without_constant_v'],1)
            self.assertEqual(report['max_delta_field_norm_v_mm'],0)
            self.assertEqual(report['samples'][0]['source_field_mr_v_mm'],[0,10,0])
            self.assertLess(report['centroid']['kinetic_energy_of_mean_velocity_ev_per_q'], report['centroid']['mean_particle_kinetic_energy_ev_per_q'])
            self.assertFalse(report['physical_matching_qualified'])
            self.assertIsNone(report['tolerance'])
            self.assertEqual(raw,Path(result['raw_output']).read_bytes())
            with Path(result['raw_output']).open(newline='') as handle:
                self.assertEqual([r['source_phi_v'] for r in csv.DictReader(handle)],['1','3','2'])

    def test_interface_audit_rejects_shadowed_route_or_missing_gradient_halo(self):
        grid = dict(origin_mm=[0,-2,-2],pitch_mm=[.1,.1,.1],dimensions=[21,41,41],symmetry='x')
        window = dict(name='ion_processor_local',grid=grid,active_box_mm=[[-1,1],[-1,1],[-1,1]])
        points = [dict(position_mm=[0,0,0])]
        self.assertEqual(audit_field_coverage(points,[window])['first_match_rank_zero_based'],0)
        with self.assertRaisesRegex(ValueError,'not entirely routed'):
            audit_field_coverage(points,[dict(window,name='covered_local'),window])
        with self.assertRaisesRegex(ValueError,'gradient halo'):
            audit_field_coverage([dict(position_mm=[0,-2,0])],[dict(window,active_box_mm=[[-1,1],[-2,1],[-1,1]])])

    def test_actual_event_audit_binds_original_6d_queries_selected_fields_and_retains_nonzero_phi(self):
        import csv
        lua = shutil.which('lua') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not Path(lua).is_file():
            self.skipTest('plain Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name,value):
                path=root/name;path.write_text(json.dumps(value));return path
            canonical=root/'state.csv'
            canonical.write_text('particle_id,mass_amu,charge_state,instrument_time_us,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n1,524,1,7500.5,0,0,0,0,0,-10000\n')
            source=write('source.json',dict(role='mrtof_measured_exit_centroid_probe_source',
                outputs=dict(component_particle_state=file_record(canonical))))
            adapter=root/'adapter.lua'
            adapter.write_text("return function(level,mode) assert(mode=='raw_sample' and level.refinement_windows==nil);local phi=level.scalar_pa=='ip.pa' and 11 or (level.scalar_pa=='mirror.pa' and 17 or 13);return function() return phi,1,2,3 end end")
            binding_path=write('binding.json',dict(candidate='actual_probe'))
            prep=write('prepared.json',dict(source_mode='centroid_probe',expected_particle_ids=[1],
                field_binding=file_record(binding_path),field_consumer_adapter=file_record(adapter)))
            flight=root/'flight.log';flight.write_text('synthetic natural N1 evidence, no solver called')
            events=[dict(kind=kind,t_us=7501+i,x_mm=0,y_mm=0,z_mm=z,vx_mm_us=0,vy_mm_us=.1,vz_mm_us=-10)
                    for i,(kind,z) in enumerate((('clean',0),('p2_low_field_crossing',3),('mirror_turn',6)))]
            csv_path=root/'probe_event_states.csv'
            with csv_path.open('w',newline='') as handle:
                keys=['event','instrument_time_us','x_mm','y_mm','z_mm','vx_mm_us','vy_mm_us','vz_mm_us']
                writer=csv.DictWriter(handle,fieldnames=keys);writer.writeheader()
                for e in events:
                    writer.writerow(dict(event=e['kind'],instrument_time_us=e['t_us'],**{k:e[k] for k in keys[2:]}))
            source_state=dict(position_mm=[0,0,0],velocity_mm_per_us=[0,0,-10],instrument_time_us=7500.5,mass_amu=524,charge_state=1)
            projection=write('controller_projection.json',dict(role='mrtof_measured_exit_centroid_controller_projection',
                inputs=dict(preparation=file_record(prep),source_receipt=file_record(source),log=file_record(flight)),
                outputs=dict(probe_event_states=file_record(csv_path)),observation=dict(events=events),
                materialization=dict(source_center_state=source_state)))
            grid=dict(origin_mm=[0,-2,-2],pitch_mm=[.1,.1,.1],dimensions=[21,41,101],symmetry='x')
            def level(name,path,box):
                return dict(name=name,mode='native_static_pa',grid=grid,active_box_mm=box,
                            sources=dict(scalar_pa=path),records=dict(scalar_pa=dict(path=path,sha256='sealed',bytes=10)))
            binding=dict(level('global','global.pa',[[-1,1],[-1,1],[-1,7]]),refinement_windows=[
                level('ion_processor_local','ip.pa',[[-1,1],[-1,1],[-1,1]]),
                level('positive_integer_grid_a','mirror.pa',[[-1,1],[-1,1],[5,7]]),
                level('covered_local','covered.pa',[[-1,1],[-1,1],[-1,7]])])
            target=root/'audit'
            module='projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding'
            with patch(module,return_value=binding):
                plan=prepare_event_field_audit(projection,binding_path,target)
            self.assertEqual([j['rank_zero_based'] for j in plan['jobs']],[0,2,1])
            self.assertEqual([p['event'] for p in plan['points']],['source_centroid','clean','p2_low_field_crossing','mirror_turn'])
            fixture=root/'mock.lua';fixture.write_text("local program,request=unpack(arg);arg={'--',request};dofile(program)")
            for job in plan['jobs']:
                completed=subprocess.run([lua,str(fixture),job['program'],job['request']['path']],cwd=root,timeout=30,capture_output=True,text=True,check=False)
                self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            ledger=summarize_event_field_audit(target)
            self.assertEqual([p['phi_v'] for p in ledger['samples']],[11,11,13,17])
            self.assertEqual(ledger['samples'][2]['velocity_mm_per_us'],[0,.1,-10])
            self.assertEqual(ledger['samples'][2]['instrument_time_us'],7502)
            self.assertEqual(ledger['samples'][2]['field_name'],'covered_local')
            self.assertAlmostEqual(ledger['samples'][2]['k_over_q_plus_phi_v'],ledger['samples'][2]['kinetic_energy_per_charge_ev']+13)
            self.assertNotEqual(ledger['samples'][2]['delta_h_from_source_centroid_v'],0)
            self.assertIsNone(ledger['tolerance'])
            wrong=write('wrong_binding.json',dict(candidate='not_the_probe'))
            with self.assertRaisesRegex(ValueError,'actual probe field binding'):
                prepare_event_field_audit(projection,wrong,root/'bad_binding')
            events[1]['z_mm']=3.5
            value=json.loads(projection.read_text());value['observation']['events']=events;projection.write_text(json.dumps(value))
            with patch(module,return_value=binding),self.assertRaisesRegex(ValueError,'actual observed 6D'):
                prepare_event_field_audit(projection,binding_path,root/'bad_state')


if __name__ == '__main__':
    unittest.main()
