"""Tests for the MR-TOF local operating-PA cache adapter."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from common.simion.operating_pa_cache import (
    CacheDisposition,
    probe_operating_pa_cache,
    publish_operating_pa_cache,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache import (
    DOWNSTREAM_COORDINATES,
    LOCAL_OUTPUT_NAMES,
    build_local_operating_pa_identity,
    build_local_operating_pa_lane_specs,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class LocalOperatingPACacheTest(unittest.TestCase):
    def test_identity_uses_frozen_receipts_and_voltage_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workbench = root / "workbench"
            outputs = []
            family_manifests = []
            cache_root = root / "cache"
            for family_index, output_name in enumerate(LOCAL_OUTPUT_NAMES):
                source = workbench / "simion" / output_name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"source-{family_index}".encode())
                outputs.append({"path": str(source.resolve()), "bytes": source.stat().st_size,
                                "sha256": file_sha256(source)})
                family_run = root / f"family-{family_index}"
                family_manifest = family_run / "run_manifest.json"
                _write(family_manifest, {"status": "success"})
                family_manifests.append(str(family_manifest))
                prefix = f"family_{family_index}"
                frozen_identity = {
                    "geometry": {"family": family_index}, "gem": {}, "basis_namespace": {},
                    "mesh": {}, "grid_phase": {}, "surface": "none", "simion_identity": {},
                    "refine_policy": {}, "builder_identity": {},
                }
                cache_key = canonical_pa_family_cache_key(frozen_identity)
                generation_id = f"{family_index + 1:064X}"
                generation = cache_root / cache_key / "generations" / generation_id
                records = []
                recipes = []
                for response_index in range(5, 9):
                    response_name = f"{prefix}.response{response_index}.pa"
                    response = generation / response_name
                    response.parent.mkdir(parents=True, exist_ok=True)
                    response.write_bytes(f"response-{family_index}-{response_index}".encode())
                    records.append({"name": response.name, "bytes": response.stat().st_size,
                                    "sha256": file_sha256(response)})
                    recipes.append({
                        "local_id": response_index,
                        "standalone_response_filename": response_name,
                    })
                _write(generation / "cache_manifest.json", {
                    "cache_key": cache_key, "generation_sha256": generation_id,
                    "identity": frozen_identity, "files": records,
                })
                _write(cache_root / cache_key / "current_generation.json", {
                    "cache_key": cache_key, "generation_sha256": generation_id,
                })
                _write(family_run / "results" / "analyzer_local_pa_family_contract.json",
                       {"family_prefix": prefix, "response_recipes": recipes})
                _write(family_run / "results" / "pa_family_cache_identity.json", frozen_identity)
                _write(family_run / "results" / "pa_family_cache_publication.json", {
                    "cache_key": cache_key, "generation_sha256": "F" * 64,
                    "generation_directory": str(root / "deleted-old-generation"),
                })
            _write(workbench / "run_config.json", {
                "mode": "analyzer_local_replacement_workbench",
                "inputs": {
                    "local_family_manifests": family_manifests,
                    "local_operating_pas": [
                        str((workbench / "simion" / name).resolve())
                        for name in LOCAL_OUTPUT_NAMES
                    ],
                },
                "parameters": {"basis_voltage_v": 10000.0},
            })
            _write(workbench / "run_manifest.json", {"status": "success", "outputs": outputs})
            _write(workbench / "inputs" / "two_prism_trial_materialization.json", {
                "stripe_biases_v": [-25.0, 50.0], "prism_voltages_v": [177.0, -179.0],
            })
            implementation = root / "adjust.lua"
            implementation.write_text("-- stable", encoding="utf-8")
            identity = build_local_operating_pa_identity(
                workbench, [-25.5, 51.0, 177.25, -178.75],
                implementation_path=implementation, family_cache_root=cache_root,
            )
            self.assertEqual(len(identity["members"]), 5)
            first = next(
                member for member in identity["members"]
                if member["output_name"] == "local_negative_mirror.pa"
            )
            self.assertIn("base_pa", first)
            self.assertNotIn("source_pa0", first)
            self.assertEqual([item["coordinate"] for item in first["responses"]], list(DOWNSTREAM_COORDINATES))
            self.assertEqual(
                [item["applied_voltage_delta_v"] for item in first["responses"]],
                [-0.5, 1.0, 0.25, 0.25],
            )
            self.assertEqual(first["target_voltage_vector_v"], [-25.5, 51.0, 177.25, -178.75])

            planned_identity, lanes = build_local_operating_pa_lane_specs(
                workbench, [-25.5, 51.0, 177.25, -178.75],
                implementation_path=implementation, family_cache_root=cache_root,
            )
            self.assertEqual(planned_identity, identity)
            self.assertEqual([lane["output_name"] for lane in lanes], list(LOCAL_OUTPUT_NAMES))
            self.assertTrue(all(lane["base_mode"] == "standalone" for lane in lanes))
            self.assertTrue(all(len(lane["responses"]) == 4 for lane in lanes))
            self.assertEqual(
                len({lane["source_family_cache_key"] for lane in lanes}), 5,
            )
            self.assertTrue(all(
                len(lane["source_family_cache_key"]) == 64 for lane in lanes
            ))

            operating_cache = root / "operating-cache"
            self.assertIs(
                probe_operating_pa_cache(operating_cache, identity).disposition,
                CacheDisposition.MISS,
            )
            staged = root / "staged"
            staged.mkdir()
            for name in LOCAL_OUTPUT_NAMES:
                (staged / name).write_bytes(("operating-" + name).encode())
            publication = publish_operating_pa_cache(operating_cache, identity, staged)
            hit = probe_operating_pa_cache(operating_cache, identity)
            self.assertIs(hit.disposition, CacheDisposition.HIT)
            self.assertEqual(hit.cache_key, publication.cache_key)
            corrupt_member = publication.generation_directory / LOCAL_OUTPUT_NAMES[0]
            corrupt_member.chmod(0o666)
            corrupt_member.write_bytes(b"corrupt")
            self.assertIs(
                probe_operating_pa_cache(operating_cache, identity).disposition,
                CacheDisposition.CORRUPT,
            )

            invalid_config = json.loads((workbench / "run_config.json").read_text())
            invalid_config["inputs"]["local_operating_pas"][0] = str(
                (workbench / "simion" / "local_negative_mirror.pa0").resolve()
            )
            _write(workbench / "run_config.json", invalid_config)
            with self.assertRaisesRegex(ValueError, "not a true standalone"):
                build_local_operating_pa_identity(
                    workbench, [-25.5, 51.0, 177.25, -178.75],
                    implementation_path=implementation, family_cache_root=cache_root,
                )


if __name__ == "__main__":
    unittest.main()
