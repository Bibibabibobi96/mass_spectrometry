"""Static interface guards; actual ES/handoff regression is separately frozen."""
from pathlib import Path
import re
import unittest


SOURCE = (
    Path(__file__).resolve().parents[2]
    / 'comsol/configure_corridor_reference_electrostatics.m'
).read_text(encoding='utf-8')


class CorridorReferenceElectrostaticsTest(unittest.TestCase):
    def test_boundary_requires_explicit_current_contract(self) -> None:
        self.assertIn('boundaryContract (1,1) struct', SOURCE)
        self.assertIn('validate_boundary_contract(boundaryContract, box);', SOURCE)
        self.assertIn("isequal(contract.schema_version, 1)", SOURCE)
        self.assertIn("case 'donor'", SOURCE)
        self.assertIn("case 'grounded_enclosure'", SOURCE)
        self.assertIn("error('MRTOF:BoundaryMode'", SOURCE)
        self.assertIn('isequal(sort(fieldnames(contract)), sort(expected))', SOURCE)
        self.assertNotIn('boundaryGridDir', SOURCE)

    def test_enclosure_matches_geometry_and_grounds_only_outer_faces(self) -> None:
        self.assertIn('isequal(reshape(contract.box_mm, 1, []), box)', SOURCE)
        self.assertIn('isequal(contract.voltage_v, 0)', SOURCE)
        self.assertIn('if ~donorBoundary && (k <= 5 || ~halfDomain)', SOURCE)
        self.assertIn("es.create(['mrc_outer_ground_', name], 'Ground', 2)", SOURCE)
        self.assertIn('ground.selection.named(selectionTag);', SOURCE)
        self.assertIn('symmetry = faces(6);', SOURCE)
        self.assertIn('faces = faces(1:5);', SOURCE)
        # No donor interpolation is imported in the grounded-enclosure branch.
        interpolation = SOURCE.index("model.func.create(functionTag, 'Interpolation')")
        branch = SOURCE.rfind('if donorBoundary && k <= 5', 0, interpolation)
        self.assertGreaterEqual(branch, 0)

    def test_component_namespace_and_internal_sheet_share_one_potential(self) -> None:
        self.assertIn('componentSolids = geometryOut.component_electrodes;', SOURCE)
        self.assertIn('componentSheets = geometryOut.component_sheets;', SOURCE)
        self.assertIn('componentId = entry.component_electrode_id;', SOURCE)
        self.assertIn('namespace = char(entry.component_namespace);', SOURCE)
        self.assertIn('ids = union(ids, sheetIds);', SOURCE)
        self.assertIn("sprintf('mrc_%s_e%d_potential', namespace, componentId)", SOURCE)
        self.assertIn("sprintf('%.17g[V]', entry.voltage_v)", SOURCE)
        self.assertIn('all(usedSolids) && all(usedSheets)', SOURCE)
        self.assertNotIn('analyzerElectrodeVoltagesV(componentId)', SOURCE)
        self.assertNotIn('local_pa_electrode_id', SOURCE)

    def test_sheet_is_checked_against_internal_not_exterior_vacuum_contacts(self) -> None:
        self.assertIn("allContacts.set('interior', 'on');", SOURCE)
        self.assertIn('isempty(setdiff(selectedIds, vacuumContactIds))', SOURCE)
        self.assertIn('isempty(intersect(selectedIds, vacuumIds))', SOURCE)
        self.assertNotIn('intersect(vacuumIds, selectedIds)', SOURCE)
        self.assertIn("'MRTOF:ComponentContactOverlap'", SOURCE)
        self.assertIn("'MRTOF:DuplicateComponentVoltage'", SOURCE)
        self.assertIn("'MRTOF:UnusedComponentVoltage'", SOURCE)

    def test_numeric_mm_interface_keeps_volts_and_rejects_extrapolation(self) -> None:
        self.assertEqual(re.findall(r"f\.set\('argunit',\s*\{([^}]+)\}\)", SOURCE), ["'1','1'"])
        self.assertEqual(re.findall(r"f\.set\('fununit',\s*\{([^}]+)\}\)", SOURCE), ["'V'"])
        self.assertEqual(re.findall(r"f\.set\('extrap',\s*'([^']+)'\)", SOURCE), ['none'])
        self.assertIn("numericMm = sprintf('(%s)/(1[mm])'", SOURCE)
        self.assertIn('snap_endpoint_expression(numericMm,', SOURCE)
        self.assertIn("functionName, snapped{1}, snapped{2}", SOURCE)

    def test_full_domain_reflects_into_positive_half_grid(self) -> None:
        self.assertIn("{'y,z','abs(x),z','abs(x),z','abs(x),y','abs(x),y','y,z'}", SOURCE)
        self.assertIn('gridLow = [0, box(2:3)];', SOURCE)
        self.assertIn('gridHigh = box(4:6);', SOURCE)
        self.assertIn('argumentAxes = [2,3;1,3;1,3;1,2;1,2;2,3];', SOURCE)
        self.assertIn('functionName = faces(1).function_name;', SOURCE)

    def test_endpoint_snap_is_bounded_and_leaves_interior_unchanged(self) -> None:
        self.assertIn('tolerance = 16 * eps(max([1, abs(low), abs(high)]));', SOURCE)
        self.assertIn('if((%s)<%.17g&&(%s)>=%.17g,%.17g,', SOURCE)
        self.assertIn('if((%s)>%.17g&&(%s)<=%.17g,%.17g,(%s)))', SOURCE)
        self.assertIn('value, low, value, low-tolerance, low,', SOURCE)
        self.assertIn('value, high, value, high+tolerance, high, value', SOURCE)


if __name__ == '__main__':
    unittest.main()
