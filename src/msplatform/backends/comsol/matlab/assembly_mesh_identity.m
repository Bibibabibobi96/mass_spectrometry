function result = assembly_mesh_identity(model)
%ASSEMBLY_MESH_IDENTITY Hash complete typed mesh data, never modifying the mesh.
[stats,data]=mphmeshstats(model,'mesh1');
assert(isfield(stats,'types') && isfield(data,'vertex') && isfield(data,'elem') && ...
    isfield(data,'elementity'),'assembly:MeshIdentity','Incomplete mesh data');
types=cellstr(string(stats.types));
assert(~isempty(types) && numel(unique(types))==numel(types) && ...
    iscell(data.elem) && iscell(data.elementity) && ...
    numel(types)==numel(data.elem) && numel(types)==numel(data.elementity), ...
    'assembly:MeshIdentity','Mesh types or connectivity differ');
assert(any(strcmp(types,'tet')) && ~isempty(data.elem{find(strcmp(types,'tet'),1)}), ...
    'assembly:MeshIdentity','Tetrahedral mesh is missing');
assert(isnumeric(data.vertex) && isreal(data.vertex) && size(data.vertex,1)==3 && ~isempty(data.vertex) && ...
    all(isfinite(data.vertex(:))),'assembly:MeshIdentity','Invalid mesh vertices');
md=java.security.MessageDigest.getInstance('SHA-256');
feed_text(md,'assembly-mesh-identity-v1');
feed_array(md,data.vertex);
for k=1:numel(types)
    assert(~isempty(types{k}),'assembly:MeshIdentity','Empty element type');
    e=data.elem{k}; entity=data.elementity{k};
    assert(isnumeric(e) && isreal(e) && all(isfinite(e(:))) && ...
        isnumeric(entity) && isreal(entity) && all(isfinite(entity(:))), ...
        'assembly:MeshIdentity','Invalid mesh connectivity');
    feed_text(md,types{k});feed_array(md,e);feed_array(md,entity);
end
raw=typecast(md.digest(),'uint8');
result=struct('schema_version',1,'role','exact_mesh_identity','sha256',lower(reshape(dec2hex(raw,2).',1,[])), ...
    'types',{types},'vertex_shape',sprintf('%dx%d',size(data.vertex,1),size(data.vertex,2)));
end

function feed_text(md,text)
b=unicode2native(char(text),'UTF-8');feed_array(md,uint8(b));
end

function feed_array(md,a)
allowed={'double','single','uint8','int8','uint16','int16','uint32','int32','uint64','int64'};
assert(any(strcmp(class(a),allowed)),'assembly:MeshIdentity','Unsupported mesh numeric type');
% Prefix each array with a class and shape header; data are hashed in bounded chunks.
header=unicode2native(sprintf('%s:%s;',class(a),sprintf('%d,',size(a))),'UTF-8');
md.update(typecast(uint8(header),'int8'));
chunk=65536;
for first=1:chunk:numel(a)
    last=min(numel(a),first+chunk-1);bytes=typecast(a(first:last),'uint8');
    md.update(typecast(bytes,'int8'));
end
end
