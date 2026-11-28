"""Compiled-input identity and freshness checks for the real Python entry."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from msplatform.backends.comsol.wehnelt_model import (
    COMPILED_INPUT_PATHS,
    load_compiled_wehnelt_inputs,
    resolve_wehnelt_build_request,
)
from msplatform.io.manifest_records import file_record

REPO = Path(__file__).resolve().parents[3]
PROJECT = REPO / "src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun"


def write_compiled_inputs(root: Path, *, stale_resolved: bool = False) -> Path:
    private = root / "compiled"
    records = []
    for name, relative in COMPILED_INPUT_PATHS.items():
        target = private / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, target)
        if name == "resolved_contract" and stale_resolved:
            resolved = json.loads(target.read_text(encoding="utf-8"))
            resolved["role"] = "stale_resolved_contract"
            target.write_text(json.dumps(resolved), encoding="utf-8")
        records.append(dict(file_record(target), name=name, relative_path=relative))
    bundle = root / "resolved_inputs.json"
    bundle.write_text(json.dumps(dict(
        schema_version=1,
        role="compiled_execution_inputs",
        project_id=PROJECT.name,
        root=str(private),
        files=records,
    )), encoding="utf-8")
    return bundle


class BuildInputAdmissionTests(unittest.TestCase):
    def test_compiled_inputs_match_canonical_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = write_compiled_inputs(Path(temporary))
            baseline, modes, count = load_compiled_wehnelt_inputs(bundle)
            expected = resolve_wehnelt_build_request(
                baseline, modes, mode_id="build_only_smoke", evidence_particle_count=count,
            )
            self.assertEqual(count, 1)
            self.assertEqual(expected["selected_mode_id"], "build_only_smoke")
            self.assertEqual(expected["numerical"]["execution_mode"], "build_only")

    def test_stale_resolved_contract_blocks_public_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = write_compiled_inputs(Path(temporary), stale_resolved=True)
            with self.assertRaisesRegex(ValueError, "resolved contract differ"):
                load_compiled_wehnelt_inputs(bundle)

    def test_changed_compiled_bytes_fail_identity_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = write_compiled_inputs(root)
            with (root / "compiled/config/baseline.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(AssertionError, "changed"):
                load_compiled_wehnelt_inputs(bundle)

    def test_missing_compiled_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = write_compiled_inputs(root)
            document = json.loads(bundle.read_text(encoding="utf-8"))
            document["files"] = [row for row in document["files"] if row["name"] != "baseline"]
            bundle.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "baseline"):
                load_compiled_wehnelt_inputs(bundle)


if __name__ == "__main__":
    unittest.main()
