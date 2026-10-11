import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from starbucks_caffeine import build_caffeine, classify_item, visit_drinks


def visit(local_second, *names, status="active"):
    return {
        "status": status,
        "local_date": local_second[:10],
        "local_second": local_second,
        "items": [{"name": name} for name in names],
    }


class ClassifyItemTests(unittest.TestCase):
    def test_sizes_from_prefixes_suffixes_and_ounces(self):
        self.assertEqual(classify_item("Tall Iced Coffee").caffeine_mg, 120)
        self.assertEqual(classify_item("Gr Iced Coffee").caffeine_mg, 165)
        self.assertEqual(classify_item("Vt Iced Coffee").caffeine_mg, 225)
        self.assertEqual(classify_item("Brewed Pike Place Roast Grande").caffeine_mg, 310)
        self.assertEqual(classify_item("24oz  Strawberry Acai Juice").size, "venti")

    def test_unsized_drink_defaults_to_grande(self):
        drink = classify_item("Iced Caffè Americano")
        self.assertFalse(drink.sized)
        self.assertEqual((drink.size, drink.caffeine_mg), ("grande", 225))

    def test_categories(self):
        self.assertEqual(classify_item("Americano Tall").category, "coffee")
        self.assertEqual(classify_item("Gr Black Iced Tea").category, "tea")
        self.assertEqual(classify_item("Gr Chai Tea Latte").category, "tea")
        self.assertEqual(classify_item("Gr Strawberry Acai Juice").category, "refresher")
        # Tea-lemonade names that mention a refresher fruit are refreshers.
        self.assertEqual(classify_item("Gr Icd Strwbry Acai Tea Lemnad").category, "refresher")

    def test_non_caffeinated_or_non_drinks_are_ignored(self):
        for name in (
            "Lemonade",
            "Hot Chocolate Grande",
            "Apple Spice Caramel Grande",
            "Tl Steamed Milk",
            "Cinnamon Coffee Cake Us Reg",
            "Add White Mocha Sauce",
            "Via Pike Place 12ct 6/ip Can",
            "Water Ethos 700ml",
        ):
            self.assertIsNone(classify_item(name), name)

    def test_modifier_lines_add_caffeine(self):
        extract = classify_item("Xtr Green Coffee Extract Blend")
        self.assertEqual((extract.category, extract.caffeine_mg), ("refresher", 45))
        chai = classify_item("Add Shot Chai")
        self.assertEqual((chai.category, chai.caffeine_mg), ("tea", 25))

    def test_herbal_tea_has_no_caffeine(self):
        self.assertEqual(classify_item("Tr Ic Passion Tea").caffeine_mg, 0)

    def test_iced_venti_latte_has_extra_shot(self):
        self.assertEqual(classify_item("White Mocha Iced Venti").caffeine_mg, 225)
        self.assertEqual(classify_item("Latte Tall").caffeine_mg, 75)


class VisitDrinksTests(unittest.TestCase):
    def test_unsized_component_line_is_not_double_counted(self):
        drinks = visit_drinks(["Gr Iced Coffee", "Starbucks® Iced Coffee Blend"])
        self.assertEqual([d.caffeine_mg for d in drinks], [165])

    def test_unsized_line_alone_counts_as_a_drink(self):
        drinks = visit_drinks(["Starbucks® Iced Coffee Blend"])
        self.assertEqual([d.caffeine_mg for d in drinks], [165])

    def test_extra_extract_is_added_to_its_refresher(self):
        drinks = visit_drinks(["Tr Lemonade Cool Lime", "Xtr Green Coffee Extract Blend", "Cool Lime Lemonade Refresher"])
        self.assertEqual(sorted(d.caffeine_mg for d in drinks), [45, 90])

    def test_different_drink_families_are_both_counted(self):
        drinks = visit_drinks(["Vt Lemonade Cool Lime", "Cool Lime Lemonade Refresher", "Tall Iced Espresso"])
        self.assertEqual(sorted(d.caffeine_mg for d in drinks), [70, 150])


class BuildCaffeineTests(unittest.TestCase):
    def test_daily_totals_and_hourly_window(self):
        visits = [
            visit("2025-08-30 09:15:00", "Tall Iced Espresso"),  # before the 365-day window
            visit("2025-08-31 09:15:00", "Tall Iced Espresso"),  # first window day
            visit("2026-08-30 09:45:00", "Gr Iced Coffee", "Butter Croissant", "Tall Iced Espresso"),
            visit("2026-08-30 17:05:00", "Gr Black Iced Tea"),
            visit("2026-08-29 08:00:00", "Hot Chocolate Grande"),
            visit("2026-08-29 08:30:00", "Tall Iced Espresso", status="void"),
        ]

        result = build_caffeine(visits)

        self.assertEqual(result["first_day"], "2025-08-30")
        self.assertEqual(result["last_day"], "2026-08-30")
        self.assertEqual(result["days"]["2026-08-30"], 165 + 150 + 30)
        self.assertNotIn("2026-08-29", result["days"])
        hourly = result["hourly"]
        self.assertEqual(hourly["start"], "2025-08-31")
        self.assertEqual(hourly["end"], "2026-08-30")
        self.assertEqual(len(hourly["mg_by_hour"]), 24)
        self.assertEqual(hourly["mg_by_hour"][9], 150 + 165 + 150)
        self.assertEqual(hourly["mg_by_hour"][17], 30)
        self.assertEqual(sum(hourly["mg_by_hour"]), 495)

    def test_visit_day_counts_for_normalizing_charts(self):
        visits = [
            visit("2025-08-30 09:15:00", "Tall Iced Espresso"),  # before the window
            visit("2025-08-31 09:15:00", "Tall Iced Espresso"),  # Sunday, first window day
            visit("2026-08-29 08:00:00", "Hot Chocolate Grande"),  # Saturday, food-only
            visit("2026-08-30 09:45:00", "Gr Iced Coffee"),  # Sunday, last day
        ]

        result = build_caffeine(visits)

        self.assertEqual(result["hourly"]["visit_days"], 3)
        weekly = result["weekly"]
        # Weeks are contiguous Sundays from the week of the first caffeinated day.
        self.assertEqual(weekly["start"], "2025-08-24")
        self.assertEqual(len(weekly["mg"]), len(weekly["visit_days"]))
        last = len(weekly["mg"]) - 1
        self.assertEqual(date.fromisoformat(weekly["start"]) + timedelta(weeks=last), date(2026, 8, 30))
        self.assertEqual((weekly["mg"][last], weekly["visit_days"][last]), (165, 1))
        self.assertEqual((weekly["mg"][last - 1], weekly["visit_days"][last - 1]), (0, 1))  # food-only Saturday
        self.assertEqual((weekly["mg"][0], weekly["visit_days"][0]), (150, 1))  # Saturday 2025-08-30

    def test_average_counts_every_visit_day_including_food_only_days(self):
        visits = [
            visit("2026-08-01 09:00:00", "Tall Iced Espresso"),  # 150
            visit("2026-08-02 09:00:00", "Butter Croissant"),  # visit day, 0 mg
            visit("2026-08-03 09:00:00", "Gr Iced Coffee"),  # 165
            visit("2026-08-03 15:00:00", "Tall Iced Espresso"),  # same day: 150 more
            visit("2026-08-04 09:00:00", "Tall Iced Espresso", status="void"),
        ]

        result = build_caffeine(visits)

        self.assertEqual(result["visit_days"], 3)
        self.assertEqual(result["avg_mg_per_visit_day"], round((150 + 165 + 150) / 3))

    def test_empty_history(self):
        result = build_caffeine([])
        self.assertEqual(result["days"], {})
        self.assertEqual(result["hourly"]["mg_by_hour"], [0] * 24)


if __name__ == "__main__":
    unittest.main()
