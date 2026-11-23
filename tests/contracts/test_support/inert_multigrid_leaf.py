"""Inert managed-test child: never starts COMSOL, MATLAB, or a solver."""
import ctypes,json,subprocess,sys
from pathlib import Path
c=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
spec=json.loads(Path(c['batch_spec']).read_text(encoding='utf8'))
for index,entry in enumerate(spec['entries']):
 if index==1 and c['fail_second']:sys.exit(7)
 g=json.loads(Path(entry['grid_path']).read_text(encoding='utf8'))
 out=Path(entry['output_directory'])
 (out/'field_v.pa').write_bytes(bytes.fromhex(c['potential_hex']))
 (out/'field_valid.pa').write_bytes(bytes.fromhex(c['mask_hex']))
 report=dict(g,status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=c['model'],vacuum_domains=[1],fem_valid=1,invalid_count=44,solution_readback=c['solution'],coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'})
 Path(entry['report_path']).write_text(json.dumps(report),encoding='utf8')
Path(c['batch_report']).write_text(json.dumps({'status':'success','scope':'assembly_world_scalar_grid_batch','grid_count':len(spec['entries']),'compute_calls':0}),encoding='utf8')
Path(c['bootstrap']).write_text('STATUS=PASS',encoding='utf8')
child=subprocess.Popen([sys.executable,'-I','-B','-c','pass'],cwd=Path(c['batch_spec']).parent)
creation=ctypes.c_ulonglong();exit_time=ctypes.c_ulonglong();kernel=ctypes.c_ulonglong();user=ctypes.c_ulonglong()
if not ctypes.windll.kernel32.GetProcessTimes(ctypes.c_void_p(int(child._handle)),ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel),ctypes.byref(user)):raise OSError('GetProcessTimes failed')
code=child.wait(timeout=30);assert code==0
receipt={'schema_version':1,'role':'comsol_launcher_completion','run_id':c['run_id'],'operations':[{'observation':{'exit_confirmed':True,'returncode':code,'process_id':child.pid,'process_started_at_utc_ticks':creation.value+504911232000000000}}],'host_release':{'inherited':True,'token':None,'result':None,'error':None}}
Path(c['completion']).write_text(json.dumps(receipt),encoding='utf8')
