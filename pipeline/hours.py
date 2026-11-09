"""Parse City of Austin parking-zone hours into canonical windows.

A window is (day, start_min, end_min) with day 0=Sun..6=Sat (same as JS Date.getDay()).
end_min may exceed 1440 when a window crosses midnight (e.g. 18:00-08:00 -> 1080..1920).

Two sources exist per zone (see DATA_NOTES.md):
  DAY_HOUR_CONCATENATE  machine-readable JSON, sometimes truncated or garbled
  HOURS_OF_OPERATION    human string, e.g. "Mon-Sat: 8AM-6PM, Sun: 1PM-6PM"
Both are parsed; the build step compares them and flags disagreements.
"""
import json
import re

DAY_TOKENS = {
    "sun": 0, "sunday": 0, "mon": 1, "monday": 1, "tue": 2, "tues": 2, "tuesday": 2,
    "wed": 3, "wednesday": 3, "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "fri": 5, "friday": 5, "sat": 6, "saturday": 6,
}
EVENT_TOKENS = {"event", "event_days", "events"}


class HoursError(ValueError):
    pass


def _hhmm(s, is_end):
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m:
        raise HoursError(f"bad time {s!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 24 and mi == 0:
        return 1440
    if h > 23 or mi > 59:
        raise HoursError(f"bad time {s!r}")
    v = h * 60 + mi
    if is_end and v == 1439:  # "23:59" is the data's way of saying midnight
        v = 1440
    return v


def _window(days, start, end):
    """Expand one schedule entry into per-day windows."""
    out = []
    span_end = end if end > start else end + 1440  # end<=start => crosses midnight; equal => 24h
    for d in days:
        out.append((d, start, span_end))
    return out


def parse_json_hours(raw):
    """Return (windows, event_only). Raises HoursError if it can't be parsed cleanly."""
    if not raw or not raw.strip():
        raise HoursError("empty")
    text = raw.strip()
    entries = []
    try:
        val = json.loads(text)
        entries = val if isinstance(val, list) else [val]
    except json.JSONDecodeError:
        # Common shape: one JSON array per line, sometimes with arrays split across lines.
        objs = re.findall(r"\{[^{}]*\}", text)
        if not objs:
            raise HoursError("no objects")
        for o in objs:
            try:
                entries.append(json.loads(o))
            except json.JSONDecodeError:
                raise HoursError(f"garbled object {o[:60]!r}")
        # Detect truncation: leftover text after removing parsed objects that looks like data.
        rest = re.sub(r"\{[^{}]*\}", "", text)
        if re.search(r"[a-z0-9]", rest, re.I):
            raise HoursError("truncated/garbled")
    windows, event = [], False
    for e in entries:
        if isinstance(e, list):
            # nested array from a line-per-array layout that happened to parse as a whole
            for sub in e:
                w, ev = parse_json_hours(json.dumps(sub))
                windows += w
                event |= ev
            continue
        if not isinstance(e, dict) or "days" not in e:
            raise HoursError(f"bad entry {e!r}")
        days = []
        for t in e["days"]:
            t = str(t).strip().lower()
            if t in EVENT_TOKENS:
                event = True
                continue
            if t not in DAY_TOKENS:
                raise HoursError(f"bad day {t!r}")
            days.append(DAY_TOKENS[t])
        start = _hhmm(e.get("start_time"), False)
        end = _hhmm(e.get("end_time"), True)
        windows += _window(days, start, end)
    return sorted(set(windows)), event


_TIME = r"(\d{1,2}(?::\d{2})?\s*(?:AM|PM)|12\s*MID|MIDNIGHT|NOON)"


def _human_time(s, is_end):
    s = s.strip().upper().replace(" ", "")
    if s in ("12MID", "MIDNIGHT"):
        return 1440 if is_end else 0
    if s == "NOON":
        return 720
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(AM|PM)", s)
    if not m:
        raise HoursError(f"bad human time {s!r}")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if h < 1 or h > 12 or mi > 59:
        raise HoursError(f"bad human time {s!r}")
    h = h % 12 + (12 if ap == "PM" else 0)
    v = h * 60 + mi
    if is_end and v == 0:
        v = 1440
    return v


def _human_days(s):
    s = s.strip().lower()
    days = []
    for part in re.split(r"\s*(?:,|&|and)\s*", s):
        if not part:
            continue
        if "-" in part:
            a, b = [p.strip() for p in part.split("-", 1)]
            if a not in DAY_TOKENS or b not in DAY_TOKENS:
                raise HoursError(f"bad day range {part!r}")
            i, j = DAY_TOKENS[a], DAY_TOKENS[b]
            # Walk forward through the week, wrapping (Sun-Thu, Sat-Thu are valid).
            d = i
            days.append(d)
            while d != j:
                d = (d + 1) % 7
                days.append(d)
        else:
            if part not in DAY_TOKENS:
                raise HoursError(f"bad day {part!r}")
            days.append(DAY_TOKENS[part])
    return days


def parse_human_hours(raw):
    """Parse 'Mon-Sat: 8AM-6PM, Sun: 1PM-6PM' style strings. Raises HoursError."""
    if not raw or not raw.strip():
        raise HoursError("empty")
    text = raw.strip()
    if re.search(r"event", text, re.I):
        raise HoursError("event-based hours")
    windows = []
    # Tokenise into "DAYS:" headers and time ranges / All Day, in order.
    pattern = re.compile(
        r"(?P<days>[A-Za-z]{3,9}(?:\s*-\s*[A-Za-z]{3,9})?(?:\s*,\s*[A-Za-z]{3,9}(?:\s*-\s*[A-Za-z]{3,9})?)*)\s*:"
        r"|(?P<allday>ALL\s*DAY)"
        rf"|(?P<range>{_TIME}\s*-\s*{_TIME})",
        re.I,
    )
    cur_days = None
    pos = 0
    for m in pattern.finditer(text):
        gap = text[pos:m.start()]
        if re.search(r"[A-Za-z0-9]", re.sub(r"(?i)\band\b|&|,", "", gap)):
            raise HoursError(f"unparsed text {gap!r}")
        pos = m.end()
        if m.group("days"):
            cur_days = _human_days(m.group("days"))
        elif cur_days is None:
            raise HoursError("time before days")
        elif m.group("allday"):
            windows += [(d, 0, 1440) for d in cur_days]
        else:
            a, b = re.split(r"\s*-\s*(?=\d|12\s*MID|MIDNIGHT|NOON)", m.group("range"), maxsplit=1, flags=re.I)
            start, end = _human_time(a, False), _human_time(b, True)
            windows += _window(cur_days, start, end)
    if re.search(r"[A-Za-z0-9]", text[pos:]):
        raise HoursError(f"trailing text {text[pos:]!r}")
    if not windows:
        raise HoursError("no windows")
    return sorted(set(windows))


def minute_set(windows):
    """Set of (week-minute) covered, for comparing two window lists regardless of how they're split."""
    s = set()
    for d, a, b in windows:
        for m in range(a, b):
            s.add((d * 1440 + m) % (7 * 1440))
    return s
