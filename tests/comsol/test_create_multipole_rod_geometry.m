function test_create_multipole_rod_geometry
%TEST_CREATE_MULTIPOLE_ROD_GEOMETRY Real COMSOL API smoke for round and ellipse rods.
import com.comsol.model.*
import com.comsol.model.util.*
model=ModelUtil.create('MultipoleRodGeometryTest');
cleanup=onCleanup(@() ModelUtil.remove('MultipoleRodGeometryTest')); %#ok<NASGU>
component=model.component.create('comp1',true);
geom=component.geom.create('geom1',3);
geom.lengthUnit('mm');

roundArray.rods=struct('radius_mm',1.2,'center_x_mm',2.0,'center_y_mm',-1.0, ...
    'z_min_mm',0.0,'z_max_mm',4.0);
roundTags=create_multipole_round_rods(geom,roundArray,'round','z',[0 0 0]);
assert(isequal(roundTags,{'round1'}),'Round tag identity changed.');
assert(strcmp(char(geom.feature('round1').getType()),'Cylinder'), ...
    'Default round rods must retain the legacy Cylinder primitive.');

ellipseArray.rods=struct('semi_major_axis_mm',2.0,'semi_minor_axis_mm',0.8, ...
    'major_axis_angle_rad',pi/3,'center_x_mm',-2.5,'center_y_mm',1.5, ...
    'z_min_mm',1.0,'z_max_mm',6.0);
ellipseTags=create_multipole_round_rods(geom,ellipseArray,'ellipse','z',[0 0 0]);
assert(isequal(ellipseTags,{'ellipse1'}),'Ellipse tag identity changed.');
assert(strcmp(char(geom.feature('ellipse1').getType()),'ECone'), ...
    'Explicit ellipse rods must use the governed elliptic-cylinder primitive.');
geom.run;
fprintf('COMSOL_MULTIPOLE_ROD_GEOMETRY=PASS ROUND=CYLINDER ELLIPSE=ECONE\n');
end
