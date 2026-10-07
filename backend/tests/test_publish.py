import datetime as dt
import json
from zoneinfo import ZoneInfo

from goodwood.events import event_from_api
from goodwood.notes import notes_to_text, parse_notes
from goodwood.publish import Rule, build

TZ = ZoneInfo('Australia/Adelaide')
NOW = dt.datetime(2026, 10, 7, 10, 0, tzinfo=TZ)     # a Wednesday

_n = 0


def ev(summary, start, end=None, notes='', recurring=None, colour=None):
    """Make an API-shaped event.  start/end are dates (all-day) or 'YYYY-MM-DD HH:MM'."""
    global _n
    _n += 1
    if isinstance(start, dt.date):
        when = lambda d: {'date': d.isoformat()}
        end = end or start + dt.timedelta(days=1)
    else:
        when = lambda s: {'dateTime': dt.datetime.fromisoformat(s).replace(tzinfo=TZ).isoformat()}
        end = end or start
    item = {'id': f'e{_n}', 'summary': summary, 'description': notes, 'start': when(start), 'end': when(end),
            'htmlLink': f'https://calendar.google.com/e{_n}'}
    if recurring:
        item['recurringEventId'] = recurring
    if colour:
        item['colorId'] = colour
    return event_from_api(item, TZ)


def issues(out, severity=None):
    return [i['message'] for i in out.report['issues'] if severity in (None, i['severity'])]


EARNEST = """Hirer: Jane Smith 0400 123 456
Invoice 1234 unpaid – chase!
PUBLISH
title: The Importance of Being Earnest
company: Sample Theatre Company
dates: 14–21 Nov
doors open: 7pm
show starts: 7.30pm
dates: Sun 22 Nov
doors open: 1.30pm
show starts: 2pm
tickets: https://example.com/tix
ticket prices: $25 / $20 conc
Price: $1,200 hire + $500 bond
"""


def test_show_with_matinee_block():
    e = ev('Earnest (Sample TC hire)', dt.date(2026, 11, 14), dt.date(2026, 11, 23), EARNEST)
    out = build([e], [], NOW)
    [show] = out.shows['shows']
    assert show['title'] == 'The Importance of Being Earnest'
    assert show['company'] == 'Sample Theatre Company'
    assert show['ticketsUrl'] == 'https://example.com/tix'
    assert show['ticketPrices'] == '$25 / $20 conc'
    assert show['startDate'] == '2026-11-14' and show['endDate'] == '2026-11-22'
    assert show['schedule'] == [
        {'dates': 'Sat 14 Nov – Sat 21 Nov', 'time': '7.30pm', 'doors': '7pm', 'status': ''},
        {'dates': 'Sun 22 Nov', 'time': '2pm', 'doors': '1.30pm', 'status': ''},
    ]
    assert len(show['performances']) == 9
    # The hire price line is a near miss, reported but not published.
    assert any('ticket prices' in m for m in issues(out, 'warning'))


def test_private_notes_never_published():
    e = ev('Earnest', dt.date(2026, 11, 14), dt.date(2026, 11, 23), EARNEST)
    out = build([e], [], NOW)
    public = json.dumps([out.shows, out.regulars])
    for secret in ['Jane', '0400', 'Invoice', 'chase', '1,200', 'bond', 'Sample TC hire', 'Hirer']:
        assert secret not in public
    [p] = out.report['published']
    assert 'Hirer: Jane Smith 0400 123 456' in p['private']


def test_overlapping_blocks_are_an_error():
    notes = 'PUBLISH\ndates: 14–22 Nov\nshow starts: 7.30pm\ndates: Sundays\nshow starts: 2pm'
    out = build([ev('Show', dt.date(2026, 11, 14), dt.date(2026, 11, 23), notes)], [], NOW)
    [show] = out.shows['shows']
    assert len(show['performances']) == 9         # Sundays keep the 7.30pm show only
    [err] = issues(out, 'error')
    assert 'Sun 15 Nov, Sun 22 Nov are already covered by the "dates:" line on line 2' in err


def test_multiple_shows_per_day_and_default_times():
    notes = 'PUBLISH\nshow starts: 2pm, 7.30pm\ndoors open: 1.30pm, 7pm'
    out = build([ev('Double', dt.date(2026, 11, 14), notes=notes)], [], NOW)
    [show] = out.shows['shows']
    assert [(p['start'], p['doors']) for p in show['performances']] == [('14:00', '13:30'), ('19:30', '19:00')]


def test_not_published_without_flag_but_reported():
    notes = 'Publish: yes\ntickets: https://example.com'
    out = build([ev('Show', dt.date(2026, 11, 14), notes=notes)], [], NOW)
    assert out.shows['shows'] == []
    msgs = issues(out, 'warning')
    assert any('PUBLISH must be on a line by itself' in m for m in msgs)


def test_dont_publish_is_not_publish():
    out = build([ev('Show', dt.date(2026, 11, 14), notes="Don't publish yet\nshow starts: 7pm")], [], NOW)
    assert out.shows['shows'] == []


def test_show_keywords_without_publish():
    out = build([ev('Show', dt.date(2026, 11, 14), notes='show starts: 7pm\ntickets: https://x.com/a')], [], NOW)
    assert out.shows['shows'] == []
    assert any('no PUBLISH line' in m for m in issues(out, 'warning'))


def test_publish_is_case_insensitive_and_html_notes():
    notes = 'Some private text<br>publish<br><b>show starts:</b> 7.30pm<br>tickets: <a href="https://tix.example.com/x">Book here</a>'
    out = build([ev('Show', dt.date(2026, 11, 14), notes=notes)], [], NOW)
    [show] = out.shows['shows']
    assert show['ticketsUrl'] == 'https://tix.example.com/x'
    assert show['schedule'][0]['time'] == '7.30pm'


def test_errors_are_reported():
    notes = ('PUBLISH\ndates: 14–25 Nov\nshow starts: 7.30\ndoors open: 8pm\ntickets: www.example.com\n'
             'status: nearly full\ntixkets: https://x.com')
    out = build([ev('Show', dt.date(2026, 11, 14), dt.date(2026, 11, 23), notes)], [], NOW)
    errs = issues(out, 'error')
    assert any('outside the calendar entry' in m for m in errs)
    assert any('add am or pm' in m for m in errs)
    assert any('not a web address' in m for m in errs)
    assert any('nearly full' in m for m in errs)
    assert any('"tixkets: https://x.com" looks like "tickets:"' in m for m in issues(out, 'warning'))
    assert 'ticketsUrl' not in out.shows['shows'][0]


def test_doors_after_start():
    out = build([ev('Show', dt.date(2026, 11, 14), notes='PUBLISH\ndoors open: 8pm\nshow starts: 7.30pm')], [], NOW)
    assert any('after the show starts' in m for m in issues(out, 'error'))
    assert out.shows['shows'][0]['performances'][0]['doors'] is None


def test_past_performances_dropped_and_show_kept_while_running():
    notes = 'PUBLISH\nshow starts: 7.30pm'
    out = build([ev('Running', dt.date(2026, 10, 5), dt.date(2026, 10, 9), notes)], [], NOW)
    [show] = out.shows['shows']
    assert show['startDate'] == '2026-10-05'
    assert [p['date'] for p in show['performances']] == ['2026-10-07', '2026-10-08']


def test_same_title_entries_are_grouped():
    a = ev('X', dt.date(2026, 11, 14), notes='PUBLISH\ntitle: Gala\nshow starts: 7pm')
    b = ev('Y', dt.date(2026, 11, 21), notes='PUBLISH\ntitle: Gala\nshow starts: 2pm')
    out = build([a, b], [], NOW)
    [show] = out.shows['shows']
    assert len(show['performances']) == 2


def test_featured_and_ordering():
    a = ev('A', dt.date(2026, 11, 14), notes='PUBLISH\nshow starts: 7pm')
    b = ev('B', dt.date(2026, 12, 1), notes='PUBLISH\nFEATURED\nshow starts: 7pm')
    out = build([b, a], [], NOW)
    assert [s['title'] for s in out.shows['shows']] == ['A', 'B']
    assert out.shows['shows'][1]['featured'] is True


def test_no_show_time_warns():
    out = build([ev('Show', dt.date(2026, 11, 14), notes='PUBLISH')], [], NOW)
    assert out.shows['shows'][0]['schedule'][0]['time'] == ''
    assert any('no "show starts:"' in m for m in issues(out, 'warning'))


YOGA = Rule(1, 'kanti yoga', 'Kanti Yoga', 'Hatha and restorative yoga', 'https://kanti.example.com')


def test_regulars():
    sessions = [ev('Kanti Yoga - room 2', f'2026-10-{d:02d} 18:00', f'2026-10-{d:02d} 19:00', recurring='y')
                for d in (5, 12, 19, 26)] + [
        ev('Kanti Yoga', '2026-11-02 18:00', '2026-11-02 19:00', 'HIDE', recurring='y'),
        ev('Kanti yoga', '2026-11-09 18:00', '2026-11-09 19:00', recurring='y'),   # beyond 4 weeks
    ]
    out = build(sessions, [YOGA], NOW)
    got = out.regulars['sessions']
    # The 5 Oct session is in the past; 2 Nov is hidden; 9 Nov is beyond the window.
    assert [s['date'] for s in got] == ['2026-10-12', '2026-10-19', '2026-10-26']
    assert got[0] == {'date': '2026-10-12', 'time': '6pm', 'start': '18:00', 'end': '19:00', 'name': 'Kanti Yoga',
                      'activity': 'Hatha and restorative yoga', 'websiteUrl': 'https://kanti.example.com',
                      'status': '', 'venue': ''}
    assert out.regulars['from'] == '2026-10-05' and out.regulars['to'] == '2026-11-01'
    assert 'room 2' not in json.dumps(out.regulars)


def test_regulars_near_misses_and_unmatched():
    events = [
        ev('Kanti Yogo', '2026-10-13 18:00', '2026-10-13 19:00', recurring='a'),
        ev('Kanti Yogo', '2026-10-20 18:00', '2026-10-20 19:00', recurring='a'),
        ev('Tuesday Bridge Club', '2026-10-13 13:00', '2026-10-13 16:00', recurring='b'),
        ev('Tuesday Bridge Club', '2026-10-20 13:00', '2026-10-20 16:00', recurring='b'),
    ]
    out = build(events, [YOGA], NOW)
    warnings = [i for i in out.report['issues'] if i['severity'] == 'warning']
    assert len(warnings) == 1 and 'looks like regular "Kanti Yoga"' in warnings[0]['message']
    assert warnings[0]['count'] == 2
    assert out.report['unmatched'] == [{'title': 'Tuesday Bridge Club', 'count': 2, 'next': 'Tue 13 Oct, 1pm',
                                        'link': events[2].html_link}]
    assert any('no calendar entries containing' in m for m in issues(out, 'info'))


def test_regular_cancelled_status():
    out = build([ev('Kanti Yoga', '2026-10-12 18:00', '2026-10-12 19:00', 'status: cancelled')], [YOGA], NOW)
    assert out.regulars['sessions'][0]['status'] == 'Cancelled'


def test_notes_to_text_handles_google_html():
    assert notes_to_text('a<br>b&nbsp;c<div>d</div>') .split('\n')[:3] == ['a', 'b c', 'd']


def test_overlong_value_not_published():
    n = parse_notes('PUBLISH\ntitle: ' + 'x' * 200)
    assert n.first('title') is None
    assert n.issues[0].severity == 'error'


def test_bad_show_time_does_not_claim_line_missing():
    out = build([ev('Show', dt.date(2026, 11, 14), notes='PUBLISH\nshow starts: 7\ndoors open: 6.30pm')], [], NOW)
    msgs = issues(out)
    assert any('add am or pm' in m for m in msgs)
    assert not any('no "show starts:"' in m or 'without' in m for m in msgs)


def test_show_ends_and_existing_note_styles():
    # Written the way staff already write notes, plus PUBLISH.
    notes = 'PUBLISH<br>Doors open: 6.20pm;<br>Show time: 6.30pm;<br>Show Ends: 8pm'
    out = build([ev('Readings', dt.date(2026, 11, 1), notes=notes)], [], NOW)
    [show] = out.shows['shows']
    assert show['schedule'] == [{'dates': 'Sun 1 Nov', 'time': '6.30pm – 8pm', 'doors': '6.20pm', 'status': ''}]
    assert show['performances'][0]['end'] == '20:00'


def test_time_first_lines_are_near_misses():
    notes = 'PUBLISH\n5:45pm doors open;\n6:30pm show time;\n8:00pm approx. finish time.\nDoors open 6.20pm;'
    out = build([ev('School show', dt.date(2026, 11, 18), notes=notes)], [], NOW)
    warnings = issues(out, 'warning')
    for key in ('doors open', 'show starts', 'show ends'):
        assert any(f'looks like "{key}:"' in m for m in warnings), key
    assert sum('looks like "doors open:"' in m for m in warnings) == 2


def test_show_ends_before_start():
    out = build([ev('S', dt.date(2026, 11, 1), notes='PUBLISH\nshow starts: 7pm\nshow ends: 6pm')], [], NOW)
    assert any('not after it starts' in m for m in issues(out, 'error'))


def test_repeated_titles_without_recurrence_are_regular_candidates():
    events = [ev('Tuesday Bridge Club', f'2026-10-{d} 13:00', f'2026-10-{d} 16:00') for d in (13, 20, 27)]
    events += [ev('One-off party', '2026-10-17 18:00', '2026-10-17 23:00')]
    events += [ev('Kanti Yogo', f'2026-10-{d} 18:00', f'2026-10-{d} 19:00') for d in (12, 19)]
    out = build(events, [YOGA], NOW)
    assert [u['title'] for u in out.report['unmatched']] == ['Tuesday Bridge Club']
    [w] = [i for i in out.report['issues'] if 'looks like regular' in i['message']]
    assert w['count'] == 2


def test_venue_from_colour():
    a = ev('A', dt.date(2026, 11, 14), notes='PUBLISH\nshow starts: 7pm', colour='7')
    b = ev('B', dt.date(2026, 11, 15), notes='PUBLISH\nshow starts: 7pm', colour='11')
    c = ev('C', dt.date(2026, 11, 16), notes='PUBLISH\nshow starts: 7pm', colour='5')
    d = ev('D', dt.date(2026, 11, 17), notes='PUBLISH\nshow starts: 7pm')
    out = build([a, b, c, d], [], NOW)
    assert [s.get('venue') for s in out.shows['shows']] == ['Studio Theatre', 'Main Theatre', None, None]
    warnings = issues(out, 'warning')
    assert any('"banana" is not a venue colour' in m for m in warnings)
    assert any('no venue colour' in m for m in warnings)


def test_venue_mapping_is_configurable_and_on_regulars():
    out = build([ev('Kanti Yoga', '2026-10-12 18:00', '2026-10-12 19:00', colour='5')], [YOGA], NOW,
                venues={'5': 'Foyer'})
    assert out.regulars['sessions'][0]['venue'] == 'Foyer'


def test_long_urls_are_published():
    url = 'https://lh3.googleusercontent.com/d/' + 'x' * 300
    out = build([ev('S', dt.date(2026, 11, 1), notes=f'PUBLISH\nimage: {url}\ntickets: {url}')], [], NOW)
    assert out.shows['shows'][0]['image'] == url
    assert out.shows['shows'][0]['ticketsUrl'] == url
    assert issues(out, 'error') == []
