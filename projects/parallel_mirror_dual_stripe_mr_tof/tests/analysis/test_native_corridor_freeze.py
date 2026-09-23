from __future__ import annotations

import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from common.simion.pa_family_cache import publish_pa_family_cache
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    derive_native_corridor_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_freeze import (
    FROZEN_NAMES,
    freeze_native_corridor_inputs,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry import (
    build_native_corridor_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


def _identity(role: str) -> dict[str, object]:
    return {
        "geometry": {"role": role},
        "gem": {"sha256": "a" * 64},
        "basis_namespace": {"ids": [1]},
        "mesh": {"mm_per_gu": [1, 1, 1]},
        "grid_phase": {"origin_mm": [0, 0, 0]},
        "surface": "none",
        "simion_identity": {"release": "fixture", "executable_sha256": "b" * 64},
        "refine_policy": {"mode": "fixture"},
        "builder_identity": {"fixture": "v1"},
    }


class NativeCorridorFreezeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical_plan = derive_native_corridor_plan(CONTRACT)
        cls.canonical_gem = build_native_corridor_gem(CONTRACT)

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_payload = self.root / "source_payload"
        self.source_payload.mkdir()
        self.physical_ids = sorted(
            int(physical)
            for physical, local in self.canonical_plan[
                "physical_to_local_electrode_id"
            ].items()
            if int(local) > 0
        )
        self.basis_paths = []
        for identifier in self.physical_ids:
            path = self.source_payload / f"mrtof_analyzer.response{identifier}.pa"
            path.write_bytes((f"basis-{identifier}" * 3).encode("ascii"))
            self.basis_paths.append(path)
        self.coarse_payload = self.root / "coarse_payload"
        self.coarse_payload.mkdir()
        self.coarse_raw = self.coarse_payload / "mrtof_analyzer.pa#"
        self.coarse_raw.write_bytes(b"coarse-raw-fixture")
        source_publication = publish_pa_family_cache(
            self.root / "source_cache",
            _identity("source"),
            self.source_payload,
            [path.name for path in self.basis_paths],
            recovery_policy="none",
        )
        coarse_publication = publish_pa_family_cache(
            self.root / "coarse_cache",
            _identity("coarse"),
            self.coarse_payload,
            [self.coarse_raw.name],
            recovery_policy="none",
        )
        self.source_manifest = source_publication.generation_directory / "cache_manifest.json"
        self.initial_source_manifest = self.source_manifest
        self.coarse_manifest = coarse_publication.generation_directory / "cache_manifest.json"
        self.basis_paths = [
            source_publication.generation_directory / path.name for path in self.basis_paths
        ]
        self.coarse_raw = coarse_publication.generation_directory / self.coarse_raw.name
        self.simion = self.root / "simion.exe"
        self.simion.write_bytes(b"synthetic-simion")
        self.gem = self.root / "mrtof_analyzer_corridor.gem"
        self.gem.write_text(self.canonical_gem, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _governed_output(self) -> tuple[Path, Path]:
        run = (
            self.root
            / "artifacts"
            / "projects"
            / "parallel_mirror_dual_stripe_mr_tof"
            / "runs"
            / "20260923_120000__build__simion__mrtof-native-corridor-response-bank"
        )
        inputs = run / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        config = {
            "schema_version": 2,
            "run_id": run.name,
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "native_corridor_detached_response_bank",
            "inputs": {},
            "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
            "capacity_ledger_lifecycle": {"schema_version": 1, "enabled": True},
        }
        (run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "status": "checkpoint",
            "run_id": run.name,
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "native_corridor_detached_response_bank",
        }
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run / "run_config.json", inputs / "native_corridor_freeze"

    def _freeze(
        self, output: Path | None = None, run_config: Path | None = None
    ) -> dict[str, object]:
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import (
            native_corridor_freeze as freeze_module,
            native_corridor_geometry as geometry_module,
        )

        if run_config is None:
            run_config, governed_output = self._governed_output()
            output = governed_output if output is None else output
        elif output is None:
            raise AssertionError("explicit governed run config requires an output")

        with (
            patch.object(
                freeze_module,
                "derive_native_corridor_plan",
                return_value=self.canonical_plan,
            ),
            patch.object(
                geometry_module,
                "build_native_corridor_gem",
                return_value=self.canonical_gem,
            ),
        ):
            return freeze_native_corridor_inputs(
                contract_path=CONTRACT,
                source_generation_manifest=self.source_manifest,
                coarse_generation_manifest=self.coarse_manifest,
                simion_executable=self.simion,
                simion_release="SIMION fixture",
                output_directory=output,
                run_config_path=run_config,
                canonical_gem_path=self.gem,
            )

    def test_freeze_is_four_files_and_identical_rerun_is_hit(self) -> None:
        _, output = self._governed_output()
        first = self._freeze(output)
        first_bytes = {name: (output / name).read_bytes() for name in FROZEN_NAMES}
        second = self._freeze(output)
        self.assertEqual(first["disposition"], "published")
        self.assertEqual(second["disposition"], "hit")
        self.assertEqual({item.name for item in output.iterdir()}, set(FROZEN_NAMES))
        self.assertEqual(
            first_bytes, {name: (output / name).read_bytes() for name in FROZEN_NAMES}
        )
        for name in FROZEN_NAMES:
            self.assertEqual((output / name).stat().st_mode & stat.S_IWRITE, 0)
        manifest = json.loads((output / FROZEN_NAMES[-1]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["role"], "mrtof_native_corridor_frozen_inputs")
        self.assertEqual(len(manifest["files"]), 3)
        self.assertEqual(
            sorted(record["name"] for record in manifest["files"]),
            sorted(FROZEN_NAMES[:3]),
        )
        recipe = json.loads((output / FROZEN_NAMES[2]).read_text(encoding="utf-8"))
        self.assertEqual(len(recipe["response_recipes"]), 8)
        self.assertEqual(recipe["response_recipes"][0]["physical_ids"], [2, 7])
        self.assertEqual(recipe["response_recipes"][-1]["physical_ids"], [17])

    def test_freeze_never_hashes_large_pa_payloads(self) -> None:
        from common.simion import pa_family_cache as cache_module
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import (
            native_corridor_freeze as module,
            native_corridor_identity as identity,
        )

        original = module.file_sha256

        def guarded(path: Path) -> str:
            if Path(path).suffix.lower().startswith(".pa") or Path(path).name.endswith(".pa#"):
                raise AssertionError("freeze must not hash PA payloads")
            return original(path)

        with (
            patch.object(module, "file_sha256", side_effect=guarded),
            patch.object(cache_module, "file_sha256", side_effect=guarded),
            patch.object(identity, "file_sha256", side_effect=guarded),
        ):
            result = self._freeze()
        self.assertEqual(result["disposition"], "published")

    def _replace_source_generation(self, names: list[str]) -> None:
        payload = self.root / ("variant_" + str(len(list(self.root.glob("variant_*")))))
        payload.mkdir()
        for name in names:
            (payload / name).write_bytes(name.encode("ascii"))
        publication = publish_pa_family_cache(
            self.root / (payload.name + "_cache"),
            _identity(payload.name),
            payload,
            names,
            recovery_policy="none",
        )
        self.source_manifest = publication.generation_directory / "cache_manifest.json"

    def test_missing_extra_and_wrong_source_response_ids_fail(self) -> None:
        canonical_names = [path.name for path in self.basis_paths]
        cases = (
            (canonical_names[:-1], "missing="),
            (canonical_names + ["mrtof_analyzer.response20.pa"], "extra="),
            (canonical_names[:-1] + ["wrong-name.pa"], "non-response member"),
        )
        for index, (names, message) in enumerate(cases):
            with self.subTest(case=index):
                self._replace_source_generation(names)
                _, output = self._governed_output()
                with self.assertRaisesRegex(CandidateContractError, message):
                    self._freeze(output)
                self.assertFalse(output.exists())

    def test_existing_nonidentical_freeze_fails_closed(self) -> None:
        _, output = self._governed_output()
        self._freeze(output)
        target = output / FROZEN_NAMES[0]
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        target.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(CandidateContractError, "differs"):
            self._freeze(output)

    def test_rejects_arbitrary_or_incomplete_artifact_scope_before_writing(self) -> None:
        run_config, output = self._governed_output()
        for target, message in (
            (self.root / "arbitrary", "pre-registered response-bank input range"),
            (self.root / "artifacts" / "projects" / "parallel_mirror_dual_stripe_mr_tof" / "cache" / "native_corridor_frozen_inputs" / "new", "pre-registered response-bank input range"),
        ):
            with self.subTest(target=target):
                with self.assertRaisesRegex(CandidateContractError, message):
                    self._freeze(target, run_config)
                self.assertFalse(target.exists())
        config = json.loads(run_config.read_text(encoding="utf-8"))
        config.pop("capacity_ledger_lifecycle")
        run_config.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(CandidateContractError, "owner, lifecycle, and checkpoint closure"):
            self._freeze(output, run_config)
        self.assertFalse(output.exists())

    def test_failed_attempt_leaves_no_output_and_replay_publishes_once(self) -> None:
        _, output = self._governed_output()
        self._replace_source_generation(["wrong-name.pa"])
        with self.assertRaisesRegex(CandidateContractError, "non-response member"):
            self._freeze(output)
        self.assertFalse(output.exists())
        self.source_manifest = self.initial_source_manifest
        first = self._freeze(output)
        second = self._freeze(output)
        self.assertEqual(first["disposition"], "published")
        self.assertEqual(second["disposition"], "hit")


if __name__ == "__main__":
    unittest.main()
