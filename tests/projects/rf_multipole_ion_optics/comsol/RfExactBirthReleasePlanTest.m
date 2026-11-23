classdef RfExactBirthReleasePlanTest < matlab.unittest.TestCase
 properties (TestParameter)
  validCase=validCases()
  invalidCase=invalidCases()
 end
 methods (TestClassSetup)
  function addHelperPath(testCase)
   projectRoot=fileparts(fileparts(fileparts(mfilename('fullpath'))));
   testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(projectRoot,'comsol')));
  end
 end
 methods (Test)
  function singletonInventoryTransportsAsJsonArray(testCase)
   inventory=struct('group_index',1,'source_rows',(1:100)','row_count',100,'column_count',6);
   cells=arrayfun(@(entry)entry,inventory,'UniformOutput',false);
   encoded=jsonencode(struct('release_files',{cells}));
   testCase.verifyTrue(contains(encoded,'"release_files":[{'));
  end
  function preservesExactGroupingAndFacts(testCase,validCase)
   [groups,map]=plan_rf_exact_birth_releases(validCase.args{:});
   actual=reconstruct(groups,numel(map));
   testCase.verifyEqual(numel(groups),validCase.count);
   testCase.verifyEqual(map,validCase.map);
   testCase.verifyEqual(actual.birth,validCase.args{1},'AbsTol',0);
   testCase.verifyEqual(actual.state,validCase.args{2},'AbsTol',0);
   testCase.verifyEqual(actual.ids,validCase.args{3});
   testCase.verifyEqual(actual.mass,validCase.args{4},'AbsTol',0);
   testCase.verifyEqual(actual.charge,validCase.args{5});
   testCase.verifyTrue(isequaln(actual.weights,validCase.args{6}));
  end
  function rejectsInvalidInputs(testCase,invalidCase)
   testCase.verifyError(@()plan_rf_exact_birth_releases(invalidCase.args{:}),invalidCase.error);
  end
 end
end
function cases=validCases()
data=reshape(1:24,4,6);ids=[41;7;93;12];mass=100*ones(4,1);charge=-ones(4,1);weights=[0.5;2;3;NaN];
cases.nonAdjacent=struct('args',{{[0.3;0.1;0.3;0.1+eps(0.1)],data,ids,mass,charge,weights}},'count',3,'map',[1;3;2;4]);
cases.allSame=struct('args',{{zeros(4,1),data,ids,mass,charge,weights}},'count',1,'map',(1:4)');
cases.allDifferent=struct('args',{{(1:4)'*eps(1),data,ids,mass,charge,weights}},'count',4,'map',(1:4)');
cases.idBoundary=struct('args',{{zeros(4,1),data,[1;2;3;flintmax],mass,charge,weights}},'count',1,'map',(1:4)');
end
function actual=reconstruct(groups,n)
actual=struct('birth',zeros(n,1),'state',zeros(n,6),'ids',zeros(n,1),'mass',zeros(n,1),'charge',zeros(n,1),'weights',zeros(n,1));
for index=1:numel(groups)
 group=groups(index);rows=group.source_rows;
 actual.birth(rows)=str2double(erase(group.release_time_expression,'[s]'));
 actual.state(rows,:)=reshape(sscanf(group.release_text,'%f'),6,[])';
 actual.ids(rows)=group.particle_ids;actual.mass(rows)=group.mass_amu;actual.charge(rows)=group.charge_state;actual.weights(rows)=group.weights;
end
end
function cases=invalidCases()
base={zeros(2,1),zeros(2,6),[1;2],ones(2,1),ones(2,1),ones(2,1)};
cases.shape=bad(base,2,zeros(2,5),'rf:ReleaseShape');
cases.empty=bad(base,1,[],'rf:ReleaseShape');
cases.stateNaN=bad(base,2,[NaN zeros(1,5);zeros(1,6)],'rf:ReleaseFinite');
cases.birthNaN=bad(base,1,[0;NaN],'rf:ReleaseFinite');
cases.birthNegative=bad(base,1,[0;-eps(1)],'rf:ReleaseFinite');
cases.idZero=bad(base,3,[0;2],'rf:ReleaseIds');
cases.idNegative=bad(base,3,[-1;2],'rf:ReleaseIds');
cases.idFraction=bad(base,3,[1.5;2],'rf:ReleaseIds');
cases.idUnsafe=bad(base,3,[1;flintmax+2],'rf:ReleaseIds');
cases.idDuplicate=bad(base,3,[1;1],'rf:ReleaseIds');
cases.idNaN=bad(base,3,[1;NaN],'rf:ReleaseIds');
cases.idShape=bad(base,3,1,'rf:ReleaseIds');
cases.massMixed=bad(base,4,[1;2],'rf:ReleaseSpecies');
cases.massZero=bad(base,4,[0;0],'rf:ReleaseSpecies');
cases.massNaN=bad(base,4,[1;NaN],'rf:ReleaseSpecies');
cases.chargeMixed=bad(base,5,[1;-1],'rf:ReleaseSpecies');
cases.chargeZero=bad(base,5,[0;0],'rf:ReleaseSpecies');
cases.chargeFraction=bad(base,5,[0.5;0.5],'rf:ReleaseSpecies');
cases.chargeNaN=bad(base,5,[NaN;NaN],'rf:ReleaseSpecies');
cases.weightNegative=bad(base,6,[1;-1],'rf:ReleaseWeights');
cases.weightInf=bad(base,6,[1;Inf],'rf:ReleaseWeights');
cases.weightShape=bad(base,6,1,'rf:ReleaseWeights');
end
function value=bad(base,position,replacement,errorId)
base{position}=replacement;value=struct('args',{base},'error',errorId);
end
