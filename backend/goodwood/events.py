"""Calendar events, as stored from the Google Calendar API (v3 Event resources)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .parsing import format_date_range, format_time


@dataclass
class Event:
    id: str
    summary: str
    description: str
    start: dt.datetime | dt.date        # aware datetime in local tz, or date for all-day
    end: dt.datetime | dt.date          # exclusive, as Google gives it
    recurring_id: str | None
    html_link: str
    raw: dict

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, dt.datetime)

    @property
    def first_day(self) -> dt.date:
        return self.start if self.all_day else self.start.date()

    @property
    def last_day(self) -> dt.date:
        """Last day the event covers (inclusive)."""
        if self.all_day:
            return max(self.start, self.end - dt.timedelta(days=1))
        return max(self.start.date(), (self.end - dt.timedelta(microseconds=1)).date())

    @property
    def series_id(self) -> str:
        """Same for every occurrence of a recurring event."""
        return self.recurring_id or self.id

    def when(self) -> str:
        days = format_date_range(self.first_day, self.last_day)
        if self.all_day:
            return days
        return f'{days}, {format_time(self.start.time())}'


def _parse_when(when: dict, tz: ZoneInfo) -> dt.datetime | dt.date:
    if 'dateTime' in when:
        return dt.datetime.fromisoformat(when['dateTime']).astimezone(tz)
    return dt.date.fromisoformat(when['date'])


def event_from_api(item: dict, tz: ZoneInfo) -> Event:
    return Event(
        id=item['id'],
        summary=(item.get('summary') or '').strip(),
        description=item.get('description') or '',
        start=_parse_when(item['start'], tz),
        end=_parse_when(item['end'], tz),
        recurring_id=item.get('recurringEventId'),
        html_link=item.get('htmlLink', ''),
        raw=item,
    )
