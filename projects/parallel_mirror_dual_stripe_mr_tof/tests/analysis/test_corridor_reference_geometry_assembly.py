"""Static guards for the optional C0 component geometry handoff.

Actual COMSOL geometry/selection qualification remains a separate small-model test.
"""
from pathlib import Path
import unittest


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "comsol/build_corridor_reference_geometry.m"
).read_text(encoding="utf-8")


class CorridorReferenceAssemblyTest(unittest.TestCase):
    def test_tilted_mirror_consumes_world_polygons_and_holes(self) -> None:
        # Runtime classifier and real COMSOL geometry checks remain separate.
        self.assertNotIn("'MRTOF:UnsupportedMirrorConvergence'", SOURCE)
        self.assertEqual(SOURCE.count("tag = tilted_mirror(item);"), 3)
        self.assertIn("tag = extrude(item.x, item.polygon_yz_mm);", SOURCE)
        self.assertIn("holes{n} = extrude(hole.x, hole.polygon_yz_mm);", SOURCE)
        self.assertIn("'MRTOF:MissingMirrorPolygon'", SOURCE)

    def test_old_analyzer_only_entry_and_half_domain_scope_remain_explicit(self) -> None:
        self.assertIn("if nargin < 4\n    assembly = [];\nend", SOURCE)
        self.assertIn("assert(isempty(assembly), 'MRTOF:UnsupportedAssemblyDomain'", SOURCE)
        self.assertIn("out = build_corridor_reference_geometry(geom, resolved, halfBox);", SOURCE)
        self.assertIn("out = struct('electrodes', electrodes, 'vacuum_tag', vacuum", SOURCE)
        self.assertIn("'component_electrodes', componentElectrodes", SOURCE)
        self.assertIn("'component_sheets', componentSheets);", SOURCE)
        self.assertNotIn("out.component_electrodes =", SOURCE)

    def test_oa_coordinates_and_component_ids_are_not_analyzer_ids(self) -> None:
        self.assertIn("assembly.accelerator_resolved_electrodes", SOURCE)
        self.assertIn("assembly.accelerator_iob_origin_mm", SOURCE)
        self.assertIn("reshape(oa.local_to_pa_translation_mm, 1, 3) +", SOURCE)
        self.assertIn("reshape(assembly.accelerator_iob_origin_mm, 1, 3)", SOURCE)
        self.assertIn("component_namespace", SOURCE)
        self.assertIn("local_pa_electrode_id", SOURCE)
        self.assertIn("detectorTag = block(reshape(detector.box, 1, 6));", SOURCE)

    def test_sheets_partition_the_same_vacuum_without_becoming_solids(self) -> None:
        self.assertIn("block(project_box(support.aperture_box_mm, oaOffset))", SOURCE)
        self.assertIn("project_sheet(support.ideal_sheet_mm, oaOffset)", SOURCE)
        self.assertIn("wp = geom.create(tag, 'WorkPlane');", SOURCE)
        self.assertIn("rect = wp.geom.create('sheet', 'Rectangle');", SOURCE)
        self.assertIn("feature.selection('input').set([{vacuum}, sheetTags]);", SOURCE)
        self.assertIn("feature.set('intbnd', 'on');", SOURCE)
        self.assertIn("vacuum = subtract(block(corridorBoxMm), [tags, componentTags], true);", SOURCE)


if __name__ == "__main__":
    unittest.main()
