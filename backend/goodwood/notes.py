"""Reading the annotations staff put in a calendar event's notes.

The confidentiality rule lives here: the only things that come out of the notes
are flag lines (PUBLISH, FEATURED, HIDE) and the single-line values of known
keywords.  Every other line is private and is only ever shown on the staff
admin page.
"""
from __future__ import annotations

import difflib
import html
import re
from dataclasses import dataclass, field

# Lines that are a single word on their own.
FLAGS = {'publish', 'featured', 'hide'}

# Canonical keyword -> accepted spellings.  Deliberately no generic words like
# "notes", "info", "description" or "price": those are likely to already be in
# use for private details (e.g. the hire price).
KEYWORDS: dict[str, list[str]] = {
    'title': ['title'],
    'company': ['company', 'presented by'],
    'dates': ['dates', 'date'],
    'doors open': ['doors open', 'doors'],
    'show starts': ['show starts', 'show start', 'starts', 'start time', 'show time', 'showtime', 'curtain up'],
    'show ends': ['show ends', 'show end', 'ends', 'finish', 'finish time', 'finishes'],
    'tickets': ['tickets', 'ticket link', 'tickets link'],
    'ticket prices': ['ticket prices', 'ticket price'],
    'image': ['image', 'poster'],
    'website': ['website', 'web site'],
    'summary': ['summary', 'blurb'],
    'suitable for': ['suitable for', 'ages'],
    'duration': ['duration', 'running time'],
    'status': ['status'],
}
ALIASES = {alias: key for key, aliases in KEYWORDS.items() for alias in aliases}

# Keywords that only make sense for a show; seeing them without PUBLISH is a near miss.
SHOW_KEYWORDS = {'dates', 'doors open', 'show starts', 'show ends', 'tickets', 'ticket prices', 'image'}

# Not keywords (probably the hire price), but worth a hint on a published show.
PRICE_WORDS = {'price': 'ticket prices', 'prices': 'ticket prices', 'cost': 'ticket prices'}

# Caps stop a pasted private paragraph from going public under a keyword.  Web
# addresses (often very long, e.g. image links) are only checked for being URLs.
MAX_LENGTH = {'summary': 400, 'tickets': 2000, 'image': 2000, 'website': 2000}
DEFAULT_MAX_LENGTH = 120

_KEY_LINE = re.compile(r'^([A-Za-z][A-Za-z ]{0,24}?)\s*:\s*(.*)$')
_LOOSE_KEY_LINE = re.compile(r'^([A-Za-z][A-Za-z ]{0,24}?)\s*(?:[:=]|\s[-–—]\s|\s-|-\s)\s*(.*)$')
_TIME_FIRST = re.compile(r'^(\d{1,2}(?:[.:]\d\d)?\s*(?:am|pm))\s+(?:approx\.?\s+|approximate\s+)?([a-z ]+?)[;,.]?$')
_BULLET = re.compile(r'^\s*(?:[-*•·]\s+)')
_CONTROL = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')


@dataclass
class Entry:
    key: str            # canonical keyword
    value: str
    line: int           # 1-based line number in the notes


@dataclass
class Issue:
    severity: str       # 'error' | 'warning' | 'info'
    message: str
    line: int | None = None


@dataclass
class Notes:
    flags: set[str] = field(default_factory=set)
    entries: list[Entry] = field(default_factory=list)
    private_lines: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    publish_like: list[tuple[int, str]] = field(default_factory=list)   # near-miss PUBLISH lines
    loose_keys: list[tuple[int, str, str]] = field(default_factory=list)  # (line, text, suggested key)

    def first(self, key: str) -> Entry | None:
        return next((e for e in self.entries if e.key == key), None)

    def has_show_keywords(self) -> bool:
        return any(e.key in SHOW_KEYWORDS for e in self.entries)


def notes_to_text(description: str | None) -> str:
    """Google Calendar stores notes typed in its web UI as HTML; turn that into lines."""
    if not description:
        return ''
    s = description
    if re.search(r'<[a-zA-Z/][^>]*>', s):
        # Links become their target URL when it is a web address, so
        # "tickets: <a href=...>Book here</a>" still yields the URL.
        def link(m: re.Match) -> str:
            href = html.unescape(m.group(1))
            return href if re.match(r'https?://', href) else m.group(2)
        s = re.sub(r'<a\b[^>]*?href\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>', link, s, flags=re.I | re.S)
        s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
        s = re.sub(r'</?(?:p|div|li|ul|ol|h\d|tr|table)\b[^>]*>', '\n', s, flags=re.I)
        s = re.sub(r'<[^>]+>', '', s)
        s = html.unescape(s)
    s = s.replace('\xa0', ' ').replace('\r\n', '\n').replace('\r', '\n')
    return s


def _clean(value: str) -> str:
    return re.sub(r'\s+', ' ', _CONTROL.sub('', value)).strip()


def _closest_key(word: str) -> str | None:
    match = difflib.get_close_matches(word, list(ALIASES), n=1, cutoff=0.75)
    return ALIASES[match[0]] if match else None


def parse_notes(description: str | None) -> Notes:
    notes = Notes()
    for lineno, raw in enumerate(notes_to_text(description).split('\n'), start=1):
        line = _clean(_BULLET.sub('', raw))
        if not line:
            continue
        lower = line.lower()

        if lower in FLAGS:
            notes.flags.add(lower)
            continue

        m = _KEY_LINE.match(line)
        if m:
            alias = _clean(m.group(1)).lower()
            key = ALIASES.get(alias)
            if key:
                value = _clean(m.group(2)).rstrip(';,. ')
                if not value:
                    notes.issues.append(Issue('warning', f'"{line}" has nothing after the colon', lineno))
                    continue
                limit = MAX_LENGTH.get(key, DEFAULT_MAX_LENGTH)
                if len(value) > limit:
                    notes.issues.append(Issue('error', f'{key}: is longer than {limit} characters, so it is not '
                                                       'published; shorten it', lineno))
                    notes.private_lines.append(line)
                    continue
                notes.entries.append(Entry(key, value, lineno))
                continue

        # Everything below is private.  Look for near misses.
        notes.private_lines.append(line)
        if re.search(r'\bpublish', lower):
            notes.publish_like.append((lineno, line))
            continue
        m = _LOOSE_KEY_LINE.match(line)
        if m:
            word = _clean(m.group(1)).lower()
            key = ALIASES.get(word) or PRICE_WORDS.get(word) or _closest_key(word)
            if key:
                notes.loose_keys.append((lineno, line, key))
                continue
        for alias, key in ALIASES.items():
            if len(alias) >= 5 and lower.startswith(alias + ' ') and key in SHOW_KEYWORDS:
                notes.loose_keys.append((lineno, line, key))
                break
        else:
            # Time first, as in "5:45pm doors open;" or "6:30pm show time".
            m = _TIME_FIRST.match(lower)
            if m and m.group(2) in ALIASES and ALIASES[m.group(2)] in SHOW_KEYWORDS:
                notes.loose_keys.append((lineno, line, ALIASES[m.group(2)]))
    return notes
