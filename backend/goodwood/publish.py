"""Turn calendar events into the public JSON and the staff report.

Public output is assembled only from parsed keyword values (see notes.py), the
event's title and times, and the regulars rules.  Raw notes never reach it.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from .events import Event
from .notes import SHOW_KEYWORDS, Notes, parse_notes
from .parsing import (ParseError, date_runs, format_date, format_date_list, format_date_range, format_time,
                      parse_dates, parse_times)

# The Institute marks the venue with the event's colour (Google's event colour IDs).
DEFAULT_VENUES = {
    '7': 'Studio Theatre', '9': 'Studio Theatre',   # Peacock, Blueberry (blue)
    '10': 'Little Reid', '2': 'Little Reid',        # Basil, Sage (green)
    '6': 'Main Theatre',                            # Tangerine (orange)
    '11': 'Main Theatre',                           # Tomato (red): whole venue, performance in the main theatre
}
COLOUR_NAMES = {'1': 'lavender', '2': 'sage', '3': 'grape', '4': 'flamingo', '5': 'banana', '6': 'tangerine',
                '7': 'peacock', '8': 'graphite', '9': 'blueberry', '10': 'basil', '11': 'tomato'}

REGULAR_WEEKS = 4
SHOW_HORIZON_DAYS = 400

STATUSES = {
    'sold out': 'Sold out',
    'cancelled': 'Cancelled',
    'canceled': 'Cancelled',
    'few tickets left': 'Few tickets left',
    'selling fast': 'Selling fast',
}
SINGLE_FIELDS = ['title', 'company', 'tickets', 'ticket prices', 'image', 'website', 'summary',
                 'suitable for', 'duration']
URL_FIELDS = {'tickets', 'image', 'website'}
JSON_NAMES = {'ticket prices': 'ticketPrices', 'tickets': 'ticketsUrl', 'website': 'websiteUrl',
              'suitable for': 'suitableFor'}


@dataclass
class Rule:
    id: int
    match: str
    name: str
    activity: str = ''
    website: str = ''


@dataclass
class Performance:
    date: dt.date
    start: dt.time | None
    doors: dt.time | None
    status: str | None
    end: dt.time | None = None


@dataclass
class Output:
    shows: dict
    regulars: dict
    report: dict


def event_ref(e: Event) -> dict:
    return {'id': e.id, 'title': e.summary or '(no title)', 'when': e.when(), 'link': e.html_link}


class Reporter:
    def __init__(self):
        self.issues: list[dict] = []
        self._seen: dict[tuple, dict] = {}

    def add(self, event: Event | None, severity: str, message: str, line: int | None = None,
            group: str | None = None):
        # Recurring events repeat the same problem every week: report it once.
        # `group` widens that to entries that are related some other way (same title).
        key = (group or (event.series_id if event else None), severity, message)
        if key in self._seen:
            self._seen[key]['count'] += 1
            return
        issue = {'severity': severity, 'message': message, 'line': line, 'count': 1,
                 'event': event_ref(event) if event else None}
        self._seen[key] = issue
        self.issues.append(issue)


def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'show'


def valid_url(value: str) -> str | None:
    """Returns an error message, or None if the URL is acceptable."""
    if not re.fullmatch(r'https?://[^\s<>"]+\.[^\s<>"]+', value):
        return f'"{value}" is not a web address; it should start with https://'
    return None


# ---------------------------------------------------------------- shows

@dataclass
class _Block:
    dates: str | None = None
    line: int | None = None
    starts: list = field(default_factory=list)
    doors: list = field(default_factory=list)
    ends: list = field(default_factory=list)
    status: object = None


def show_fields(event: Event, notes: Notes, rep: Reporter) -> dict:
    fields: dict[str, str] = {}
    for key in SINGLE_FIELDS:
        entries = [e for e in notes.entries if e.key == key]
        if not entries:
            continue
        for extra in entries[1:]:
            rep.add(event, 'warning', f'second "{key}:" line ignored; only the first is used', extra.line)
        value = entries[0].value
        if key in URL_FIELDS:
            problem = valid_url(value)
            if problem:
                rep.add(event, 'error', f'{key}: {problem}, so it is not published', entries[0].line)
                continue
            if value.startswith('http://'):
                rep.add(event, 'warning', f'{key}: link starts with http://, not https://; check it works',
                        entries[0].line)
        fields[key] = value
    if 'title' not in fields:
        if not event.summary:
            rep.add(event, 'error', 'no "title:" line and the calendar entry has no title, so it is not published')
            return {}
        fields['title'] = event.summary
    return fields


def show_performances(event: Event, notes: Notes, rep: Reporter) -> list[Performance]:
    defaults = _Block()
    blocks: list[_Block] = []
    cur = defaults
    for e in notes.entries:
        if e.key == 'dates':
            cur = _Block(dates=e.value, line=e.line)
            blocks.append(cur)
        elif e.key == 'show starts':
            cur.starts.append(e)
        elif e.key == 'doors open':
            cur.doors.append(e)
        elif e.key == 'show ends':
            cur.ends.append(e)
        elif e.key == 'status':
            if cur.status:
                rep.add(event, 'error', 'two "status:" lines for the same dates; only the first is used', e.line)
            else:
                cur.status = e
    if not blocks:
        blocks = [defaults]

    def times(entries) -> list[dt.time]:
        out = []
        for e in entries:
            try:
                out += parse_times(e.value)
            except ParseError as err:
                rep.add(event, 'error', f'{e.key}: {err}', e.line)
        return out

    all_days = [event.first_day + dt.timedelta(days=i)
                for i in range((event.last_day - event.first_day).days + 1)]
    perfs: dict[tuple, Performance] = {}
    claimed: dict[dt.date, _Block] = {}     # which block each date belongs to
    warned_no_time = False
    for b in blocks:
        if b.dates is None:
            dates = all_days
        else:
            try:
                dates, problems = parse_dates(b.dates, event.first_day, event.last_day)
            except ParseError as err:
                rep.add(event, 'error', f'dates: {err}', b.line)
                continue
            for p in problems:
                rep.add(event, 'error', f'dates: {b.dates}: {p}', b.line)
        overlap = [d for d in dates if d in claimed]
        if overlap:
            firsts = sorted({claimed[d].line for d in overlap})
            rep.add(event, 'error', f'dates: {b.dates}: {format_date_list(overlap)} '
                                    f'{"is" if len(overlap) == 1 else "are"} already covered by the "dates:" line '
                                    f'on line {", ".join(map(str, firsts))}; those dates keep the earlier times. '
                                    'Give each date only one "dates:" line (list two shows a day as '
                                    '"show starts: 2pm, 7.30pm")', b.line)
            dates = [d for d in dates if d not in claimed]
        for d in dates:
            claimed[d] = b

        start_lines = b.starts or defaults.starts
        starts = times(start_lines)
        doors = times(b.doors or defaults.doors)
        ends = times(b.ends or defaults.ends)
        if not starts:
            if not start_lines and not warned_no_time:
                rep.add(event, 'warning', 'no "show starts:" line, so no performance times are shown')
                warned_no_time = True
            starts = [None]
            if doors and not start_lines:
                rep.add(event, 'error', '"doors open:" without "show starts:"; doors time not shown')
                doors = []
            if ends and not start_lines:
                rep.add(event, 'error', '"show ends:" without "show starts:"; end time not shown')
                ends = []
        if doors and len(doors) not in (1, len(starts)):
            rep.add(event, 'error', f'"doors open:" lists {len(doors)} times but "show starts:" lists '
                                    f'{len(starts)}; doors times not shown')
            doors = []
        if ends and len(ends) not in (1, len(starts)):
            rep.add(event, 'error', f'"show ends:" lists {len(ends)} times but "show starts:" lists '
                                    f'{len(starts)}; end times not shown')
            ends = []
        if len(doors) == 1:
            doors = doors * len(starts)
        if len(ends) == 1:
            ends = ends * len(starts)
        for i, (s, e) in enumerate(zip(starts, ends)):
            if s is not None and e is not None and e <= s:
                rep.add(event, 'error', f'show ends at {format_time(e)}, not after it starts at '
                                        f'{format_time(s)}; end time not shown')
                ends[i] = None
        for i, (s, d) in enumerate(zip(starts, doors)):
            if s is not None and d is not None and d > s:
                rep.add(event, 'error', f'doors open at {format_time(d)}, after the show starts at '
                                        f'{format_time(s)}; doors time not shown')
                doors[i] = None

        status_entry = b.status or defaults.status
        status = None
        if status_entry:
            status = STATUSES.get(status_entry.value.lower())
            if status is None:
                rep.add(event, 'error', f'status: "{status_entry.value}" is not one of: '
                                        f'{", ".join(sorted(set(STATUSES) - {"canceled"}))}', status_entry.line)

        for day in dates:
            for i, s in enumerate(starts):
                perfs.setdefault((day, s), Performance(day, s, doors[i] if doors else None, status,
                                                       ends[i] if ends else None))
    return sorted(perfs.values(), key=lambda p: (p.date, p.start or dt.time(0)))


def schedule_lines(perfs: list[Performance]) -> list[dict]:
    """Compact human summary: [{dates: "Fri 14 – Sat 21 Nov", time: "7.30pm", doors: "7pm", status}]."""
    groups: dict[tuple, list[dt.date]] = {}
    for p in perfs:
        groups.setdefault((p.start, p.doors, p.status, p.end), []).append(p.date)
    lines = []
    for (start, doors, status, end), dates in sorted(groups.items(), key=lambda kv: (min(kv[1]), kv[0][0] or dt.time(0))):
        time = format_time(start)
        if start and end:
            time += f' – {format_time(end)}'
        lines.append({
            'dates': ', '.join(format_date_range(a, b) for a, b in date_runs(dates)),
            'time': time,
            'doors': format_time(doors),
            'status': status or '',
        })
    return lines


def _near_misses_published(event: Event, notes: Notes, rep: Reporter):
    for line, text, key in notes.loose_keys:
        if key == 'ticket prices' and not text.lower().startswith('ticket'):
            rep.add(event, 'warning', f'"{text}" is not published. If it is the ticket price, '
                                      f'write it as "ticket prices: …"', line)
        else:
            rep.add(event, 'warning', f'"{text}" looks like "{key}:" but is not written that way, '
                                      f'so it is not published', line)
    if 'hide' in notes.flags:
        rep.add(event, 'warning', 'HIDE only applies to regular classes; ignored on a published show')


# ---------------------------------------------------------------- regulars

def match_rule(summary: str, rules: list[Rule]) -> Rule | None:
    s = summary.lower()
    hits = [r for r in rules if r.match.strip() and r.match.strip().lower() in s]
    return max(hits, key=lambda r: len(r.match)) if hits else None


def similar_rule(summary: str, rules: list[Rule]) -> Rule | None:
    s = summary.lower()
    for r in rules:
        m = r.match.strip().lower()
        if not m:
            continue
        if difflib.SequenceMatcher(None, m, s).ratio() >= 0.75 or \
                difflib.SequenceMatcher(None, m, s[:len(m) + 2]).ratio() >= 0.8:
            return r
    return None


# ---------------------------------------------------------------- build

def venue_of(event: Event, venues: dict[str, str]) -> str | None:
    return venues.get(event.raw.get('colorId', ''))


def build(events: list[Event], rules: list[Rule], now: dt.datetime, sync_info: dict | None = None,
          venues: dict[str, str] | None = None) -> Output:
    venues = DEFAULT_VENUES if venues is None else venues
    tz: ZoneInfo = now.tzinfo
    today = now.date()
    week_start = today - dt.timedelta(days=today.weekday())
    regulars_end = week_start + dt.timedelta(weeks=REGULAR_WEEKS)
    horizon = today + dt.timedelta(days=SHOW_HORIZON_DAYS)
    rep = Reporter()

    shows: dict[str, dict] = {}
    published: list[dict] = []
    sessions: list[dict] = []
    rule_use: dict[int, list[dt.date]] = {r.id: [] for r in rules}
    unmatched: dict[str, dict] = {}

    def is_future(p: Performance) -> bool:
        when = dt.datetime.combine(p.date, p.start or dt.time(23, 59), tz)
        return when >= now and p.date <= horizon

    for event in sorted(events, key=lambda e: (e.first_day, e.summary)):
        if event.last_day < today:
            continue
        notes = parse_notes(event.description)

        if 'publish' in notes.flags:
            for issue in notes.issues:
                rep.add(event, issue.severity, issue.message, issue.line)
            _near_misses_published(event, notes, rep)
            fields = show_fields(event, notes, rep)
            if not fields:
                continue
            venue = venue_of(event, venues)
            if venue:
                fields['venue'] = venue
            else:
                colour = event.raw.get('colorId')
                rep.add(event, 'warning', 'the calendar entry has no venue colour, so no venue is shown' if not colour
                        else f'colour "{COLOUR_NAMES.get(colour, colour)}" is not a venue colour, so no venue is shown')
            perfs = show_performances(event, notes, rep)
            future = [p for p in perfs if is_future(p)]
            published.append({
                'event': event_ref(event),
                'public': {k: v for k, v in fields.items()},
                'featured': 'featured' in notes.flags,
                'schedule': schedule_lines(future),
                'private': notes.private_lines,
            })
            if not future:
                if perfs:
                    rep.add(event, 'info', 'all performances have finished')
                continue
            key = fields['title'].strip().lower()
            show = shows.get(key)
            if show is None:
                shows[key] = {'fields': fields, 'perfs': perfs, 'featured': 'featured' in notes.flags}
            else:
                for k, v in fields.items():
                    if show['fields'].get(k, v) != v:
                        rep.add(event, 'warning', f'another calendar entry for "{fields["title"]}" has a different '
                                                  f'{k}: "{show["fields"][k]}" is used')
                    show['fields'].setdefault(k, v)
                show['perfs'] += perfs
                show['featured'] |= 'featured' in notes.flags
            continue

        rule = match_rule(event.summary, rules)
        if rule:
            if not (today <= event.first_day < regulars_end):
                continue
            rule_use[rule.id].append(event.first_day)
            if 'hide' in notes.flags:
                rep.add(event, 'info', f'hidden from the timetable on {format_date(event.first_day)} (HIDE)')
                continue
            if event.all_day:
                rep.add(event, 'error', f'matches regular "{rule.name}" but is an all-day entry, so has no time; '
                                        'not shown in the timetable')
                continue
            status = None
            st = notes.first('status')
            if st:
                status = STATUSES.get(st.value.lower())
                if status is None:
                    rep.add(event, 'error', f'status: "{st.value}" is not one of: cancelled, sold out, '
                                            'few tickets left, selling fast', st.line)
            if notes.has_show_keywords() or notes.publish_like:
                rep.add(event, 'warning', f'matches regular "{rule.name}" but has show details; add PUBLISH on '
                                          'its own line if it should be listed as a show')
            sessions.append({
                'date': event.first_day.isoformat(),
                'time': format_time(event.start.time()),
                'start': event.start.strftime('%H:%M'),
                'end': event.end.strftime('%H:%M'),
                'name': rule.name,
                'venue': venue_of(event, venues) or '',
                'activity': rule.activity,
                'websiteUrl': rule.website,
                'status': status or '',
            })
            continue

        # Not published: report near misses only.
        for line, text in notes.publish_like:
            rep.add(event, 'warning', f'"{text}" mentions publishing, but PUBLISH must be on a line by itself; '
                                      'not published', line)
        if not notes.publish_like and notes.has_show_keywords():
            keys = sorted({e.key + ':' for e in notes.entries if e.key in SHOW_KEYWORDS})
            rep.add(event, 'warning', f'has show details ({", ".join(keys)}) but no PUBLISH line, so not published')
        if 'featured' in notes.flags:
            rep.add(event, 'warning', 'FEATURED has no effect without a PUBLISH line')
        if today <= event.first_day < regulars_end and event.summary:
            # Regular classes are often separate entries with the same title
            # rather than a repeating event, so group by title.
            similar = similar_rule(event.summary, rules)
            if similar:
                rep.add(event, 'warning', f'looks like regular "{similar.name}", but the title doesn\'t contain '
                                          f'"{similar.match}", so it is not in the timetable',
                        group=event.summary.lower())
            else:
                u = unmatched.setdefault(event.summary.lower(), {'title': event.summary, 'count': 0,
                                                                 'next': event.when(), 'link': event.html_link,
                                                                 'recurring': False})
                u['count'] += 1
                u['recurring'] |= bool(event.recurring_id)

    for r in rules:
        if not rule_use[r.id]:
            rep.add(None, 'info', f'regular "{r.name}": no calendar entries containing "{r.match}" in the next '
                                  f'{REGULAR_WEEKS} weeks')

    # Public shows.
    show_list = []
    for show in shows.values():
        f = show['fields']
        perfs = sorted(show['perfs'], key=lambda p: (p.date, p.start or dt.time(0)))
        future = [p for p in perfs if is_future(p)]
        statuses = {p.status for p in future}
        item = {
            'id': f'{_slug(f["title"])}-{perfs[0].date.isoformat()}',
            'title': f['title'],
            'startDate': perfs[0].date.isoformat(),
            'endDate': perfs[-1].date.isoformat(),
            'featured': show['featured'],
            'status': (next(iter(statuses)) or '') if len(statuses) == 1 else '',
            'schedule': schedule_lines(future),
            'performances': [{'date': p.date.isoformat(),
                              'start': p.start.strftime('%H:%M') if p.start else None,
                              'doors': p.doors.strftime('%H:%M') if p.doors else None,
                              'end': p.end.strftime('%H:%M') if p.end else None,
                              'status': p.status or ''} for p in future],
        }
        for k, v in f.items():
            if k != 'title':
                item[JSON_NAMES.get(k, k)] = v
        show_list.append((future[0].date, future[0].start or dt.time(0), item))
    show_list.sort(key=lambda t: (t[0], t[1]))

    generated = now.isoformat(timespec='seconds')
    sessions.sort(key=lambda s: (s['date'], s['start'], s['name']))
    rank = {'error': 0, 'warning': 1, 'info': 2}
    issues = sorted(rep.issues, key=lambda i: rank[i['severity']])
    return Output(
        shows={'generated': generated, 'shows': [t[2] for t in show_list]},
        regulars={'generated': generated, 'from': week_start.isoformat(),
                  'to': (regulars_end - dt.timedelta(days=1)).isoformat(), 'sessions': sessions},
        report={
            'generated': generated,
            'sync': sync_info or {},
            'issues': issues,
            'counts': {s: sum(1 for i in issues if i['severity'] == s) for s in rank},
            'published': published,
            'regulars': [{'rule': r, 'sessions': len(rule_use[r.id]),
                          'next': format_date(min(rule_use[r.id])) if rule_use[r.id] else ''} for r in rules],
            'unmatched': sorted(({k: v for k, v in u.items() if k != 'recurring'} for u in unmatched.values()
                                 if u['count'] >= 2 or u['recurring']), key=lambda u: u['title'].lower()),
        },
    )
