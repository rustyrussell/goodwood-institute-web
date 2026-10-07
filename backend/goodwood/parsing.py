"""Parsing of the human-written values in calendar notes: times and date lists.

Everything here is written for Australian conventions (day before month) and
for people who are not programmers, so errors are phrased as advice.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
WEEKDAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
               'October', 'November', 'December']


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- times

_TIME_RE = re.compile(r'^(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm|a\.m\.?|p\.m\.?)?$')


def parse_time(text: str) -> dt.time:
    s = text.strip().lower()
    if s in ('noon', 'midday', '12 noon', '12noon'):
        return dt.time(12, 0)
    m = _TIME_RE.match(s)
    if not m:
        raise ParseError(f'"{text.strip()}" is not a time I understand; write it like 7pm, 7.30pm or 19:30')
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if minute > 59:
        raise ParseError(f'"{text.strip()}" has more than 59 minutes')
    if ampm:
        if not 1 <= hour <= 12:
            raise ParseError(f'"{text.strip()}": with am/pm the hour must be 1 to 12')
        if ampm.startswith('p') and hour != 12:
            hour += 12
        elif ampm.startswith('a') and hour == 12:
            hour = 0
        return dt.time(hour, minute)
    # No am/pm: only accept unambiguous 24-hour times such as 19:30 or 09:30.
    if m.group(2) and (hour >= 13 or m.group(1).startswith('0')) and hour <= 23:
        return dt.time(hour, minute)
    raise ParseError(f'"{text.strip()}" could be morning or evening; add am or pm (e.g. 7.30pm)')


_LIST_SPLIT = re.compile(r'\s*(?:,|;|&|\band\b)\s*', re.I)


def parse_times(text: str) -> list[dt.time]:
    """A list of times: "2pm", "2pm, 7.30pm", "2pm & 7.30pm"."""
    parts = [p for p in _LIST_SPLIT.split(text.strip()) if p]
    if not parts:
        raise ParseError('no time given')
    return [parse_time(p) for p in parts]


def format_time(t: dt.time | None) -> str:
    if t is None:
        return ''
    if t == dt.time(12, 0):
        return '12 noon'
    h = t.hour % 12 or 12
    suffix = 'am' if t.hour < 12 else 'pm'
    return f'{h}{suffix}' if t.minute == 0 else f'{h}.{t.minute:02d}{suffix}'


# ---------------------------------------------------------------- dates

def _weekday(word: str) -> int | None:
    w = word.lower().rstrip('.')
    if w.endswith('s') and len(w) > 3:      # "Sundays"
        w = w[:-1]
    for i, name in enumerate(WEEKDAYS):
        if w == name or w == WEEKDAY_NAMES[i].lower() or (len(w) >= 3 and WEEKDAY_NAMES[i].lower().startswith(w)):
            return i
    return None


def _month(word: str) -> int | None:
    w = word.lower().rstrip('.')
    if len(w) < 3:
        return None
    for i, full in enumerate(MONTH_NAMES):
        if full.lower().startswith(w):
            return i + 1
    return None


@dataclass
class _Point:
    """One end of a date item, possibly missing month/year until filled in."""
    text: str
    day: int | None = None
    month: int | None = None
    year: int | None = None
    weekday: int | None = None      # stated weekday (checked) or weekday-only item

    @property
    def weekday_only(self) -> bool:
        return self.day is None


_NUMERIC_RE = re.compile(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$')
_ORD_RE = re.compile(r'^(\d{1,2})(?:st|nd|rd|th)?$', re.I)


def _parse_point(text: str) -> _Point:
    words = text.replace(',', ' ').split()
    if not words:
        raise ParseError('empty date')
    p = _Point(text=text.strip())
    i = 0
    wd = _weekday(words[0])
    if wd is not None:
        p.weekday = wd
        i = 1
        if i == len(words):
            return p                    # weekday only, e.g. "Sundays"
    rest = words[i:]
    m = _NUMERIC_RE.match(rest[0]) if len(rest) == 1 else None
    if m:
        p.day, p.month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            p.year = y + 2000 if y < 100 else y
        return p
    m = _ORD_RE.match(rest[0])
    if not m:
        raise ParseError(f'"{text.strip()}" is not a date I understand; write it like 14 Nov or Sat 14 Nov')
    p.day = int(m.group(1))
    if len(rest) >= 2:
        p.month = _month(rest[1])
        if p.month is None:
            raise ParseError(f'"{rest[1]}" in "{text.strip()}" is not a month')
    if len(rest) >= 3:
        if not re.fullmatch(r'\d{4}', rest[2]):
            raise ParseError(f'"{rest[2]}" in "{text.strip()}" is not a year')
        p.year = int(rest[2])
    if len(rest) > 3:
        raise ParseError(f'"{text.strip()}" has extra words I don\'t understand')
    return p


_RANGE_SPLIT = re.compile(r'\s*(?:[-–—]|\bto\b|\buntil\b|\btill\b)\s*', re.I)
_ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')


@dataclass
class DateSpec:
    dates: set[dt.date] = field(default_factory=set)
    weekdays: set[int] = field(default_factory=set)


def parse_dates(text: str, span_start: dt.date, span_end: dt.date) -> tuple[list[dt.date], list[str]]:
    """Parse a `dates:` value, within an event running span_start..span_end
    (inclusive).  Returns the sorted dates inside the span, and problems found.

    Accepts lists of dates, ranges and weekdays, e.g.
    "14–22 Nov", "14 Nov – 2 Dec", "Sat 21 & Sun 22 Nov", "Sundays", "Thu–Sat",
    "14/11, 21/11/2026".
    """
    problems: list[str] = []
    s = _ISO_RE.sub(lambda m: f'{int(m.group(3))}/{int(m.group(2))}/{m.group(1)}', text)
    items = [p for p in _LIST_SPLIT.split(s.strip()) if p]
    if not items:
        raise ParseError('no dates given')

    parsed: list[list[_Point]] = []
    for item in items:
        ends = [e for e in _RANGE_SPLIT.split(item) if e]
        if len(ends) > 2:
            raise ParseError(f'"{item}" has too many dashes; write a range like 14–22 Nov')
        parsed.append([_parse_point(e) for e in ends])

    # Fill in missing months (and years) from the next point that has one:
    # "21, 22 Nov" and "14–22 Nov" both borrow "Nov" from the right.
    points = [p for item in parsed for p in item if not p.weekday_only]
    next_month = next_year = None
    for p in reversed(points):
        if p.month is None:
            if next_month is None:
                raise ParseError(f'"{p.text}" needs a month, e.g. {p.text} Nov')
            p.month = next_month
            if p.year is None:
                p.year = next_year
        else:
            next_month, next_year = p.month, p.year if p.year is not None else next_year

    def resolve(p: _Point) -> dt.date:
        if p.year is not None:
            years = [p.year]
        else:
            years = list(range(span_start.year - 1, span_end.year + 2))
        candidates = []
        for y in years:
            try:
                candidates.append(dt.date(y, p.month, p.day))
            except ValueError:
                pass
        if not candidates:
            raise ParseError(f'"{p.text}" is not a real date')
        inside = [d for d in candidates if span_start <= d <= span_end]
        d = inside[0] if inside else min(candidates, key=lambda d: abs((d - span_start).days))
        if p.weekday is not None and d.weekday() != p.weekday:
            raise ParseError(f'"{p.text}": {d.day} {MONTH_ABBR[d.month - 1]} {d.year} is a {WEEKDAY_NAMES[d.weekday()]}, '
                             f'not a {WEEKDAY_NAMES[p.weekday]}')
        return d

    spec = DateSpec()
    for item in parsed:
        kinds = {p.weekday_only for p in item}
        if len(kinds) > 1:
            raise ParseError(f'"{" – ".join(p.text for p in item)}" mixes a weekday with a date; '
                             'write either "Thu–Sat" or "14–22 Nov"')
        if item[0].weekday_only:
            a = item[0].weekday
            b = item[-1].weekday
            day = a
            while True:
                spec.weekdays.add(day)
                if day == b:
                    break
                day = (day + 1) % 7
            continue
        first = resolve(item[0])
        last = resolve(item[-1])
        if last < first:
            raise ParseError(f'"{item[0].text} – {item[-1].text}" ends before it starts')
        d = first
        while d <= last:
            spec.dates.add(d)
            d += dt.timedelta(days=1)

    outside = sorted(d for d in spec.dates if not span_start <= d <= span_end)
    if outside:
        problems.append(f'{format_date_list(outside)} {"is" if len(outside) == 1 else "are"} outside the calendar entry '
                        f'({format_date_range(span_start, span_end)}), so ignored')
    result = {d for d in spec.dates if span_start <= d <= span_end}
    for wd in sorted(spec.weekdays):
        matched = [span_start + dt.timedelta(days=i) for i in range((span_end - span_start).days + 1)
                   if (span_start + dt.timedelta(days=i)).weekday() == wd]
        if not matched:
            problems.append(f'there is no {WEEKDAY_NAMES[wd]} in the calendar entry '
                            f'({format_date_range(span_start, span_end)})')
        result.update(matched)
    if not result:
        problems.append('none of these dates fall within the calendar entry '
                        f'({format_date_range(span_start, span_end)})')
    return sorted(result), problems


# ---------------------------------------------------------------- formatting

def format_date(d: dt.date, weekday: bool = True, year: bool = False) -> str:
    s = f'{d.day} {MONTH_ABBR[d.month - 1]}'
    if weekday:
        s = f'{WEEKDAY_NAMES[d.weekday()][:3]} {s}'
    if year:
        s += f' {d.year}'
    return s


def format_date_range(a: dt.date, b: dt.date, weekday: bool = True) -> str:
    if a == b:
        return format_date(a, weekday)
    if not weekday and a.month == b.month:
        return f'{a.day}–{b.day} {MONTH_ABBR[b.month - 1]}'
    return f'{format_date(a, weekday)} – {format_date(b, weekday)}'


def date_runs(dates: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    """Group sorted dates into runs of consecutive days."""
    runs: list[tuple[dt.date, dt.date]] = []
    for d in sorted(set(dates)):
        if runs and d - runs[-1][1] == dt.timedelta(days=1):
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def format_date_list(dates: list[dt.date]) -> str:
    return ', '.join(format_date_range(a, b) for a, b in date_runs(dates))
