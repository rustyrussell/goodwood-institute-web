"""One-off: let the website read the calendar as a Workspace user.

    .venv/bin/python -m goodwood.authorize CLIENT_SECRET.json TOKEN.json [CALENDAR_ID]

CLIENT_SECRET.json is the "Desktop app" OAuth client downloaded from Cloud
Console.  A browser opens; sign in as the account the website should use (e.g.
bookings@) and approve read-only calendar access.  The token is written to
TOKEN.json: point [calendar] credentials at it.  Given a CALENDAR_ID, the token
is tested and the number of events with a colour (venue) is reported.
"""
import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from .gcal import READ_SCOPE, GoogleCalendar


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    client_file, token_file = sys.argv[1], sys.argv[2]
    flow = InstalledAppFlow.from_client_secrets_file(client_file, scopes=[READ_SCOPE])
    creds = flow.run_local_server(port=0, prompt='consent', access_type='offline', open_browser=True)
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(creds.to_json())
    print(f'Saved token to {token_file} (keep it secret: it can read the calendar).')
    if len(sys.argv) == 4:
        items = GoogleCalendar(sys.argv[3], token_file).sync(None).items
        coloured = sum('colorId' in i for i in items)
        print(f'Test: read {len(items)} events, {coloured} with a colour.')


if __name__ == '__main__':
    main()
