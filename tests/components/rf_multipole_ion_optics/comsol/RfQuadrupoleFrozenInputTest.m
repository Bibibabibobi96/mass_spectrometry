classdef RfQuadrupoleFrozenInputTest < matlab.unittest.TestCase
 properties (TestParameter)
  invalid=struct('legacy1','schema1','legacy2','schema2','future','schema99', ...
   'role','role','identity','identity','rods','rods','rodRadius','radius','exitFace','face','census','census');
  missingGui=struct('noConfig','config','noDesign','design','noInterface','interface');
 end
 methods (TestClassSetup)
  function publicInputs(testCase)
   root=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(root));
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   gui=fileread(fullfile(root,'workflows','interface_readiness','comsol','verify_nocollision_comsol.m'));
   stop=strfind(gui,'g = contract.geometry_mm;');assert(isscalar(stop));
   helper=['function [contract,interface]=readFrozenGuiInputs()' newline gui(1:stop-1) newline 'end' newline];
   writeText(fullfile(folder.Folder,'readFrozenGuiInputs.m'),helper);
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(folder.Folder));
   testCase.addTeardown(@clearGuiHelper);
  end
 end
 methods (Test)
  function actualSchema3PreservesOriginalPhysicalFields(testCase)
   path=fixturePath('interface_resolved_schema3.json');
   actual=load_rf_quadrupole_contract(path);original=jsondecode(fileread(path));
   testCase.verifyEqual(actual,original);
   testCase.verifyEqual(actual.schema_version,3,'AbsTol',0);
   testCase.verifyEqual(actual.identity.electrode_count,4,'AbsTol',0);
  end
  function unsupportedSchemasAndPhysicalMismatchesFail(testCase,invalid)
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   [document,identifier]=invalidDocument(invalid);
   path=fullfile(folder.Folder,'resolved.json');writeText(path,jsonencode(document));
   testCase.verifyError(@()load_rf_quadrupole_contract(path),identifier);
  end
  function guiReadsExactFrozenDesignAndInterfaceBeforeCommercialCalls(testCase)
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   request=guiRequest();requestPath=fullfile(folder.Folder,'run_config.json');writeText(requestPath,jsonencode(request));
   prior=getenv('RFQUAD_RUN_CONFIG');testCase.addTeardown(@()setenv('RFQUAD_RUN_CONFIG',prior));setenv('RFQUAD_RUN_CONFIG',requestPath);
   [contract,interface]=readFrozenGuiInputs();
   testCase.verifyEqual(contract,jsondecode(fileread(request.inputs.resolved_design)));
   testCase.verifyEqual(interface,jsondecode(fileread(request.inputs.interface_contract)));
  end
  function guiMissingFrozenInputRejectsBeforeCommercialCalls(testCase,missingGui)
   folder=testCase.applyFixture(matlab.unittest.fixtures.TemporaryFolderFixture);
   requestPath=missingGuiRequest(folder.Folder,missingGui);
   prior=getenv('RFQUAD_RUN_CONFIG');testCase.addTeardown(@()setenv('RFQUAD_RUN_CONFIG',prior));setenv('RFQUAD_RUN_CONFIG',requestPath);
   testCase.verifyError(@()readFrozenGuiInputs(),'rfquad:GuiFrozenInputs');
  end
 end
end
function path=fixturePath(name)
path=fullfile(fileparts(mfilename('fullpath')),'fixtures',name);
end
function request=guiRequest()
request=struct('role','rf_quadrupole_comsol_run_config','project','rf_multipole_ion_optics', ...
 'workflow_id','transport_interface_readiness','inputs',struct( ...
 'resolved_design',fixturePath('interface_resolved_schema3.json'),'interface_contract',fixturePath('interface_contract.json')));
end
function path=missingGuiRequest(folder,kind)
request=guiRequest();path=fullfile(folder,'run_config.json');
switch kind
 case 'config',path=fullfile(folder,'absent.json');return
 case 'design',request.inputs.resolved_design=fullfile(folder,'absent_design.json');
 case 'interface',request.inputs.interface_contract=fullfile(folder,'absent_interface.json');
end
writeText(path,jsonencode(request));
end
function [d,id]=invalidDocument(kind)
d=jsondecode(fileread(fixturePath('interface_resolved_schema3.json')));id='rfquad:ResolvedDerivation';
switch kind
 case 'schema1',d.schema_version=1;id='rfquad:ResolvedSchema';
 case 'schema2',d.schema_version=2;id='rfquad:ResolvedSchema';
 case 'schema99',d.schema_version=99;id='rfquad:ResolvedSchema';
 case 'role',d.role='unknown';id='rfquad:ResolvedSchema';
 case 'identity',d.identity.radial_order_n=3;id='rfquad:ResolvedIdentity';
 case 'rods',d.geometry_mm.rod_array.rods=d.geometry_mm.rod_array.rods(1:3);id='rfquad:ResolvedRodArray';
 case 'radius',d.geometry_mm.rod_array.inscribed_radius_r0=d.geometry_mm.rod_array.inscribed_radius_r0+0.1;
 case 'face',d.interfaces_mm.exit.aperture_plate_upstream_face_z_mm=d.interfaces_mm.exit.aperture_plate_upstream_face_z_mm+0.1;
 case 'census',d.interfaces_mm.exit.census_plane_z_mm=d.interfaces_mm.exit.census_plane_z_mm+0.1;
end
end
function writeText(path,text)
f=fopen(path,'w','n','UTF-8');assert(f>=0);cleanup=onCleanup(@()fclose(f));fprintf(f,'%s',text);
end
function clearGuiHelper()
clear readFrozenGuiInputs
end
