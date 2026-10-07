# Goodwood Institute website

Static site, no build step. Design source: "2a Playbill with curtain".

## Files
- `index.html`: page structure, static copy (hire, contact, footer)
- `styles.css`: all styling; brand colours are CSS variables in `:root` (curtain uses `--curtain-*`)
- `app.js`: loads `/api/shows.json` and `/api/regulars.json` from the backend (`../backend`) and renders the featured show, upcoming list and 4-week class timetable
- `data/*.json`: the original design's sample data; no longer used
- `docs/rates-2026-2027.pdf`: hire rates

Must be served over HTTP with the backend's `/api/` alongside (see `../backend/README.md`; in development the backend serves this directory too).

## Content

Shows and classes come from the Institute's Google Calendar. See `../backend/README.md`, and the staff guide at `/admin/guide`.

## Details
- Domain: goodwoodinstitute.asn.au
- Phone: 8272 3036 (`tel:+61882723036`)
- Fonts: Marcellus (headings), Libre Franklin (body), from Google Fonts
