import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from starbucks_history import _merge, _report_groups, parse_report


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
