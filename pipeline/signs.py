"""Turn City of Austin sign-inventory parking signs into curb rules.

A rule is {"t": zone-type name from rules/zone_types.json, "w": windows, "q": quality, "tl": minutes}
using the same window format as pipeline/hours.py, so the browser evaluates signs and curb zones
with the same engine.

Signs fall into three groups:
  block rules  - apply to that side of the block (no parking, permit, paid, time limit)
  spot signs   - cover a few spaces only (ADA, loading, bus stop, "here to corner"); listed on the
                 card but they don't colour the whole block side
  ignore       - street-name signs that happen to contain "PARK", informational signs
"""
import re

from hours import DAY_TOKENS

SPOT = re.compile(r"HANDICAP|ADA\b|ACCESSIBLE|DISABLED|LOADING|BUS\b|BUS STOP|CORNER|VALET|BICYCLE|BIKE PARKING|"
                  r"RESERVED|TAXI|POLICE|FIRE LANE|EMERGENCY|ELECTRIC|EV\b|CHARGING|MOTORCYCLE|SCOOTER|CAR ?SHARE|"
                  r"PASSENGER|DELIVERY|FOOD TRUCK|CUSTOMER|VISITOR|PICK ?UP|DROP ?OFF|HOTEL|CHURCH|STAFF|EMPLOYEE")
INFO = re.compile(r"PARALLEL PARKING ONLY|ANGLE PARKING|BACK-IN|HEAD-IN|PULL IN|PARK WITHIN|PARKING LOT|PARKING GARAGE|"
                  r"PUBLIC PARKING|PARKING AREA|PARKING ENTRANCE|PARKING \w+ ARROW$|^P\b")
PAID = re.compile(r"PAY TO PARK|PARKATX|TEXT PARKING|PAY STATION|PAY HERE|METER")
PERMIT = re.compile(r"PERMIT")
NOPARK = re.compile(r"NO PARKING|NO STOPPING|NO STANDING|TOW[- ]AWAY|DO NOT PARK")
TIMED = re.compile(r"(\d+)\s*(HOUR|HR|MIN|MINUTE)S?\s+PARKING|PARKING\s+(\d+)\s*(HOUR|HR|MIN|MINUTE)S?")

TIME = r"(?:\d{1,2}(?:[:.]\d{2})?\s*(?:AM|PM|A\.M\.|P\.M\.)|MIDNIGHT|NOON|12\s*MID)"
RANGE = re.compile(rf"({TIME})\s*(?:-|TO|–)\s*({TIME})")
DAY = r"(?:MON|TUE|TUES|WED|THU|THUR|THURS|FRI|SAT|SUN)(?:DAY|SDAY|NESDAY|RSDAY|URDAY)?"
DAYRANGE = re.compile(rf"\b({DAY})\s*(?:-|THRU|THROUGH|TO|–)\s*({DAY})\b")
SINGLEDAY = re.compile(rf"\b({DAY})\b")


def _t(s, is_end):
    s = s.replace("A.M.", "AM").replace("P.M.", "PM").replace(" ", "")
    s = re.sub(r"(\d)\.(\d{2})", r"\1:\2", s)
    if s in ("MIDNIGHT", "12MID"):
        return 1440 if is_end else 0
    if s == "NOON":
        return 720
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(AM|PM)", s)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not 1 <= h <= 12 or mi > 59:
        return None
    h = h % 12 + (12 if m.group(3) == "PM" else 0)
    v = h * 60 + mi
    return 1440 if is_end and v == 0 else v


def _day(tok):
    return DAY_TOKENS.get(tok[:3].lower()) if tok[:3].lower() in DAY_TOKENS else DAY_TOKENS.get(tok[:4].lower())


def parse_days(msg):
    """Days a sign applies to. None = couldn't tell; [] never returned."""
    if "SCHOOL DAYS" in msg or "SCHOOL DAY" in msg:
        return [1, 2, 3, 4, 5], "school days treated as Mon-Fri"
    days = []
    for a, b in DAYRANGE.findall(msg):
        i, j = _day(a), _day(b)
        if i is None or j is None:
            return None, None
        d = i
        days.append(d)
        while d != j:
            d = (d + 1) % 7
            days.append(d)
    rest = DAYRANGE.sub(" ", msg)
    if "EXCEPT SUN" in rest:
        days += [1, 2, 3, 4, 5, 6]
        rest = rest.replace("EXCEPT SUNDAY", " ").replace("EXCEPT SUN", " ")
    for tok in SINGLEDAY.findall(rest):
        d = _day(tok)
        if d is not None:
            days.append(d)
    if not days:
        return list(range(7)), None  # no days on the sign = every day
    return sorted(set(days)), None


def parse_windows(msg):
    """Return (windows, quality, note)."""
    ranges = RANGE.findall(msg)
    days, note = parse_days(msg)
    if days is None:
        return [], "none", "Couldn't read the days on this sign"
    if not ranges:
        if re.search(r"\d", re.sub(r"\b(AREA|ZONE|DISTRICT)\s*\d+|\d+\s*(HOUR|HR|MIN|MINUTE)S?|\d{3,}", "", msg)):
            return [], "none", "Couldn't read the hours on this sign"
        return [(d, 0, 1440) for d in days], "ok", note  # "at any time" / no hours = all day
    out = []
    for a, b in ranges:
        s, e = _t(a, False), _t(b, True)
        if s is None or e is None:
            return [], "none", "Couldn't read the hours on this sign"
        end = e if e > s else e + 1440
        out += [(d, s, end) for d in days]
    return sorted(set(out)), "ok", note


def classify(msg):
    """Return (group, rule|None). group in block/spot/info/ignore."""
    m = re.sub(r"\s+", " ", (msg or "").upper()).strip()
    if "PARK" not in m and not NOPARK.search(m):
        return "ignore", None
    if re.search(r"\d,?\d{3} ?LBS|TRUCK|TRAILER|OVERSIZE", m):
        return "info", None  # heavy-vehicle rules don't apply to cars
    if SPOT.search(m):
        return "spot", None
    if PAID.search(m):
        # Pay signs rarely carry hours; hours come from the pay-to-park area at build time.
        w, q, note = parse_windows(m) if RANGE.search(m) else ([], "area", None)
        return "block", {"t": "Paystation Zone", "w": w, "q": q, "note": note}
    if (NOPARK.search(m) and PERMIT.search(m)) or "RESIDENT PARKING ONLY" in m:
        w, q, note = parse_windows(m)
        return "block", {"t": "Residential Parking Permit", "w": w, "q": q, "note": note}
    tm = TIMED.search(m)
    if tm and not NOPARK.search(m):
        n = int(tm.group(1) or tm.group(3))
        unit = tm.group(2) or tm.group(4)
        w, q, note = parse_windows(m)
        return "block", {"t": "Time Limited Parking", "w": w, "q": q, "note": note,
                         "tl": n * 60 if unit.startswith("H") else n}
    if NOPARK.search(m):
        w, q, note = parse_windows(m)
        return "block", {"t": "No Parking", "w": w, "q": q, "note": note}
    if INFO.search(m):
        return "info", None
    # Contains PARK but isn't a recognisable parking regulation (mostly street names: PARKFIELD DR).
    return "ignore", None
