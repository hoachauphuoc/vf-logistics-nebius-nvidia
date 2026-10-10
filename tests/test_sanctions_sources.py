"""
The official-list parsers: OFAC SDN and the UN Security Council Consolidated List.

The fixtures in tests/fixtures/sanctions are real rows cut from the published files
on 2026-10-10, not hand-written ones, because the failure these parsers are most
likely to have is a disagreement with the actual layout -- a column off by one, an
encoding, the trailing SUB byte OFAC appends -- and a fixture written from the
documentation would share the misunderstanding.

What they pin, in the order a regression would hurt:

  * a designated company is found by name, by a declarant's punctuation of that
    name, by its former name, and by the registration number OFAC buries in the
    remarks;
  * vessels and aircraft never become screenable rows;
  * short aliases are dropped, because exact matching on "COIBA" or "ADF" would
    hold every shipment from any company whose name normalises to it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

from vf_logistics import sanctions, sanctions_sources as ss

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "sanctions"


def _ofac() -> list[dict]:
    return ss.parse_ofac(
        *(FIXTURES.joinpath(n).read_bytes().decode("latin-1") for n in ("sdn.csv", "alt.csv", "add.csv"))
    )


def _un() -> tuple[list[dict], str | None]:
    return ss.parse_un(FIXTURES.joinpath("un.xml").read_bytes())


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["entity_id"]: r for r in rows}


class TestOfacParser(unittest.TestCase):
    def test_entities_and_individuals_are_kept_and_the_vessel_is_not(self):
        ids = set(_by_id(_ofac()))
        self.assertEqual(ids, {"OFAC-SDN-540", "OFAC-SDN-2674", "OFAC-SDN-35036"})
        self.assertNotIn("OFAC-SDN-4238", ids, "MAR AZUL is a vessel, not a counterparty")

    def test_the_registration_number_in_the_remarks_becomes_an_identifier(self):
        row = _by_id(_ofac())["OFAC-SDN-35036"]
        self.assertEqual(row["name"], "ALEXSONG PTE LTD")
        self.assertEqual(row["identifiers"], ["199104462G"])
        self.assertEqual(row["programs"], ["RUSSIA-EO14024"])
        self.assertEqual(row["countries"], ["Singapore"])
        self.assertEqual(row["source"], "ofac_sdn")
        self.assertIn("CHAMPION WAY PTE LTD", row["aliases"], "the former name is an alias")

    def test_an_individual_reads_first_name_first(self):
        row = _by_id(_ofac())["OFAC-SDN-2674"]
        self.assertEqual(row["name"], "Abu ABBAS")
        self.assertEqual(row["kind"], "person")
        self.assertIn("Muhammad ZAYDAN", row["aliases"])
        self.assertIn("ABBAS, Abu", row["aliases"], "the published order still matches")

    def test_a_short_alias_is_dropped(self):
        row = _by_id(_ofac())["OFAC-SDN-540"]
        self.assertNotIn("COIBA", row["aliases"])

    def test_empty_input_is_an_empty_list_not_an_error(self):
        self.assertEqual(ss.parse_ofac(""), [])


class TestUnParser(unittest.TestCase):
    def test_reference_numbers_names_and_the_generation_date(self):
        rows, generated = _un()
        by_id = _by_id(rows)
        self.assertEqual(generated, "2026-10-09T23:00:05.576Z")
        self.assertEqual(by_id["UN-CDi.001"]["name"], "ERIC BADEGE")
        self.assertEqual(by_id["UN-CDi.001"]["kind"], "person")
        self.assertEqual(by_id["UN-CDe.001"]["programs"], ["DRC"])
        self.assertEqual(by_id["UN-CDe.001"]["source"], "un_sc_consolidated")

    def test_long_aliases_are_kept_and_short_ones_are_not(self):
        row = _by_id(_un()[0])["UN-CDe.001"]
        self.assertIn("Allied Democratic Forces", row["aliases"])
        self.assertNotIn("ADF", row["aliases"])


class TestScreeningAgainstTheOfficialIndex(unittest.TestCase):
    """The parsed rows, loaded the way production loads them, against a shipment."""

    def setUp(self):
        rows = _ofac() + _un()[0]
        self.index = sanctions.SanctionsIndex(
            {"version": 1, "source": "OFAC SDN + UN SC Consolidated"},
            sanctions._entities_from_payload({"entities": rows}),
        )

    def _screen(self, **shipment) -> dict:
        return self.index.screen(shipment)

    def test_a_declarant_spelling_of_the_designated_name_is_a_hit(self):
        result = self._screen(receiver_company="Alexsong Pte. Ltd.")
        self.assertEqual(result["status"], sanctions.HIT)
        self.assertEqual(result["matches"][0]["entity_id"], "OFAC-SDN-35036")
        self.assertEqual(result["matches"][0]["risk_level"], "CRITICAL")

    def test_the_former_name_and_the_registration_number_are_hits(self):
        self.assertEqual(self._screen(shipper_company="Champion Way Pte Ltd")["status"], sanctions.HIT)
        result = self._screen(receiver_company="Unrelated Name", receiver_tax_id="199104462G")
        self.assertEqual(result["matches"][0]["matched_on"], "identifier")

    def test_the_same_legal_form_in_another_language_still_matches(self):
        """
        OFAC writes "LLC TESTKOMPLEKT" (OFAC-SDN-41958); a Russian invoice says
        "OOO Testkomplekt". Before OOO was a known legal form the two keys
        differed and the designated buyer screened CLEAN under its own name.
        """
        index = sanctions.SanctionsIndex({}, sanctions._entities_from_payload({"entities": [
            {"entity_id": "OFAC-SDN-41958", "name": "LLC TESTKOMPLEKT", "topics": ["sanction"]},
            {"entity_id": "UN-X", "name": "SUNTRONIC FZE", "topics": ["sanction"]},
        ]}))
        for declared in ("OOO Testkomplekt", "Testkomplekt LLC", "ooo  testkomplekt."):
            with self.subTest(declared=declared):
                self.assertEqual(index.screen({"receiver_company": declared})["status"], sanctions.HIT)
        self.assertEqual(index.screen({"receiver_company": "Suntronic FZCO"})["status"], sanctions.HIT)

    def test_an_ordinary_counterparty_is_clean(self):
        result = self._screen(
            shipper_company="Truong Hai Trading Co", receiver_company="Pacific Sourcing Pte Ltd",
        )
        self.assertEqual(result["status"], sanctions.CLEAN)
        self.assertEqual(result["snapshot"]["source"], "OFAC SDN + UN SC Consolidated")


class TestBuildOfficial(unittest.TestCase):
    """refresh_sanctions.build_official, run against the fixtures instead of the network."""

    @staticmethod
    def _module():
        path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "refresh_sanctions.py"
        spec = importlib.util.spec_from_file_location("_refresh_sanctions_official", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_refresh_sanctions_official"] = module
        spec.loader.exec_module(module)
        return module

    def test_the_payload_names_both_lists_and_their_terms(self):
        payload = self._module().build_official(str(FIXTURES))
        meta = payload["meta"]
        self.assertEqual(meta["source"], "OFAC SDN + UN SC Consolidated")
        self.assertEqual(meta["entity_count"], 5)
        self.assertEqual(meta["lists"]["ofac_sdn"]["records"], 3)
        self.assertEqual(meta["lists"]["un_sc_consolidated"]["generated"], "2026-10-09T23:00:05.576Z")
        self.assertNotIn("NC", meta["licence"], "no non-commercial licence on the official lists")
        self.assertTrue(meta["synced_at"])

    def test_a_missing_list_refuses_rather_than_publishing_half(self):
        module = self._module()
        empty_un = b'<?xml version="1.0"?><CONSOLIDATED_LIST><INDIVIDUALS/><ENTITIES/></CONSOLIDATED_LIST>'
        real_fetch = module._fetch

        def fetch(url, local_dir, filename):
            return empty_un if filename == "un.xml" else real_fetch(url, local_dir, filename)

        module._fetch = fetch
        with self.assertRaises(RuntimeError):
            module.build_official(str(FIXTURES))

    def test_the_built_payload_loads_as_a_production_index(self):
        payload = self._module().build_official(str(FIXTURES))
        index = sanctions.SanctionsIndex(payload["meta"], sanctions._entities_from_payload(payload))
        self.assertEqual(len(index), 5)
        self.assertEqual(index.source, "OFAC SDN + UN SC Consolidated")
        self.assertIsNotNone(index.age_days())


if __name__ == "__main__":
    unittest.main()
