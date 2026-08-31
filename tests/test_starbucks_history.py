import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from starbucks_history import _merge, _report_groups, api_visits, merge_history, parse_report


class StarbucksHistoryTests(unittest.TestCase):
    def test_report_groups_flush_rows_at_boundaries(self):
        observations = [
            {"kind": "purchase_item", "occurred_at": "2026-01-01 10:00:00", "store_key": "one"},
            {"kind": "purchase_item", "occurred_at": "2026-01-01 10:00:00", "store_key": "one"},
            {"kind": "account_activity", "occurred_at": "2026-01-01 10:01:00", "store_key": ""},
            {"kind": "purchase_item", "occurred_at": "2026-01-01 11:00:00", "store_key": "two"},
        ]

        groups = list(_report_groups(observations))

        self.assertEqual([len(group["rows"]) for group in groups], [2, 1])
        self.assertEqual(groups[0]["signature"], ("2026-01-01 10:00:00", "one"))
        self.assertEqual(groups[1]["signature"], ("2026-01-01 11:00:00", "two"))

    def test_parse_report_preserves_store_and_local_second(self):
        report = """Purchase Transactions,
Date/Time,Store Name,Order Total Charged,Item Name
2026-01-01 10:00:00,Bayview & Romfield,5.00,Coffee
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt") as source:
            source.write(report)
            source.flush()
            _, _, visits = parse_report(Path(source.name), "ca_customer_information_report", "CAD")

        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["store"]["name_raw"], "Bayview & Romfield")
        self.assertEqual(visits[0]["local_second"], "2026-01-01 10:00:00")

    def test_merge_reconciles_unique_close_api_visit(self):
        report = self._visit("2026-01-01 10:00:00", "ca_customer_information_report")
        api = self._visit("2026-01-01 10:00:10", "api_export", time_basis="utc")

        merged = _merge([report, api])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_kinds"], ["api_export", "ca_customer_information_report"])

    def test_merge_does_not_reconcile_ambiguous_close_orders(self):
        first = self._visit("2026-01-01 10:00:00", "ca_customer_information_report")
        second = self._visit("2026-01-01 10:00:10", "ca_customer_information_report")
        api = self._visit("2026-01-01 10:00:05", "api_export", time_basis="utc")

        merged = _merge([first, second, api])

        self.assertEqual(len(merged), 3)

    def test_merge_history_preserves_dictionary_store_metadata(self):
        visit = self._visit("2026-01-01 10:00:00", "api_export", time_basis="utc")
        visit["store"].update({
            "catalog_store_number": "12345-67890",
            "in_gta_catalog": True,
            "standalone": True,
            "region": "Toronto",
            "match_method": "store_number",
        })
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump({"visits": [visit], "observations": [], "stars": []}, source)
            source.flush()

            merge_history(Path(source.name), [])
            canonical = json.loads(Path(source.name).read_text())["visits"][0]

        self.assertEqual(canonical["store"], visit["store"])
        self.assertNotIn("amount_order_total", canonical)

    def test_merge_history_preserves_existing_time_basis(self):
        visit = self._visit("2026-01-01 10:00:00", "api_export", time_basis="local_wall")
        visit["source_kinds"] = ["api_export", "ca_customer_information_report"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump({"visits": [visit], "observations": [], "stars": []}, source)
            source.flush()

            merge_history(Path(source.name), [])
            canonical = json.loads(Path(source.name).read_text())["visits"][0]

        self.assertEqual(canonical["time_basis"], "local_wall")

    def test_api_visits_omits_missing_order_total(self):
        receipt = {
            "historyId": "receipt-1",
            "date": "2026-01-01T15:00:00Z",
            "storeName": "Bayview & Romfield",
            "purchasedItems": [{"name": "Coffee"}],
        }

        _, visits = api_visits([receipt])

        self.assertNotIn("amount_order_total", visits[0])

        receipt["total"] = "5.00"
        _, visits = api_visits([receipt])
        self.assertEqual(visits[0]["amount_order_total"], "5.00")

    def test_merge_history_adds_unmatched_api_stars_once(self):
        report_star = {
            "star_id": "report-star",
            "occurred_on": "2026-01-01",
            "stars_delta": -60.0,
            "source_kind": "ca_customer_information_report",
        }
        history_items = [
            {
                "historyId": "api-spend",
                "historyType": "Point",
                "date": "2026-01-01T15:00:00Z",
                "historyOverview": {"description": "60★ redeemed"},
            },
            {
                "historyId": "api-earn",
                "historyType": "Point",
                "date": "2026-01-02T15:00:00Z",
                "historyOverview": {"description": "50★ earned"},
            },
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as source:
            json.dump({"visits": [], "observations": [], "stars": [report_star]}, source)
            source.flush()

            merge_history(Path(source.name), [], history_items=history_items)
            first = json.loads(Path(source.name).read_text())["stars"]
            merge_history(Path(source.name), [], history_items=history_items)
            second = json.loads(Path(source.name).read_text())["stars"]

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(second[-1]["stars_delta"], 50.0)

    @staticmethod
    def _visit(local_second, source, time_basis="local_wall"):
        return {
            "visit_id": f"{source}:{local_second}",
            "status": "active",
            "occurred_at": local_second,
            "local_date": local_second[:10],
            "local_second": local_second,
            "time_basis": time_basis,
            "store": {"name_raw": "Bayview & Romfield", "name_key": "bayview and romfield"},
            "items": [{"name": "Coffee", "name_key": "coffee", "quantity": None}],
            "source_kinds": [source],
            "source_observation_ids": [f"{source}:{local_second}"],
        }


if __name__ == "__main__":
    unittest.main()
