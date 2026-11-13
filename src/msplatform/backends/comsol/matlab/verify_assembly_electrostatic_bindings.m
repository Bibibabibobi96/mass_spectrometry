function verify_assembly_electrostatic_bindings(model,selected,request,keys,values)
% VERIFY_ASSEMBLY_ELECTROSTATIC_BINDINGS Check actual electrostatic feature bindings.
% Caller independently binds selected entities to the frozen geometry report.
comp=model.component('comp1');es=comp.physics('es');mesh=comp.mesh('mesh1');
assert(numel(comp.physics.tags)==1 && numel(model.study.tags)==1,'assembly:Scope','Unexpected physics or study');
assert(same_entities(es.selection.entities(),selected.vacuum_domains),'assembly:Vacuum','Cold physics domain differs');
assert(same_entities(comp.material('vacuum').selection.entities(),selected.vacuum_domains),'assembly:Material','Cold material domain differs');
property=comp.material('vacuum').propertyGroup('def');kind=char(property.getValueType('relpermittivity'));
assert(any(strcmp(kind,{'String','StringArray','StringMatrix'})),'assembly:Material','Unsupported relative permittivity representation: %s',kind);
tensor=string(property.getStringArray('relpermittivity'));
if numel(tensor)==1
    assert(str2double(tensor)==request.relative_permittivity,'assembly:Material','Cold scalar permittivity differs');
else
    assert(numel(tensor)==9,'assembly:Material','Cold tensor must have nine entries');
    numeric=reshape(str2double(tensor),3,3);
    assert(isequal(numeric,eye(3)*request.relative_permittivity),'assembly:Material','Cold full isotropic tensor differs');
end
globalControls=read_comsol_mesh_size_controls(mesh.feature('size'));
if strcmp(globalControls.hauto.type,'String'),level=str2double(globalControls.hauto.value);else,level=globalControls.hauto.value;end
assert(level==request.mesh.global_automatic_level && strcmp(char(globalControls.custom.value),'off'),'assembly:Mesh','Cold global mesh level differs');
stat=model.study('std1').feature('stat');
assert(strcmp(char(stat.type()),'Stationary') && stat.isActive() && stat.solveFor('/physics/es'),'assembly:Study','Cold study type or physics activation differs');
for k=1:numel(keys)
    feature=es.feature(sprintf('assembly_potential_%03d',k));
    assert(feature.isActive() && strcmp(char(feature.selection.named()),sprintf('assembly_group_%03d',k)) && same_entities(feature.selection.entities(2),selected.group_faces{k}),'assembly:Groups','Cold potential feature selection differs');
    assert(strcmp(char(feature.getString('V0')),sprintf('%.17g[V]',values(k))),'assembly:Voltage','Cold voltage differs');
    assert(same_entities(comp.selection(sprintf('assembly_group_%03d',k)).entities(),selected.group_faces{k}),'assembly:Groups','Cold group selection differs');
end
outerFeature=es.feature('assembly_outer_potential');
assert(outerFeature.isActive() && strcmp(char(outerFeature.selection.named()),'assembly_outer_boundary') && same_entities(outerFeature.selection.entities(2),selected.outer_faces),'assembly:Exterior','Cold exterior feature selection differs');
assert(strcmp(char(outerFeature.getString('V0')),sprintf('%.17g[V]',request.exterior.voltage_v)),'assembly:Exterior','Cold exterior differs');
assert(same_entities(comp.selection('assembly_outer_boundary').entities(),selected.outer_faces),'assembly:Exterior','Cold exterior selection differs');
allFaces=[];for k=1:numel(keys),allFaces=union(allFaces,selected.group_faces{k});end
localSize=mesh.feature('assembly_electrode_size');localControls=read_comsol_mesh_size_controls(localSize);
assert(localSize.isActive() && strcmp(char(localControls.custom.value),'on') && localSize.getBoolean('hmaxactive'),'assembly:Mesh','Cold local mesh control inactive');
assert(strcmp(char(localSize.selection.named()),'assembly_electrode_faces') && same_entities(localSize.selection.entities(2),allFaces),'assembly:Mesh','Cold local mesh selection differs');
tet=mesh.feature('ftet1');assert(tet.isActive() && strcmp(char(tet.selection.named()),'assembly_reference_vacuum') && same_entities(tet.selection.entities(3),selected.vacuum_domains),'assembly:Mesh','Cold tetrahedral selection differs');
% Read the saved expression independently of the property's primary value type.
% This is the existing paired-field conversion route; getter/evaluation failures propagate.
actualHmax=model.param.evaluate(char(localSize.getString('hmax')),'mm');
assert(abs(actualHmax-request.mesh.electrode_hmax_mm)<=8*eps(request.mesh.electrode_hmax_mm),'assembly:Mesh','Cold hmax differs');
end

function equal = same_entities(left,right)
a=double(left);b=double(right);equal=isequal(sort(a(:)),sort(b(:)));
end
