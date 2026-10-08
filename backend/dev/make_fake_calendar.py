"""Write dev/calendar.json (fake Google Calendar events, dated relative to today)
and add sample regulars to the development database.

    .venv/bin/python dev/make_fake_calendar.py
"""
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from goodwood.publish import Rule  # noqa: E402
from goodwood.store import Store  # noqa: E402

TZ = ZoneInfo('Australia/Adelaide')
today = dt.date.today()
monday = today - dt.timedelta(days=today.weekday())
items = []


def add(summary, start, end, notes='', recurring=None):
    n = len(items) + 1

    def when(v):
        if isinstance(v, dt.datetime):
            return {'dateTime': v.replace(tzinfo=TZ).isoformat(), 'timeZone': 'Australia/Adelaide'}
        return {'date': v.isoformat()}
    item = {'id': f'dev{n}', 'status': 'confirmed', 'summary': summary, 'description': notes,
            'start': when(start), 'end': when(end), 'htmlLink': f'https://calendar.google.com/calendar/event?eid=dev{n}'}
    if recurring:
        item['recurringEventId'] = recurring
    items.append(item)


def at(day, hhmm):
    h, m = map(int, hhmm.split(':'))
    return dt.datetime.combine(day, dt.time(h, m))


def next_weekday(wd, weeks=0):
    return monday + dt.timedelta(days=wd, weeks=weeks)


# A three-week run with a Sunday matinee, as one multi-day all-day entry.
run_start = next_weekday(4, 3)          # Friday, 3 weeks out
run_end = run_start + dt.timedelta(days=9)
add('Earnest - Sample Theatre Co (hire)', run_start, run_end + dt.timedelta(days=1), """Hirer: Jane Smith 0400 123 456
Invoice 1234 - deposit paid, balance due 1 week before
Price: $1,200 hire + $500 bond
PUBLISH
FEATURED
title: The Importance of Being Earnest
company: Sample Theatre Company
dates: Mon–Sat
doors open: 7pm
show starts: 7.30pm
dates: Sundays
doors open: 1.30pm
show starts: 2pm
tickets: https://example.com/tickets
ticket prices: $25 / $20 concession
summary: Oscar Wilde's comedy of mistaken identity and cucumber sandwiches.
suitable for: All ages
duration: 2 hours 20 minutes including interval""")

# A single evening, entered as a timed event, notes written in Google's HTML.
carols = next_weekday(5, 9)
add('Carols', at(carols, '17:00'), at(carols, '22:00'),
    'PUBLISH<br>title: Christmas Carols Concert<br>company: Sample Community Choir<br>'
    'show starts: 7pm<br>website: <a href="https://example.com/choir">example.com/choir</a>')

# A published show with mistakes in it.
dance = next_weekday(4, 6)
add('Dance showcase', dance, dance + dt.timedelta(days=2), """PUBLISH
title: Summer Dance Showcase
company: Sample Dance School
show starts: 7
doors open: 6.30pm
tickets: trybooking.com/sample
dates: Fri, Sat, Sun""")

# Near misses: forgot PUBLISH, and wrote it wrong.
add('Comedy night', at(next_weekday(5, 4), '18:00'), at(next_weekday(5, 4), '23:00'),
    'Contact: Bob 0411 111 111\nshow starts: 8pm\ntickets: https://example.com/comedy')
add('Magic show', at(next_weekday(6, 5), '13:00'), at(next_weekday(6, 5), '17:00'),
    'Publish: yes please\nshow starts: 2pm')

# Private bookings.
add('Smith 50th birthday', at(next_weekday(5, 1), '18:00'), at(next_weekday(5, 1), '23:30'),
    'Contact: Mrs Smith 0422 222 222. Bond paid.')
add('Bump in - Earnest', at(run_start - dt.timedelta(days=1), '09:00'), at(run_start - dt.timedelta(days=1), '22:00'))

# Regulars, weekly for six weeks.
for week in range(6):
    for wd in (0, 2):
        d = next_weekday(wd, week)
        notes = 'HIDE\nTeacher away' if week == 2 and wd == 2 else ''
        add('Kanti Yoga', at(d, '18:00'), at(d, '19:15'), notes, recurring='kanti')
    for wd in (1, 3):
        d = next_weekday(wd, week)
        add('Sample Dance School - juniors (studio 1)', at(d, '16:00'), at(d, '17:30'), recurring='dance')
    d = next_weekday(2, week)
    add('Choir rehearsal', at(d, '19:30'), at(d, '21:30'),
        'status: cancelled' if week == 1 else '', recurring='choir')
    d = next_weekday(1, week)
    add('Tuesday Bridge Club', at(d, '13:00'), at(d, '16:00'), recurring='bridge')
    d = next_weekday(4, week)
    add('Kanti Yogo - Friday flow', at(d, '09:30'), at(d, '10:30'), recurring='kanti-fri')

(HERE / 'calendar.json').write_text(json.dumps({'items': items}, indent=1))
print(f'wrote {len(items)} events to {HERE / "calendar.json"}')

store = Store(HERE.parent / 'var' / 'dev.db')
if not store.rules():
    for r in [Rule(0, 'Kanti Yoga', 'Kanti Yoga', 'Hatha and restorative yoga', 'https://example.com/yoga'),
              Rule(0, 'Sample Dance School', 'Sample Dance School', 'Ballet, tap and jazz for ages 4+'),
              Rule(0, 'Choir rehearsal', 'Sample Choir', 'Community choir, all welcome'),
              Rule(0, 'Tai Chi', 'Sample Tai Chi', 'Gentle movement for seniors')]:
        store.save_rule(r)
    print('added sample regulars')
