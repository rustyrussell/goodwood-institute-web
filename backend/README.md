# Goodwood website backend

Reads the Institute's Google Calendar and publishes:

- `/api/shows.json`: entries whose notes contain `Publish to website`, built only from recognised\n  instructions below that marker (earlier notes and unrecognised fields stay private);
- `/api/regulars.json`: the rest of the calendar month of regular classes, matched by title against
  rules kept in the admin page;
- `/admin/`: staff status page (problems, near misses, exactly what is published, regulars
  editor) and `/admin/guide`, the notes cheat sheet for whoever edits the calendar.

The calendar is read on demand: a request finds the data more than 30 seconds old, a background
incremental sync (Google sync tokens) fetches only what changed, and visitors are always served
the last good data immediately. If Google is unreachable the site keeps showing the last data and
the admin page shows the error.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/python dev/make_fake_calendar.py        # sample events dated from today, sample regulars
GOODWOOD_CONFIG=dev/config.toml PORT=8765 .venv/bin/python -m goodwood.app
```

Then open http://localhost:8765/ (site) and http://localhost:8765/admin/ (any username,
password `dev`). Edit `dev/calendar.json` and press *Refresh now* to see changes.

## Google Calendar setup (one-off)

The website reads the calendar as a Workspace user (e.g. bookings@), because Google hides event
colours, which mark the venue, from service accounts.

1. https://console.cloud.google.com: project `goodwood-website` (parent: the
   goodwoodinstitute.asn.au organisation), with the **Google Calendar API** enabled
   (`gcloud services enable calendar-json.googleapis.com`).
2. Google Auth Platform → Get started: app name "Goodwood website", audience **Internal**.
3. Google Auth Platform → Clients → Create client → **Desktop app** → download the JSON.
4. On a machine with a browser:
   `.venv/bin/python -m goodwood.authorize client_secret.json website-user-token.json CALENDAR_ID`
   and sign in as the account the website should use. It needs to see the bookings calendar.
5. Copy `website-user-token.json` to the server (e.g. `/etc/goodwood/`, mode 600, owned by the
   app's user) and set `[calendar] credentials` to it. The Calendar ID is in the calendar's
   Settings → Integrate calendar.

Internal apps' tokens don't expire. They stop working if the account is suspended or the access
is revoked (myaccount.google.com → Security → Third-party connections). Then rerun step 4.

Future online bookings: rerun step 4 with the `calendar.events` scope; the reader keeps its
read-only token.

## Deployment

The static site (`../site`) is served by the web server; the app runs behind it on localhost.
Run **one** worker process (the 30-second cache lives in memory) with a few threads:

```sh
GOODWOOD_CONFIG=/etc/goodwood/config.toml \
  .venv/bin/gunicorn --workers 1 --threads 4 --bind 127.0.0.1:8080 'goodwood.app:wsgi()'
```

nginx:

```nginx
location /api/   { proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host; }
location /admin/ {
    # Later: allow 192.168.x.0/24; deny all;   (staff LAN only)
    proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host;
}
```

`proxy_set_header Host $host` matters: admin form posts are checked against the Host header.
Admin uses HTTP Basic auth, so serve it over HTTPS.

## Code

| file | |
|---|---|
| `goodwood/notes.py` | Splits notes into flags, keyword values and private lines; spots near misses. The confidentiality rule lives here. |
| `goodwood/parsing.py` | Times (`7.30pm`) and date lists (`14–21 Nov`, `Sundays`, `Sat 21 & Sun 22 Nov`). |
| `goodwood/publish.py` | Builds shows, regulars and the staff report from events. |
| `goodwood/gcal.py` | Google Calendar sync (user token from `goodwood.authorize`, sync tokens) and the dev file source. |
| `goodwood/service.py` | On-demand, throttled, background refresh. |
| `goodwood/store.py` | SQLite: local copy of events, sync state, regulars rules. |
| `goodwood/app.py` | Flask routes. |
| `goodwood/authorize.py` | One-off browser sign-in that creates the user token. |

## Drafts and contact enquiries

Set `[app] include_drafts = true` **only on the test deployment**. This is
false by default, ensuring that a production deployment excludes entries with
a `DRAFT` instruction. Staff should write `Publish to website` on a line,
then optional `DRAFT`, then whitelisted show details. Other booking notes
belong above the marker and never enter public feeds.

Contact enquiries POST to `/api/contact` and are saved in the same private
SQLite database as the calendar cache. A separate systemd timer sends them
through Google Workspace's IP-allowlisted, STARTTLS-only SMTP relay, to the
**fixed** recipient `bookings@goodwoodinstitute.asn.au`. The visitor's email is
used only for Reply-To. Staff can read each item and delivery state under
`/admin/#contacts`, retry errors and mark it handled. Failed attempts retry
with backoff (up to 12); no messages are deleted on SMTP failure. The form
limits the number of submissions per hour, checks same-origin and uses a
honeypot; watch for spam. Protect the SQLite file and include it in backups.

Mail setup on CT 100 (root; do not modify production configuration in Git):

1. In Google Admin → Apps → Google Workspace → Gmail → Routing, configure an
   SMTP relay allowing **only addresses in my domains**, authenticate by the
   ABB static public IP **144.6.28.44**, require TLS, no SMTP AUTH. Do **not**
   select "Any addresses". Allow changes time to propagate.
2. In the existing private `config.toml`, add:

   ```toml
   [mail]
   smtp_host = "smtp-relay.gmail.com"
   smtp_port = 587
   from_address = "website@goodwoodinstitute.asn.au"
   to_address = "bookings@goodwoodinstitute.asn.au"
   subject_prefix = "[TEST]"
   ```

3. Install the two unit files from `deploy/` into `/etc/systemd/system/`:

   ```sh
   cp deploy/goodwood-website-mailer.{service,timer} /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now goodwood-website-mailer.timer
   ```

4. Submit one test enquiry from the public form, then run
   `systemctl start goodwood-website-mailer.service` to send immediately.
   Check `journalctl -u goodwood-website-mailer -n 50 --no-pager`, the
   `bookings@` inbox, and the admin delivery status. Confirm Reply-To points
   to the visitor. The timer then runs roughly once per minute.

Only the static ABB WAN IP is allowlisted; Telstra failover may prevent mail
until ABB returns (the worker retries). TLS verification is mandatory.
Clear the `[TEST]` subject prefix when production is ready.

Curtain colour is controlled under `/admin/#appearance` and exposed only as
a hex colour by `/api/appearance.json`. The default is oxblood `#67192B`.
