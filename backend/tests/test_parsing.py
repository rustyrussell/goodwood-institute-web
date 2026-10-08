import datetime as dt

import pytest

from goodwood.parsing import ParseError, format_date_list, format_time, parse_dates, parse_time, parse_times

D = dt.date
NOV14, NOV22 = D(2026, 11, 14), D(2026, 11, 22)


@pytest.mark.parametrize('text,expected', [
    ('7pm', dt.time(19, 0)), ('7.30pm', dt.time(19, 30)), ('7:30 PM', dt.time(19, 30)),
    ('7.30 p.m.', dt.time(19, 30)), ('19:30', dt.time(19, 30)), ('09:30', dt.time(9, 30)),
    ('12pm', dt.time(12, 0)), ('12am', dt.time(0, 0)), ('noon', dt.time(12, 0)), ('10am', dt.time(10, 0)),
])
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize('text', ['7.30', '7', '13pm', '7.75pm', 'evening', '25:00'])
def test_parse_time_rejects(text):
    with pytest.raises(ParseError):
        parse_time(text)


def test_parse_times_list():
    assert parse_times('2pm, 7.30pm') == [dt.time(14), dt.time(19, 30)]
    assert parse_times('2pm & 7.30pm') == [dt.time(14), dt.time(19, 30)]
    assert parse_times('2pm and 7.30pm') == [dt.time(14), dt.time(19, 30)]


def test_format_time():
    assert format_time(dt.time(19, 30)) == '7.30pm'
    assert format_time(dt.time(19)) == '7pm'
    assert format_time(dt.time(12)) == '12 noon'
    assert format_time(dt.time(9, 5)) == '9.05am'


def days(a, b):
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


@pytest.mark.parametrize('text,expected', [
    ('14–22 Nov', days(NOV14, NOV22)),
    ('14-22 nov', days(NOV14, NOV22)),
    ('14 Nov - 16 Nov', days(NOV14, D(2026, 11, 16))),
    ('Sat 14 Nov', [NOV14]),
    ('Sat 21 & Sun 22 Nov', [D(2026, 11, 21), NOV22]),
    ('21, 22 November', [D(2026, 11, 21), NOV22]),
    ('Sundays', [D(2026, 11, 15), NOV22]),
    ('Sun', [D(2026, 11, 15), NOV22]),
    ('Fri–Sat', [NOV14, D(2026, 11, 20), D(2026, 11, 21)]),
    ('14/11, 21/11/2026', [NOV14, D(2026, 11, 21)]),
    ('2026-11-14', [NOV14]),
    ('14th Nov', [NOV14]),
    ('Sundays, 14 Nov', [NOV14, D(2026, 11, 15), NOV22]),
    ('Sept 1', None),
])
def test_parse_dates(text, expected):
    if expected is None:
        with pytest.raises(ParseError):
            parse_dates(text, NOV14, NOV22)
        return
    dates, problems = parse_dates(text, NOV14, NOV22)
    assert problems == []
    assert dates == expected


def test_parse_dates_across_year_end():
    dates, problems = parse_dates('30 Dec – 2 Jan', D(2026, 12, 28), D(2027, 1, 5))
    assert problems == []
    assert dates == days(D(2026, 12, 30), D(2027, 1, 2))


def test_parse_dates_outside_span_is_reported():
    dates, problems = parse_dates('20–25 Nov', NOV14, NOV22)
    assert dates == days(D(2026, 11, 20), NOV22)
    assert len(problems) == 1 and 'outside' in problems[0] and '23' in problems[0]


def test_parse_dates_nothing_inside():
    dates, problems = parse_dates('1 Dec', NOV14, NOV22)
    assert dates == []
    assert any('none of these' in p for p in problems)


@pytest.mark.parametrize('text,fragment', [
    ('Fri 14 Nov', 'is a Saturday'),
    ('14', 'needs a month'),
    ('31 Nov', 'not a real date'),
    ('22–14 Nov', 'ends before'),
    ('Thu–14 Nov', 'mixes'),
    ('next week', 'not a date'),
])
def test_parse_dates_errors(text, fragment):
    with pytest.raises(ParseError, match=fragment):
        parse_dates(text, NOV14, NOV22)


def test_format_date_list():
    assert format_date_list([NOV14, D(2026, 11, 15), NOV22]) == 'Sat 14 Nov – Sun 15 Nov, Sun 22 Nov'


def test_parse_dates_missing_weekday_reported():
    dates, problems = parse_dates('Fri, Sun', D(2026, 11, 20), D(2026, 11, 21))
    assert dates == [D(2026, 11, 20)]
    assert problems == ['there is no Sunday in the calendar entry (Fri 20 Nov – Sat 21 Nov)']
