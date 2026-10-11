"""Estimate caffeine intake (mg) from Starbucks order history.

Only coffee, tea, and refresher drinks are counted. Item names in the ledger
are terse POS strings ("Gr Iced Coffee", "Tl Strawberry Acai Juice"), quantity
is never recorded, and receipts list some drinks twice: once as a sized SKU and
once as an unsized product/component line ("Gr Iced Coffee" next to
"Starbucks® Iced Coffee Blend"). Estimates therefore rely on three assumptions
documented here and surfaced on the page:

* Each line is one drink; unsized lines of the same drink family in the same
  visit are components of a sized line and are not counted again.
* A drink with no size is a Grande.
* Caffeine per size follows Starbucks' published figures (rounded); anything
  not listed here (food, juice, hot chocolate, lemonade, steamed milk) is 0.

Edit RULES / TABLES below to adjust the estimate, then re-run
scripts/starbucks_import.py.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

SIZES = ("short", "tall", "grande", "venti", "trenta")
DEFAULT_SIZE = "grande"
WINDOW_DAYS = 365

# mg of caffeine by size: (short, tall, grande, venti, trenta).
TABLES: dict[str, tuple[int, int, int, int, int]] = {
    "brewed_pike": (155, 235, 310, 410, 410),
    "brewed_blonde": (180, 270, 360, 475, 475),
    "brewed_dark": (130, 195, 260, 340, 340),
    "brewed_decaf": (15, 20, 25, 30, 30),
    "iced_coffee": (85, 120, 165, 225, 280),
    "cold_brew": (155, 155, 205, 310, 360),
    "nitro_cold_brew": (215, 215, 265, 360, 360),
    "americano": (75, 150, 225, 300, 300),
    "latte": (75, 75, 150, 150, 150),
    "latte_iced": (75, 75, 150, 225, 225),
    "espresso": (150, 150, 150, 150, 150),
    "shaken_espresso": (170, 170, 255, 340, 340),
    "refresher": (25, 35, 45, 70, 90),
    "iced_energy": (120, 120, 160, 205, 205),
    "tea_iced": (20, 25, 30, 40, 50),
    "tea_lemonade": (15, 20, 25, 35, 45),
    "tea_hot": (10, 15, 20, 25, 25),
    "chai": (50, 70, 95, 130, 130),
    "matcha": (40, 55, 80, 110, 110),
    "herbal_tea": (0, 0, 0, 0, 0),
}
SHOT_MG = 75
VIA_MG = 130
# Modifier lines that add caffeine on top of the drink they ride along with.
# "Xtr Green Coffee Extract Blend" is an extra scoop of the refresher base
# (about a Grande refresher's worth); "Add Shot Chai" is a shot of chai
# concentrate (a Grande chai latte's 95 mg is about four of them).
EXTRA_EXTRACT_MG = 45
CHAI_SHOT_MG = 25

_SIZE_TOKENS = {
    "short": "short", "sh": "short",
    "tall": "tall", "tl": "tall",
    "grande": "grande", "gr": "grande",
    "venti": "venti", "vt": "venti",
    "trenta": "trenta", "tr": "trenta", "trt": "trenta",
}
_OZ_SIZES = {"8": "short", "12": "tall", "16": "grande", "20": "venti", "24": "venti", "30": "trenta"}
_ICED = re.compile(r"\b(iced|icd|ic|ice)\b")

# Matched first: things that mention coffee/tea/fruit words but are not drinks.
_NOT_A_DRINK = re.compile(
    r"^add\b|\b(cake|pop|loaf|cookie|danish|croissant|muffin|wrap|sandwich|sandwch|bagel|"
    r"oatmeal|pancakes?|waffle|pie|bar|pocket|parfait|box|egg|eggs|bacon|doughnut|bites|"
    r"popcorn|mug|card|pouch|topping|powder|cheese|water|sparklin|sparkln|montellier|"
    r"foam|steam|steamed|milk|cider|chips|pastry|brkfst|bkfst|bfast)\b"
    r"|hot chocolate|apple spice|\bjuice \d+ ?oz\b|\b\d+ ?oz juice\b"
    r"|12ct|/ip|/cs",
    re.IGNORECASE,
)
# Checked before _NOT_A_DRINK, since both are "add"/"extract" modifier lines.
_MODIFIERS: list[tuple[re.Pattern[str], str, str, int]] = [
    (re.compile(r"green coffee extract"), "refresher", "extra_extract", EXTRA_EXTRACT_MG),
    (re.compile(r"^add shot chai\b"), "tea", "chai_shot", CHAI_SHOT_MG),
]


@dataclass(frozen=True)
class Drink:
    category: str  # coffee | tea | refresher
    family: str    # drink identity within a visit, used to collapse duplicate lines
    size: str
    sized: bool
    caffeine_mg: int


def _normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("®", " ").replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/\s-]", " ", text)).strip()


def _detect_size(text: str) -> str | None:
    oz = re.search(r"\b(\d+) ?oz\b", text)
    if oz and oz.group(1) in _OZ_SIZES:
        return _OZ_SIZES[oz.group(1)]
    for token in re.findall(r"[a-z0-9]+", text):
        if token in _SIZE_TOKENS:
            return _SIZE_TOKENS[token]
    return None


# (regex, category, family, table). First match wins; "latte" tables are
# resolved for iced venti at lookup time.
RULES: list[tuple[str, str, str, str]] = [
    (r"\bvia\b", "coffee", "via", "via"),
    (r"nitro", "coffee", "nitro", "nitro_cold_brew"),
    (r"cold ?brew|coldbrew", "coffee", "cold_brew", "cold_brew"),
    (r"shkn esp|shaken espresso|blonde apple crisp oatmilk", "coffee", "shaken_espresso", "shaken_espresso"),
    (r"espresso (add )?shot|add (an )?espresso|add shot espresso", "coffee", "shot", "shot"),
    (r"americano", "coffee", "americano", "americano"),
    (r"\bespresso\b", "coffee", "espresso", "espresso"),
    (r"\bchai\b", "tea", "chai", "chai"),
    (r"matcha|green tea latte", "tea", "matcha", "matcha"),
    (r"latte|macchiato|mocha|cappuccino|flat white|cortado", "coffee", "latte", "latte"),
    (r"decaf", "coffee", "brewed", "brewed_decaf"),
    (r"dark roast", "coffee", "brewed", "brewed_dark"),
    (r"blonde roast", "coffee", "brewed", "brewed_blonde"),
    (r"brewed|pike place|medium roast", "coffee", "brewed", "brewed_pike"),
    (r"iced coffee|icd coffee|ic coffee", "coffee", "iced_coffee", "iced_coffee"),
    (r"iced energy|sparkling ener", "refresher", "iced_energy", "iced_energy"),
    # Refreshers before tea: "Iced Strawberry Acai Tea Lemonade" is a refresher.
    (r"cool lime|lemonade cool lime", "refresher", "cool_lime", "refresher"),
    (r"strawberry coconut|pink drink", "refresher", "pink", "refresher"),
    (r"acai|strwbry|strawberry", "refresher", "strawberry_acai", "refresher"),
    (r"dragonfruit|drgnfrt|dragon", "refresher", "dragonfruit", "refresher"),
    (r"pnppl|pinpl|pinapple|pineapple|passionfruit|pasfrt", "refresher", "pineapple", "refresher"),
    (r"mango|strbe", "refresher", "mango", "refresher"),
    (r"blood orange", "refresher", "blood_orange", "refresher"),
    (r"summer bery|bery|blackberry sage|spicy lime|refresher|refr\b|rfshr", "refresher", "other_refresher", "refresher"),
    (r"passion", "tea", "passion_tea", "herbal_tea"),
    (r"\btea\b", "tea", "tea", "tea"),
]
_COMPILED = [(re.compile(p), c, f, t) for p, c, f, t in RULES]


def classify_item(name: str) -> Drink | None:
    """Return the caffeinated drink a ledger line represents, or None."""
    text = _normalize(name)
    if not text:
        return None
    for pattern, category, family, mg in _MODIFIERS:
        if pattern.search(text):
            # Always counted: a modifier adds caffeine beyond its drink's.
            return Drink(category, family, DEFAULT_SIZE, False, mg)
    if _NOT_A_DRINK.search(text):
        return None
    for pattern, category, family, table in _COMPILED:
        if not pattern.search(text):
            continue
        size = _detect_size(text)
        sized = size is not None
        size = size or DEFAULT_SIZE
        if table == "shot":
            mg = SHOT_MG
        elif table == "via":
            mg = VIA_MG
        else:
            if table == "latte" and _ICED.search(text):
                table = "latte_iced"
            elif table == "tea" and not _ICED.search(text) and "lemonade" not in text:
                table = "tea_hot"
            elif table == "tea" and "lemonade" in text:
                table = "tea_lemonade"
            elif table == "tea":
                table = "tea_iced"
            mg = TABLES[table][SIZES.index(size)]
        return Drink(category, family, size, sized, mg)
    return None


def visit_drinks(item_names: list[str]) -> list[Drink]:
    """Classify a visit's lines, collapsing unsized component duplicates."""
    drinks = [d for d in (classify_item(n) for n in item_names) if d is not None]
    sized_families = {d.family for d in drinks if d.sized}
    return [d for d in drinks if d.sized or d.family not in sized_families]


def build_caffeine(visits: list[dict], window_days: int = WINDOW_DAYS) -> dict:
    """Daily mg for every active visit plus an hour-of-day histogram.

    Uses each visit's local wall-clock second (`local_second`), which the
    ledger already converts from UTC where the source was UTC.
    """
    daily: dict[str, int] = defaultdict(int)
    stamped: list[tuple[str, int, int]] = []  # (local_date, hour, mg)
    visit_days: set[str] = set()  # every day with an order, caffeinated or not
    drink_count = 0
    for visit in visits:
        if visit.get("status", "active") != "active":
            continue
        local_second = visit.get("local_second") or visit.get("occurred_at") or ""
        day = visit.get("local_date") or local_second[:10]
        if len(day) != 10 or not day.startswith("20"):
            continue
        visit_days.add(day)
        names = [i.get("name") or "" for i in visit.get("items", [])]
        drinks = visit_drinks(names)
        mg = sum(d.caffeine_mg for d in drinks)
        drink_count += len(drinks)
        if not drinks:
            continue
        daily[day] += mg
        hour = int(local_second[11:13]) if len(local_second) >= 13 and local_second[11:13].isdigit() else None
        if hour is not None:
            stamped.append((day, hour, mg))

    last_day = max(daily) if daily else None
    first_day = min(daily) if daily else None
    hourly = [0] * 24
    window_start = None
    window_visit_days = 0
    week_mg: list[int] = []
    week_visit_days: list[int] = []
    week_start: str | None = None
    if last_day:
        end = date.fromisoformat(last_day)
        window_start = (end - timedelta(days=window_days - 1)).isoformat()
        for day, hour, mg in stamped:
            if window_start <= day <= last_day:
                hourly[hour] += mg
        for day in visit_days:
            if window_start <= day <= last_day:
                window_visit_days += 1

        # Contiguous Sunday-start weeks (matching the page's calendar) from the
        # first caffeinated day, as parallel arrays so bar positions are plain
        # indexes. Visit days count every day with an order, caffeinated or not.
        first = date.fromisoformat(first_day)
        week = first - timedelta(days=(first.weekday() + 1) % 7)
        week_start = week.isoformat()
        while week <= end:
            days_in_week = [(week + timedelta(days=i)).isoformat() for i in range(7)]
            week_mg.append(sum(daily.get(d, 0) for d in days_in_week))
            week_visit_days.append(
                sum(1 for d in days_in_week if d in visit_days and d <= last_day)
            )
            week += timedelta(days=7)

    return {
        "unit": "mg",
        "first_day": first_day,
        "last_day": last_day,
        "drink_count": drink_count,
        "visit_days": len(visit_days),
        # Mean over every day with an order, so food-only days count as 0 mg.
        "avg_mg_per_visit_day": round(sum(daily.values()) / len(visit_days)) if visit_days else 0,
        "days": dict(sorted(daily.items())),
        # Charts divide mg by visit_days to show an average per day with an order.
        "weekly": {
            "start": week_start,
            "mg": week_mg,
            "visit_days": week_visit_days,
        },
        "hourly": {
            "window_days": window_days,
            "start": window_start,
            "end": last_day,
            "visit_days": window_visit_days,
            "mg_by_hour": hourly,
        },
    }
