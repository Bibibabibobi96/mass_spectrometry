function result = test_assembly_electrostatic_bindings(modelPath, requestPath, reopenGeometryReportPath)
% Test the production verifier on one saved, unsolved Assembly model.
% Caller freezes and verifies the exact production verifier and all three inputs.
% No model save, mesh build, Compute, particle source or solver is performed.
arguments
    modelPath (1,:) char
    requestPath (1,:) char
    reopenGeometryReportPath (1,:) char
end
import com.comsol.model.util.*
request=jsondecode(fileread(requestPath));
selected=jsondecode(fileread(reopenGeometryReportPath));
keys=cellstr(string(selected.group_keys(:))).';
rows=request.group_voltages;
if isstruct(rows),rows=num2cell(rows);end
assert(numel(keys)==50 && numel(rows)==50 && numel(unique(keys))==50, ...
    'assembly:QAInput','The full unique 50-group authority is required');
assert(iscell(selected.group_faces) && numel(selected.group_faces)==numel(keys), ...
    'assembly:QAInput','Frozen group-face selection representation differs');
values=zeros(1,numel(keys));used=false(1,numel(keys));
for k=1:numel(rows)
    row=rows{k};key=[char(row.instance_id) '/' char(row.electrode_group_id)];
    index=find(strcmp(keys,key));
    assert(numel(index)==1 && ~used(index) && isfinite(row.voltage_v), ...
        'assembly:QAInput','Group voltage identity is missing, duplicated or invalid');
    values(index)=row.voltage_v;used(index)=true;
end
assert(all(used),'assembly:QAInput','Group voltage coverage differs');
assert(isfinite(request.mesh.electrode_hmax_mm) && request.mesh.electrode_hmax_mm==5, ...
    'assembly:QAInput','This test requires the explicit 5 mm request');
model=mphload(modelPath,'AssemblyBindingNativeQA');
cleanupModel=onCleanup(@() ModelUtil.remove('AssemblyBindingNativeQA'));
assert(isempty(model.sol.tags),'assembly:QAInput','Saved model already contains a solution');
% Test the complete cold-saved model before changing any in-memory feature.
verify_assembly_electrostatic_bindings(model,selected,request,keys,values);
mesh=model.component('comp1').mesh('mesh1');
sizeFeature=mesh.feature('assembly_electrode_size');
sizeFeature.set('hmax','0.005[m]');
verify_assembly_electrostatic_bindings(model,selected,request,keys,values);
sizeFeature.set('hmax','7[mm]');
caught=false;
try
    verify_assembly_electrostatic_bindings(model,selected,request,keys,values);
catch error
    if ~strcmp(error.identifier,'assembly:Mesh') || ~strcmp(error.message,'Cold hmax differs')
        rethrow(error);
    end
    caught=true;
end
assert(caught,'assembly:QANegative','Changed 7 mm hmax did not produce the exact required refusal');
assert(isempty(model.sol.tags),'assembly:QAInput','Unexpected solution created');
result=struct('status','success','scope','saved_assembly_verifier_native_qa', ...
    'group_count',numel(keys),'saved_model_accepted',true,'equivalent_005m_accepted',true, ...
    'changed_7mm_refusal_identifier','assembly:Mesh','changed_7mm_refusal_message','Cold hmax differs', ...
    'source_saved',false,'mesh_runs',0,'compute_calls',0,'scientific_qualification',false);
end
