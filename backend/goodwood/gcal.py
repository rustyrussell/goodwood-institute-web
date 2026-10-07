"""Calendar sources: Google Calendar (via a service account) and a local file for development.

Both implement sync(token) -> SyncResult.  Writing to the calendar (future
online bookings) will be a separate class with its own scope, so the read
path never holds write credentials.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

READ_SCOPE = 'https://www.googleapis.com/auth/calendar.events.readonly'
API = 'https://www.googleapis.com/calendar/v3'
# How far back the initial full sync reaches.  Incremental syncs after that
# report changes to any event, wherever it is in time.
FULL_SYNC_DAYS_BACK = 7


class SyncTokenExpired(Exception):
    """Google forgot our sync token (HTTP 410): do a full sync."""


@dataclass
class SyncResult:
    items: list[dict]
    token: str | None
    full: bool


def load_credentials(credentials_file: str):
    """A service account key, or an authorised-user token from `python -m goodwood.authorize`.

    Google hides event colours (which the Institute uses for the venue) from
    service accounts, since they count as outside the organisation, so the
    authorised-user token of a Workspace account is preferred."""
    with open(credentials_file) as f:
        kind = json.load(f).get('type')
    if kind == 'service_account':
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(credentials_file, scopes=[READ_SCOPE])
    from google.oauth2.credentials import Credentials
    return Credentials.from_authorized_user_file(credentials_file, scopes=[READ_SCOPE])


class GoogleCalendar:
    def __init__(self, calendar_id: str, credentials_file: str):
        from google.auth.transport.requests import AuthorizedSession

        creds = load_credentials(credentials_file)
        self.session = AuthorizedSession(creds)
        self.calendar_id = calendar_id
        self.description = f'Google Calendar {calendar_id}'
        # Different logins can see different fields (service accounts don't get colours).
        self.identity = f'{calendar_id} as {type(creds).__module__}:{credentials_file}'

    def sync(self, token: str | None) -> SyncResult:
        params = {'singleEvents': 'true', 'maxResults': '2500'}
        if token:
            params['syncToken'] = token
        else:
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=FULL_SYNC_DAYS_BACK)
            params['timeMin'] = since.isoformat()
        items: list[dict] = []
        url = f'{API}/calendars/{urllib.parse.quote(self.calendar_id, safe="")}/events'
        while True:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 410:
                raise SyncTokenExpired()
            if resp.status_code != 200:
                try:
                    message = resp.json()['error']['message']
                except Exception:
                    message = resp.text[:300]
                raise RuntimeError(f'Google Calendar API error {resp.status_code}: {message}')
            data = resp.json()
            items += data.get('items', [])
            if 'nextPageToken' in data:
                params['pageToken'] = data['nextPageToken']
                continue
            return SyncResult(items, data.get('nextSyncToken'), full=not token)


class FileCalendar:
    """Development stand-in: a JSON file of API-shaped events ({"items": [...]}).
    Always does a full sync, so edits to the file show up on the next refresh."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.description = f'local file {self.path}'
        self.identity = self.description

    def sync(self, token: str | None) -> SyncResult:
        data = json.loads(self.path.read_text())
        return SyncResult(data['items'], None, full=True)
