"""Installed RF whole-batch continuation, using a tiny inert published fixture."""
import json
from pathlib import Path
import subprocess
import sys
import sysconfig


def run(root, arm, timer, blocked_roots):
    """Exercise actual installed direct and CLI routes; no SIMION is started."""
    from msplatform.backends.simion.native_completion import retention_api
    from msplatform.contracts.machine_contracts import ContractError
    from msplatform.execution.manifest_publication import build_run_manifest
    from msplatform.execution.terminal_publication import publish_terminal_state
    from msplatform.workflows import rf_batch_continuation as continuation

    purelib=Path(sysconfig.get_paths()['purelib']).resolve()
    module=Path(continuation.__file__).resolve()
    assert module==purelib/'msplatform/workflows/rf_batch_continuation.py'
    base=Path(root)/('installed-rf-continuation-'+str(arm));base.mkdir(exist_ok=False)
    parent=base/'20261114_120000__sim__simion__fixture'
    direct=base/'20261114_120001__sim__simion__fixture'
    cli=base/'20261114_120002__sim__simion__fixture'
    names=['resolved_design','particle_table','simion_program_source','numerical_contract',
           'simion_layout_template_iob','simion_layout_template_con']
    case='interface_readiness';project='rf_multipole_ion_optics';mode='transport_interface_readiness'
    for run in (parent,direct,cli):
        for directory in ('inputs','results','logs'): (run/directory).mkdir(parents=True,exist_ok=True)
        inputs={}
        for name in names:
            path=run/'inputs'/(name+'.json');path.write_text(name,encoding='utf8');inputs[name]=str(path)
        physics=run/'inputs/simion_fly_physics.json'
        physics.write_text(json.dumps({'role':'multipole_simion_fly_physics','cases':{case:{'rf':7}},
                                       'source_modules':{'slicer.py':'unchanged'}}),encoding='utf8')
        inputs['simion_fly_physics']=str(physics)
        partition=run/'inputs/simion_execution_batch_plan.json'
        partition.write_text(json.dumps({'particle_count':2,'batch_count':2,'batches':[
            {'index':i,'particle_id_min':i,'particle_id_max':i,'simion_particle_id_offset':i-1} for i in (1,2)]}),encoding='utf8')
        inputs['simion_execution_batch_plan']=str(partition)
        config={'schema_version':1,'run_id':run.name,'project':project,'mode':mode,'inputs':inputs}
        (run/'run_config.json').write_text(json.dumps(config),encoding='utf8')
    outputs=[];index=2
    for relative in (Path('logs/batch_02/simion_stdout.txt'),Path('results/particle_state__batch_02.csv'),Path('results/solver_summary__batch_02.json')):
        target=parent/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(relative.name,encoding='utf8');outputs.append(target)
    receipt=parent/f'results/simion_batch_completion__{case}__batch_02.json'
    receipt.write_text(json.dumps({'role':'multipole_simion_completed_batch','case':case,'batch_index':index,
        'particle_id_min':index,'particle_id_max':index,'particle_count':1,
        'outputs':[str(p.relative_to(parent)) for p in outputs]}),encoding='utf8');outputs.append(receipt)
    manifest=build_run_manifest(parent/'run_config.json','failed',output_paths=outputs,retention_api=retention_api)
    publish_terminal_state(parent,{'status':'failed'},manifest)
    original=(parent/'run_manifest.json').read_bytes()
    blocked=json.dumps([str(Path(p).resolve()) for p in blocked_roots])
    bootstrap=r'''import importlib.abc,json,os,pathlib,runpy,sys
blocked=[pathlib.Path(v).resolve() for v in json.loads(sys.argv.pop(1))]
def deny(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  path=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(path.is_relative_to(root) for root in blocked):raise AssertionError('author read: '+str(path))
sys.addaudithook(deny)
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}:raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,Guard())
import msplatform.workflows.rf_batch_continuation as target,sysconfig
assert pathlib.Path(target.__file__).resolve()==pathlib.Path(sysconfig.get_path('purelib')).resolve()/'msplatform/workflows/rf_batch_continuation.py'
sys.argv[0]='msplatform.workflows.rf_batch_continuation'
runpy.run_module('msplatform.workflows.rf_batch_continuation',run_name='__main__')
'''
    def invoke(arguments):
        return subprocess.run([sys.executable,'-I','-B','-c',bootstrap,blocked,*arguments],cwd=base,
            capture_output=True,text=True,encoding='utf8',timeout=30,check=False)
    with timer('rf_continuation_installed',str(arm)):
        assert continuation.ancestry(parent,project,mode)==[parent.resolve()]
        result=continuation.prepare(direct,parent,[case],'compact',False,names,'prepared')
        assert [unit['action'] for unit in result['replay']['units']]==['replay','reuse']
        assert (direct/'inputs/simion_whole_unit_replay_plan.json').is_file()
        ancestry=invoke(['--predecessor',str(parent),'--project',project,'--mode',mode])
        assert ancestry.returncode==0,(ancestry.stdout,ancestry.stderr)
        assert json.loads(ancestry.stdout)==[str(parent.resolve())]
        command=['--predecessor',str(parent),'--project',project,'--mode',mode,'--run-dir',str(cli),
                 '--case',case,'--retention','compact','--output-layout','prepared']
        for name in names: command.extend(['--input',name])
        planned=invoke(command)
        assert planned.returncode==0,(planned.stdout,planned.stderr)
        assert [unit['action'] for unit in json.loads(planned.stdout)['replay']['units']]==['replay','reuse']
        state=parent/'results/particle_state__batch_02.csv';old=state.read_bytes()
        try:
            state.write_bytes(old+b'!')
            try: continuation.prepare(direct,parent,[case],'compact',False,names,'prepared')
            except ContractError as error: assert 'hash differs' in str(error),str(error)
            else: raise AssertionError('tampered predecessor accepted')
        finally: state.write_bytes(old)
        manifest_path=parent/'run_manifest.json';old_manifest=manifest_path.read_bytes()
        try:
            manifest_path.unlink()
            try: continuation.ancestry(parent,project,mode)
            except FileNotFoundError as error: assert error.filename and Path(error.filename)==manifest_path
            else: raise AssertionError('missing predecessor manifest accepted')
        finally: manifest_path.write_bytes(old_manifest)
        assert manifest_path.read_bytes()==original
        module_bytes=module.read_bytes()
        try:
            module.unlink()
            missing=subprocess.run([sys.executable,'-I','-B','-c',bootstrap,blocked,'--predecessor',str(parent),'--project',project,'--mode',mode],cwd=base,capture_output=True,text=True,encoding='utf8',timeout=30,check=False)
            assert missing.returncode!=0 and missing.stderr.rstrip().splitlines()[-1:] == ["ModuleNotFoundError: No module named 'msplatform.workflows.rf_batch_continuation'"],missing.stderr
            assert 'author read:' not in missing.stderr and 'author import:' not in missing.stderr,missing.stderr
        finally: module.write_bytes(module_bytes)
        assert module.read_bytes()==module_bytes
    print('INSTALLED_RF_CONTINUATION=PASS native=NOT_STARTED arm='+str(arm),flush=True)
