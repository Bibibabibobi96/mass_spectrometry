"""Original RF/IP Assembly and explicit gas authors for public software tests."""
import copy
import hashlib
import json
from pathlib import Path

from tests.contracts.test_joint_ip_model import JointIpModelTests
from tests.components.ion_processor.test_functional import HS1_SOURCE_FIXTURE
from tests.assembly.rf_ip.test_ip_compiler import IpCompilerTests


ROOT = Path(__file__).resolve().parents[3]


def write_rf_ip_recipe_fixture(root: Path) -> Path:
    """Retain real provider geometry, RF birth author and explicit 4 Pa outer fixture."""
    root.mkdir(parents=True, exist_ok=True)
    fixture=IpCompilerTests();fixture.setUp()
    model=JointIpModelTests();model.setUp()
    example=json.loads((ROOT/'src/msplatform/examples/rf_oatof_functional_v1.json').read_bytes())
    template=json.loads((ROOT/'src/msplatform/examples/oa_split_tof_native_small_v1.json').read_bytes())
    components={'multipole':copy.deepcopy(example['component_requests']['multipole']),
        'ion_processor':dict(provider_id='ion_processor',design=copy.deepcopy(fixture.assembly.components_source['ion_processor']))}
    drive=copy.deepcopy(model.drive);drive['clock_authority']={'example_resource':'instrument_clock_authority_v1.json'}
    drive['clock']={'phase_reference_instrument_time_us':drive['clock']['phase_reference_instrument_time_us']}
    release=copy.deepcopy(example['release'])
    release['release_spec']['particle_count']=release['release_spec']['mother_particle_count']=3
    release['particle_ids']=release['particle_ids'][:3]
    template.update(name='rf_ip_inert_public_recipe', component_requests=components,
        recipe=fixture.assembly.composition_plan['recipe'], drive=drive,
        physics=dict(field_model='external_electrostatic_linear',boundary_policy='grounded_pa_faces'), release=release,
        numerics=dict(geometry=fixture.numerics,fields=dict(refine_policy='explicit_convergence',convergence_v={'parent':.1}),
            tracing=dict(end_policy=dict(maximum_particle_age_us=200.),simion=dict(maximum_step_us=.001,
                trajectory_quality=17,rf_steps_per_period=80,grouped=0))),
        claim_limit='inert public software fixture; no native qualification',model_input_sources={'fixture':'real RF/IP authors; three-particle technical test selection'})
    def write(name,payload):
        (root/name).write_bytes(payload)
        return dict(path=name,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest().upper())
    study=write('study.json',json.dumps(template).encode())
    env=json.loads((ROOT/'src/msplatform/components/ion_processor/config/gas_environment.json').read_bytes())
    env['outer_state']=dict(pressure_pa=4.,temperature_k=300.,bulk_velocity_m_s=[1.,2.,3.])
    environment=write('environment.json',json.dumps(env).encode());vendor=write('vendor.lua',HS1_SOURCE_FIXTURE.encode())
    box=lambda lo,hi:dict(minimum_mm=lo,maximum_mm=hi,lower_closed=[True]*3,upper_closed=[True]*3)
    hs1=dict(bath_domain=box([0,-10,-10],[211,10,10]),outer_domain=box([-10000]*3,[10000]*3),
        numerics=dict(seed=40,hs1_steps_per_mfp=20),environment_instance_id='ion_processor',
        environment_record=environment,vendor_record=vendor)
    h=write('hs1.json',json.dumps(hs1).encode())
    text=f'''schema_version = 2
constants_version = "repository_particle_physics_v1"
label = "RF IP inert fixture"
particle_tracer = "simion"
field_assembly_strategy = "native_domain_composition"
particle_field_coupling = "external_given_field"
[study]
path = "study.json"
sha256 = "{study['sha256']}"
[field_source]
kind = "simion_native"
[recording]
mode = "observation_times"
observation_times_us = [199.0]
plane_observations = []
[gas_environment]
status = "hs1"
path = "hs1.json"
sha256 = "{h['sha256']}"
'''
    author=root/'author.toml';author.write_text(text,encoding='utf8',newline='\n')
    return author
