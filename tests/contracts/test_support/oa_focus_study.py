"""Explicit software-only OA Study derived from one real campaign author."""
import hashlib
import json
from pathlib import Path

from msplatform.workflows.oa_focus_model_projection import project_focus_model

ROOT=Path(__file__).resolve().parents[3]
COMPONENT=ROOT/'src/msplatform/components/orthogonal_accelerator'


def make_focus_recipe(root: Path):
    root.mkdir(parents=True,exist_ok=True)
    source=COMPONENT/'config/two_zone_component_focus_campaign.json'
    payload=source.read_bytes();campaign_path=root/'focus_campaign.json';campaign_path.write_bytes(payload)
    campaign=json.loads(payload);contract=json.loads((COMPONENT/'component_contract.json').read_text(encoding='utf8'))
    profile=contract['geometry_profiles'][campaign['geometry_profile_id']]
    clock=dict(clock_epoch_id='instrument_clock_epoch_v1',
        authority_sha256='6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0',
        phase_reference_instrument_time_us=0.)
    projection=project_focus_model(campaign_path,geometry_profile=profile,mesh_mm_per_gu=[.25,.25,.1],clock=clock)
    drive=dict(projection['drive'],clock={'phase_reference_instrument_time_us':0.},
               clock_authority={'example_resource':'instrument_clock_authority_v1.json'})
    study=dict(schema_version=1,name='original_oa_focus_software_fixture',
        component_requests=projection['component_requests'],recipe=projection['recipe'],drive=drive,
        physics=projection['physics'],release=dict(schema_version=1,role='oa_focus_campaign_birth_request',
            clock={key:clock[key] for key in ('clock_epoch_id','authority_sha256')},instrument_origin_us=0.,
            species_id='oa_focus_100amu_z1',source_component_id='oa',relative_weights=None),
        numerics=dict(geometry=projection['geometry_numerics'],fields={'refine_policy':'vendor_default'},
            tracing=dict(end_policy={'maximum_particle_age_us':50.},simion={'maximum_step_us':.0005,'trajectory_quality':8})),
        cad_export=dict(representation='physical_solids',write_pcurves=True,precision_mode=0),
        claim_limit='Software fixture only; 50 us endpoint and 0.1 us sample are explicit fixture choices, not original campaign.',
        model_input_sources={'oa_focus_campaign':{'path':campaign_path.name,'sha256':hashlib.sha256(payload).hexdigest()}})
    study_path=root/'study.json';study_bytes=(json.dumps(study,indent=2)+'\n').encode();study_path.write_bytes(study_bytes)
    author=root/'recipe.toml';author.write_text('schema_version = 2\nconstants_version = "repository_particle_physics_v1"\n'
        'label = "OA focus software fixture"\nparticle_tracer = "simion"\nfield_assembly_strategy = "native_domain_composition"\n'
        'particle_field_coupling = "external_given_field"\n[study]\npath = "study.json"\nsha256 = "'+hashlib.sha256(study_bytes).hexdigest()+'"\n'
        '[field_source]\nkind = "simion_native"\n[recording]\nmode = "observation_times"\nobservation_times_us = [0.1]\n'
        '[gas_environment]\nstatus = "vacuum"\n',encoding='utf8')
    return author,study,projection


def make_signed_focus_recipe(root: Path, *, species_kind: str):
    """Derive an explicit software author for signed birth, without native claims."""
    from msplatform.contracts.particle_physics import ELECTRON_CONSTANTS
    author,study,projection=make_focus_recipe(root)
    if species_kind not in {'negative_ion','electron'}:
        raise ValueError('explicit negative_ion or electron is required')
    campaign_path=root/'focus_campaign.json'
    campaign=json.loads(campaign_path.read_bytes())
    campaign['release_spec']['species']=dict(species_kind='ion' if species_kind=='negative_ion' else 'electron',
        mass_amu=100. if species_kind=='negative_ion' else ELECTRON_CONSTANTS['mass_u'],charge_state=-1)
    payload=(json.dumps(campaign,indent=2)+'\n').encode();campaign_path.write_bytes(payload)
    study['model_input_sources']['oa_focus_campaign']['sha256']=hashlib.sha256(payload).hexdigest()
    study['release']['species_id']=species_kind
    study_path=root/'study.json';study_bytes=(json.dumps(study,indent=2)+'\n').encode();study_path.write_bytes(study_bytes)
    original=author.read_text(encoding='utf8')
    import re
    author.write_text(re.sub(r'(\[study\]\npath = "study.json"\nsha256 = ")[^"]+',
        lambda match:match.group(1)+hashlib.sha256(study_bytes).hexdigest(),original),encoding='utf8')
    previous=projection['observations']
    projection=project_focus_model(campaign_path,geometry_profile=previous['geometry_profile'],
        mesh_mm_per_gu=previous['mesh_mm_per_gu'],clock=previous['clock'])
    return author,study,projection
