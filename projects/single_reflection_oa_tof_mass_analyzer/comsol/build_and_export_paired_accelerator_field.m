function facts = build_and_export_paired_accelerator_field(planPath, outputDir, SavedModelPath, SavedModelStage)
%BUILD_AND_EXPORT_PAIRED_ACCELERATOR_FIELD OA-only static ON electrostatics.
% Requires an established managed LiveLink connection; owns no process/run.
% COMSOL 6.4 APIs (checked 2026-10-24): Boolean/WorkPlane, model.selection,
% mphinterp (explicit V/m, model-mm coordinates), mphsave. References:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.070.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_geom.48.143.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.56.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.37.html
% Saved-solution check (COMSOL 6.4 SolverSequence.isEmpty):
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/SolverSequence.html
% Size/getters/unit evaluation (6.4): comsol_api_mesh.49.100.html,
% api/com/comsol/model/ParameterEntity.html and ParamBase.html.
% Prepared mesh/solver transport uses mphsave/mphload; this reruns only the
% missing stationary solve, not solver checkpoint continuation (checked 2026-10-25):
% https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_model.6.07.html
% https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.40.html
% No particles, RF, OFF state, pulse, downstream geometry or tolerance verdict.
arguments
    planPath (1,:) char
    outputDir (1,:) char
    SavedModelPath (1,:) char = ''
    SavedModelStage (1,:) char {mustBeMember(SavedModelStage,{'prepared_saved','solved_saved'})} = 'solved_saved'
end
import com.comsol.model.util.*
plan=jsondecode(fileread(planPath));
assert(plan.schema_version==2 && strcmp(plan.role,'oatof_paired_accelerator_static_field_plan'), ...
    'oatof:PairedPlan','Current paired static-field plan required.');
assert(strcmp(plan.accelerator_variant,'three_zone_square') && strcmp(plan.coordinate_frame,'oatof_global'), ...
    'oatof:PairedScope','Only the prepared three-zone square OA scope is supported.');
domain=plan.numerical_domain; g=plan.accelerator_geometry;
assert(strcmp(domain.comsol_outer_boundary,'zero_charge') && strcmp(domain.boundary_policy,'native_zero_neumann'), ...
    'oatof:PairedBoundary','Common zero-normal boundary contract required.');
id=plan.oatof_instance_id;
scope=plan.composition_plan;
assert(numel(scope.scope.instance_ids)==1 && strcmp(scope.scope.instance_ids{1},id), ...
    'oatof:PairedScope','Exactly the selected OA instance is required.');
instances=scope.recipe.instances;
selected=find(strcmp({instances.instance_id},id));
assert(numel(selected)==1,'oatof:PairedPose','Selected provider instance is missing or duplicated.');
port=scope.components.(id).ports.side_entry;
assert(strcmp(port.cross_section.shape,'rectangle'),'oatof:PairedPort','Mechanical rectangle required.');
opening=struct('center_mm',port.center_mm,'width_mm',port.cross_section.width_mm, ...
    'height_mm',port.cross_section.height_mm);
binding=plan.native_geometry_compilation.electrode_bindings.(id);
points=readtable(plan.sample_points.path,'VariableNamingRule','preserve');
assert(isequal(points.Properties.VariableNames,{'point_id','x_mm','y_mm','z_mm'}) && ...
    height(points)==plan.sample_points.count && height(points)>0, ...
    'oatof:PairedPoints','Exact prepared point coverage required.');
assert(all(isfinite(points{:,:}),'all') && all(points.point_id>=0 & points.point_id==fix(points.point_id)) && ...
    numel(unique(points.point_id))==height(points), 'oatof:PairedPoints','Finite unique point IDs/coordinates required.');
if ~isfolder(outputDir), mkdir(outputDir); end
previousPath=path; restorePath=onCleanup(@() path(previousPath)); %#ok<NASGU>
projectsRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
addpath(fullfile(projectsRoot,'orthogonal_accelerator','comsol'));
addpath(fullfile(fileparts(projectsRoot),'common','comsol'));
tag='PairedAcceleratorStatic';
if ~isempty(SavedModelPath)
    % Explicit owner-bound input; a solved source remains export-only.
    model=mphload(SavedModelPath,tag);
    cleanupModel=onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
    read_mesh_contract(model,plan);
    if strcmp(SavedModelStage,'solved_saved')
        assert(~model.sol('sol1').isEmpty(),'oatof:PairedSolution','Saved stationary solution is empty.');
        facts=export_field_samples(model,plan,planPath,points,outputDir,SavedModelPath);
    else
        assert(model.sol('sol1').isEmpty(),'oatof:PairedSolution','Prepared source unexpectedly contains a solution.');
        modelPath=solve_and_save(model,planPath,outputDir);
        facts=export_field_samples(model,plan,planPath,points,outputDir,modelPath);
    end
    return
end
assert(strcmp(SavedModelStage,'solved_saved'),'oatof:PairedSource','Prepared stage requires an explicit source model.');
model=ModelUtil.create(tag);
cleanupModel=onCleanup(@() ModelUtil.remove(tag)); %#ok<NASGU>
comp=model.component.create('comp1',true);
geom=comp.geom.create('geom1',3); geom.lengthUnit('mm');
rings=oatof_build_accelerator_geometry(geom,numel(g.ring_z_mm),opening,g);
solids=[{'repeller','accelshield'},rings];
for k=1:numel(solids), geom.feature(solids{k}).set('selresult','on'); end
b=domain.pa_bounds_mm;
geom.create('outerbox','Block');
geom.feature('outerbox').set('pos',[b.x_min,b.y_min,b.z_min]);
geom.feature('outerbox').set('size',[b.x_max-b.x_min,b.y_max-b.y_min,b.z_max-b.z_min]);
geom.create('vac','Difference');
geom.feature('vac').selection('input').set({'outerbox'});
geom.feature('vac').selection('input2').set(solids);
geom.feature('vac').set('keepsubtract','on');
geom.feature('vac').set('selresult','on');
roles={'grid1','intermediate2','grid2'};
sheets=repmat(struct('tag','','z','','width','','x','','y',''),1,numel(roles));
for k=1:numel(roles)
    role=roles{k}; width=g.electrode_width_mm;
    if strcmp(role,'grid2'), width=g.shield_inner_width_mm; end
    sheets(k)=struct('tag',['wp_' role],'z',mm(g.([role '_z_mm'])), ...
        'width',mm(width),'x',mm(g.axis_x_mm),'y',mm(g.axis_y_mm));
end
sheetTags=build_accelerator_grids(geom,sheets);
for k=1:numel(sheetTags), geom.feature(sheetTags{k}).set('selresult','on'); end
geom.create('vac_grids','Union');
geom.feature('vac_grids').selection('input').set([{'vac'},sheetTags]);
geom.feature('vac_grids').set('intbnd','on');
geom.run;
vac=comp.selection.create('sel_vac','Explicit'); vac.geom('geom1',3);
vac.set(comp.selection('geom1_vac_dom').entities());
assert(~isempty(vac.entities()),'oatof:PairedVacuum','Vacuum selection is empty.');
adj=comp.selection.create('vac_boundaries','Adjacent');
adj.set('entitydim',3); adj.set('outputdim',2); adj.set('input',{'sel_vac'}); adj.set('interior','on');
allVac=adj.entities(); electrodes=[];
es=comp.physics.create('es','Electrostatics','geom1'); es.selection.named('sel_vac');
mat=comp.material.create('vacuum','Common'); mat.selection.named('sel_vac');
mat.propertyGroup('def').set('relpermittivity','1');
solidIds=[binding.accelerator_repeller_id,binding.grounded_shield_id,binding.accelerator_ring_ids(:).'];
assert(numel(solidIds)==numel(solids),'oatof:PairedElectrodes','Ring binding coverage differs.');
for k=1:numel(solids)
    s=comp.selection.create(['adj_' solids{k}],'Adjacent');
    s.set('entitydim',3); s.set('outputdim',2); s.set('input',{['geom1_' solids{k} '_dom']});
    entities=intersect(s.entities(),allVac);
    electrodes=add_potential(comp,es,solids{k},entities,on_voltage(plan,solidIds(k)),electrodes);
end
for k=1:numel(roles)
    role=roles{k}; entities=intersect(comp.selection(['geom1_' sheetTags{k} '_bnd']).entities(),allVac);
    electrodes=add_potential(comp,es,role,entities,on_voltage(plan,binding.(['accelerator_' role '_id'])),electrodes);
end
outer=setdiff(allVac,electrodes);
assert(~isempty(outer),'oatof:PairedOuter','Artificial outer boundary is empty.');
s=comp.selection.create('sel_outer','Explicit'); s.geom('geom1',2); s.set(outer);
zero=es.create('outer_zero_charge','ZeroCharge',2); zero.selection.named('sel_outer');
mesh=comp.mesh.create('mesh1');
s=comp.selection.create('sel_electrode_mesh','Explicit'); s.geom('geom1',2); s.set(electrodes);
mesh.feature('size').set('hauto',domain.comsol_mesh.global_automatic_level);
localSize=add_comsol_size_feature(mesh,'paired_electrode_size','Prepared electrode-boundary mesh', ...
    'geom1',2,'sel_electrode_mesh',domain.comsol_mesh.electrode_boundary_maximum_element_size_mm);
localSize.set('hgradactive','on'); localSize.set('hgrad',domain.comsol_mesh.electrode_boundary_growth_rate);
% All other local controls inherit the explicit global automatic settings.
for property={'hminactive','hcurveactive','hnarrowactive'}
    localSize.set(property{1},'off');
end
tet=mesh.create('ftet1','FreeTet'); tet.selection.named('sel_vac');
read_mesh_contract(model,plan);
mesh.run;
stats=mesh.stat(); stats.selection().geom('geom1',3).set(int32(vac.entities()));
assert(stats.isComplete() && stats.getNumElem('tet')>0,'oatof:PairedMesh','Selected vacuum mesh incomplete.');
study=model.study.create('std1'); study.create('stat','Stationary');
sol=model.sol.create('sol1'); sol.study('std1'); sol.createAutoSequence('std1'); sol.attach('std1');
modelPath=solve_and_save(model,planPath,outputDir);
facts=export_field_samples(model,plan,planPath,points,outputDir,modelPath);
end

function modelPath=solve_and_save(model,planPath,outputDir)
% Persist the completed geometry, mesh and solver before the expensive solve.
% Reuse one run-local MPH; the native fact always describes its saved stage.
import com.comsol.model.util.*
modelPath=fullfile(outputDir,'paired_accelerator_static.mph');
sol=model.sol('sol1');
assert(sol.isEmpty() && sol.isAttached(),'oatof:PairedPrepared','Empty attached stationary solver required.');
model.study('std1').feature('stat');
comp=model.component('comp1');
stats=comp.mesh('mesh1').stat(); stats.selection().geom('geom1',3).set(int32(comp.selection('sel_vac').entities()));
assert(stats.isComplete() && stats.getNumElem('tet')>0,'oatof:PairedMesh','Selected vacuum mesh incomplete.');
mphsave(model,modelPath);
facts=struct('schema_version',1,'role','oatof_paired_accelerator_static_field_solution', ...
    'status','prepared_saved','plan_path',planPath,'model_path',modelPath,'solution_tag','sol1', ...
    'study_tag','std1','solution_present',false,'mesh_complete',true,'tetrahedra',stats.getNumElem('tet'), ...
    'backend_version',char(ModelUtil.getComsolVersion()));
write_native_facts(fullfile(outputDir,'comsol_field_solution.json'),facts);
% A failed preparation save/fact write propagates before any runAll call.
sol.runAll;
assert(~sol.isEmpty(),'oatof:PairedSolution','Solved stationary solution is empty.');
mphsave(model,modelPath);
facts.status='solved_saved'; facts.solution_present=true;
write_native_facts(fullfile(outputDir,'comsol_field_solution.json'), ...
    facts);
end

function facts=export_field_samples(model,plan,planPath,points,outputDir,modelPath)
% One export implementation for new solves and explicitly restored solutions.
% COMSOL 6.4 model.sol().isEmpty() checks stored data without reading the vector:
% https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.58.html
import com.comsol.model.util.*
comp=model.component('comp1'); vac=comp.selection('sel_vac');
outer=comp.selection('sel_outer').entities();
roles=[{'repeller','accelshield','grid1','intermediate2','grid2'}, ...
    arrayfun(@(k) sprintf('accelring_%d',k),1:numel(plan.accelerator_geometry.ring_z_mm),'UniformOutput',false)];
electrodes=[];
for k=1:numel(roles), electrodes=union(electrodes,comp.selection(['selb_' roles{k}]).entities()); end
stats=comp.mesh('mesh1').stat(); stats.selection().geom('geom1',3).set(int32(vac.entities()));
meshFacts=read_mesh_contract(model,plan);
assert(stats.isComplete() && stats.getNumElem('tet')>0,'oatof:PairedMesh','Selected vacuum mesh incomplete.');
[ex,ey,ez,units]=mphinterp(model,{'es.Ex','es.Ey','es.Ez'}, ...
    'coord',points{:,{'x_mm','y_mm','z_mm'}}.','selection',vac.entities(), ...
    'edim','domain','ext',0,'unit',{'V/m','V/m','V/m'},'matherr','on');
assert(all(isfinite([ex(:);ey(:);ez(:)])) && numel(ex)==height(points) && ...
    all(strcmp(units,'V/m')),'oatof:PairedSamples','Native point coverage/units differ.');
outputPath=fullfile(outputDir,'comsol_field_samples.csv');
write_samples(outputPath,[points{:,:},ex(:),ey(:),ez(:)]);
facts=struct('backend','COMSOL','version',char(ModelUtil.getComsolVersion()), ...
    'plan_path',planPath,'model_path',modelPath,'sample_path',outputPath, ...
    'point_count',height(points),'coordinate_unit','mm','field_unit',{units}, ...
    'vacuum_domain_ids',vac.entities(),'outer_boundary_ids',outer, ...
    'electrode_boundary_ids',electrodes,'mesh_contract',meshFacts,'tetrahedra',stats.getNumElem('tet'), ...
    'claim','Static field samples only; no numerical equivalence tolerance or particle claim.');
write_native_facts(fullfile(outputDir,'comsol_field_native_facts.json'),facts);
end

function facts=read_mesh_contract(model,plan)
% Inspect both newly configured and explicitly restored native models.
comp=model.component('comp1'); mesh=comp.mesh('mesh1'); requested=plan.numerical_domain.comsol_mesh;
globalSize=mesh.feature('size'); localSize=mesh.feature('paired_electrode_size');
level=globalSize.getDouble('hauto');
hmax=model.param.evaluate(char(localSize.getString('hmax')),'mm');
hgrad=localSize.getDouble('hgrad');
assert(strcmp(globalSize.getString('custom'),'off') && level==requested.global_automatic_level && ...
    strcmp(localSize.getString('custom'),'on') && localSize.getBoolean('hmaxactive') && ...
    localSize.getBoolean('hgradactive') && ...
    abs(hmax-requested.electrode_boundary_maximum_element_size_mm)<=8*eps(requested.electrode_boundary_maximum_element_size_mm) && ...
    hgrad==requested.electrode_boundary_growth_rate, ...
    'oatof:PairedMeshContract','Native mesh size settings differ from the prepared contract.');
for property={'hminactive','hcurveactive','hnarrowactive'}
    assert(~localSize.getBoolean(property{1}),'oatof:PairedMeshContract','Unexpected local mesh control.');
end
roles=[{'repeller','accelshield','grid1','intermediate2','grid2'}, ...
    arrayfun(@(k) sprintf('accelring_%d',k),1:numel(plan.accelerator_geometry.ring_z_mm),'UniformOutput',false)];
electrodes=[];
for k=1:numel(roles)
    ids=comp.selection(['selb_' roles{k}]).entities();
    assert(~isempty(ids),'oatof:PairedMeshContract','Electrode boundary group is empty: %s',roles{k});
    electrodes=union(electrodes,ids);
end
selected=comp.selection('sel_electrode_mesh').entities();
assert(isequal(sort(selected(:)),sort(electrodes(:))) && ...
    strcmp(localSize.selection.named(),'sel_electrode_mesh') && ...
    isequal(sort(localSize.selection.entities(2)),sort(electrodes)) && ...
    strcmp(mesh.feature('ftet1').selection.named(),'sel_vac') && ...
    isequal(sort(mesh.feature('ftet1').selection.entities(3)),sort(comp.selection('sel_vac').entities())), ...
    'oatof:PairedMeshContract','Mesh must cover the electrode union and the complete vacuum domain.');
tags=string(cell(mesh.feature.tags()));
assert(isequal(tags(:),["size";"paired_electrode_size";"ftet1"]), ...
    'oatof:PairedMeshContract','Unexpected mesh feature order.');
facts=struct('global_automatic_level',level,'global_growth_rate',globalSize.getDouble('hgrad'), ...
    'global_minimum_element_size_expression',char(globalSize.getString('hmin')), ...
    'geometry_length_unit',char(comp.geom('geom1').lengthUnit()), ...
    'electrode_boundary_maximum_element_size_mm',hmax,'electrode_boundary_growth_rate',hgrad, ...
    'electrode_group_count',numel(roles),'electrode_boundary_ids',selected,'feature_order',{cellstr(tags)});
end

function write_native_facts(outputPath,facts)
fid=fopen(outputPath,'w');
assert(fid>=0,'oatof:PairedOutput','Cannot write native facts.');
closeFile=onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid,'%s\n',jsonencode(facts,PrettyPrint=true));
end

function electrodes=add_potential(comp,es,tag,entities,voltage,electrodes)
assert(~isempty(entities) && isempty(intersect(entities,electrodes)), ...
    'oatof:PairedElectrodes','Empty or overlapping electrode boundary selection: %s',tag);
s=comp.selection.create(['selb_' tag],'Explicit'); s.geom('geom1',2); s.set(entities);
p=es.create(['pot_' tag],'ElectricPotential',2); p.selection.named(['selb_' tag]);
p.set('V0',sprintf('%.17g[V]',voltage));
electrodes=union(electrodes,entities);
end

function value=on_voltage(plan,id)
key=matlab.lang.makeValidName(sprintf('%.0f',id));
value=plan.static_on_electrode_voltages_v.(key);
assert(isscalar(value) && isfinite(value),'oatof:PairedVoltage','Finite declared ON voltage required.');
end

function value=mm(number)
value=sprintf('%.17g[mm]',number);
end

function write_samples(outputPath,values)
fid=fopen(outputPath,'w');
assert(fid>=0,'oatof:PairedOutput','Cannot write native field samples.');
closeFile=onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid,'point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n');
% Preserve the prepared binary64 coordinates for exact shared point identity.
fprintf(fid,'%.0f,%.17g,%.17g,%.17g,%.17g,%.17g,%.17g\n',values.');
end
