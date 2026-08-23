from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from common.integration.resolve_connection import load_connection_profile_registry
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    SCREENING_SOURCE_COLUMNS,
    validate_connector_gap_screen_campaign,
    write_pulse_resolution_screening_prefix,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = REPO_ROOT / (
    "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
CAMPAIGN_PATH = INTEGRATION_ROOT / (
    "docs/history/retired_campaigns/connector_gap_three_zone_real_pa_first100_n100_campaign.json"
)
REGISTRY_PATH = INTEGRATION_ROOT / "config/connection_profiles.json"


class ConnectorGapCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = current_campaign_fixture(
            json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        )
        self.registry = load_connection_profile_registry(REGISTRY_PATH)

    def test_campaign_schema_and_cross_row_contract_pass(self) -> None:
        validate_schema(
            self.campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        validate_connector_gap_screen_campaign(self.campaign, self.registry)
        rows = self.campaign["experiments"]
        self.assertEqual(
            [row["connector_gap_evidence_role"] for row in rows],
            ["primary", "primary", "primary", "primary", "stress_report_only"],
        )
        self.assertEqual(
            {row["source"]["particle_source"]["sha256"] for row in rows},
            {"302C03DC29737CE9D46EB1A8D258DB2A8D3C0F8B6A53F7702A33B1ECF9D5320D"},
        )
        self.assertTrue(all(row["source_release_mode"] == "continuous_frontend" for row in rows))
        self.assertTrue(all("pre_pulse_source_state" not in row for row in rows))

    def test_cross_row_contract_rejects_scientific_or_population_drift(self) -> None:
        mutations = []
        source = copy.deepcopy(self.campaign)
        source["experiments"][1]["source"]["particle_source"]["sha256"] = "A" * 64
        mutations.append(source)
        population = copy.deepcopy(self.campaign)
        population["experiments"][2]["single_flight_population"][
            "execution_population"
        ]["ordered_particle_id_sha256"] = "B" * 64
        mutations.append(population)
        denominator = copy.deepcopy(self.campaign)
        denominator["experiments"][3]["single_flight_population"]["denominators"][
            "population_count"
        ] = 99
        mutations.append(denominator)
        field = copy.deepcopy(self.campaign)
        field["experiments"][1]["single_flight_accelerator_field_profile_id"] = (
            "accelerator_real_pa"
        )
        mutations.append(field)
        role = copy.deepcopy(self.campaign)
        role["experiments"][4]["connector_gap_evidence_role"] = "primary"
        mutations.append(role)
        for mutated in mutations:
            with self.subTest(mutated=mutated):
                with self.assertRaises(ContractError):
                    validate_connector_gap_screen_campaign(mutated, self.registry)

    def test_cross_row_contract_rejects_profile_length_drift(self) -> None:
        registry = copy.deepcopy(self.registry)
        target = next(
            profile for profile in registry["profiles"]
            if profile["connection_profile_id"].endswith("gap_6p4mm")
        )
        target["connector"]["length_mm"] = 6.5
        with self.assertRaisesRegex(ContractError, "registration and length differ"):
            validate_connector_gap_screen_campaign(self.campaign, registry)

    def test_existing_prefix_writer_materializes_exact_first_100(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mother.csv"
            output = root / "prefix.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=SCREENING_SOURCE_COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                for particle_id in range(1, 1001):
                    writer.writerow({
                        "particle_id": particle_id,
                        "birth_time_s": 0,
                        "x_mm": 0,
                        "y_mm": 0,
                        "z_mm": 0,
                        "vx_m_s": 1,
                        "vy_m_s": 0,
                        "vz_m_s": 0,
                        "mass_amu": 100,
                        "charge_state": 1,
                    })
            write_pulse_resolution_screening_prefix(
                source, output, ordered_particle_ids=list(range(1, 101))
            )
            with output.open(encoding="utf-8", newline="") as handle:
                ids = [int(row["particle_id"]) for row in csv.DictReader(handle)]
            self.assertEqual(ids, list(range(1, 101)))
            self.assertEqual(
                hashlib.sha256(output.read_bytes()).hexdigest().upper(),
                "899299CDE68F14EB50567E5B2ADD4605CD1399C0C5D4E8482D8F312F0CCA5570",
            )


if __name__ == "__main__":
    unittest.main()
