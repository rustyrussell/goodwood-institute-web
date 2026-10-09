"""Reading the annotations staff put in a calendar event's notes.

The confidentiality rule lives here: the only things that come out of the notes
are explicitly named fields after a 'Publish to website' marker.
Everything before that marker stays private. Any unknown or malformed non-blank
line after the marker aborts publication of the entire event.
"""
from __future__ import annotations

import difflib
import html
import re
from dataclasses import dataclass, field

# Lines that are a single word on their own.
FLAGS = {'featured', 'hide', 'draft'}
PUBLISH_MARKER = re.compile(r'^publish\s+to\s+(?:the\s+)?website\s*(?::\s*(?:yes|true|on)?)?\s*[.!]?$', re.I)

# Canonical keyword -> accepted spellings. Fields are only public after an
# explicit Publish to website marker. Keep unrelated private notes above it.
KEYWORDS: dict[str, list[str]] = {
    'title': ['title'],
    'company': ['company', 'presented by'],
    'dates': ['dates', 'date'],
    'doors open': ['doors open', 'doors'],
    'show starts': ['show starts', 'show start', 'starts', 'start time', 'show time', 'showtime', 'curtain up', 'performance time'],
    'show ends': ['show ends', 'show end', 'ends', 'finish', 'finish time', 'finishes'],
    'tickets': ['tickets', 'ticket link', 'tickets link'],
    'ticket prices': ['price', 'prices', 'ticket prices', 'ticket price', 'admission prices', 'admission'],
    'image': ['image', 'images', 'poster', 'poster image'],
    'website': ['website', 'web site'],
    'summary': ['summary', 'blurb', 'about the show'],
    'suitable for': ['suitable for', 'ages'],
    'duration': ['duration', 'running time'],
    'status': ['status'],
}
ALIASES = {alias: key for key, aliases in KEYWORDS.items() for alias in aliases}

# Keywords that only make sense for a show; seeing them without PUBLISH is a near miss.
SHOW_KEYWORDS = {'dates', 'doors open', 'show starts', 'show ends', 'tickets', 'ticket prices', 'image'}

# "cost" is not a recognised instruction; suggest the public price field.
PRICE_WORDS = {'cost': 'ticket prices'}

# Caps stop a pasted private paragraph from going public under a keyword.  Web
# addresses (often very long, e.g. image links) are only checked for being URLs.
MAX_LENGTH = {'summary': 400, 'tickets': 2000, 'image': 2000, 'website': 2000}
DEFAULT_MAX_LENGTH = 120

_KEY_LINE = re.compile(r'^([A-Za-z][A-Za-z ]{0,30}?)\s*(?::|=|\s[-–—]\s)\s*(.*)$')
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
    invalid_publish: bool = False  # fail-closed: do not publish partial shows
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
    """The publication marker is an explicit trust boundary.

    Private notes before the marker are never interpreted as public fields.
    After it, allow familiar field separators and time-first notation, but
    only whitelist known keys: any malformed or unknown non-blank line
    invalidates the entire published show, rather than showing partial data.
    """
    notes = Notes()
    publishing = False
    stopped = False
    for lineno, raw in enumerate(notes_to_text(description).split('\n'), start=1):
        line = _clean(_BULLET.sub('', raw))
        if not line:
            continue
        lower = line.lower()

        if stopped:
            notes.private_lines.append(line)
            continue

        if PUBLISH_MARKER.fullmatch(line):
            if publishing:
                notes.private_lines.append(line)
                notes.issues.append(Issue('error', 'duplicate Publish to website line; '
                                          'the show will not be published', lineno))
                notes.invalid_publish = True
                stopped = True
                continue
            publishing = True
            notes.entries.clear()  # pre-marker regular-status notes must never enter a show
            notes.flags.add('publish')
            continue

        if not publishing:
            notes.private_lines.append(line)
            # Regular timetables use these directives without being published shows.
            if lower == 'hide':
                notes.flags.add('hide')
            m = _KEY_LINE.match(line)
            if m and _clean(m.group(1)).lower() in ALIASES:
                # Retained only for unmarked-entry diagnostics or regular
                # status; entirely cleared if a publication marker follows.
                key = ALIASES[_clean(m.group(1)).lower()]
                notes.entries.append(Entry(key, _clean(m.group(2)), lineno))
            if re.search(r'\bpublish\b', lower):
                notes.publish_like.append((lineno, line))
            elif m and (_clean(m.group(1)).lower() in ALIASES):
                notes.loose_keys.append((lineno, line, ALIASES[_clean(m.group(1)).lower()]))
            continue

        if lower.rstrip(':') in FLAGS:
            notes.flags.add(lower.rstrip(':'))
            continue

        m = _KEY_LINE.match(line)
        if not m:
            # Accept e.g. "Show starts 7pm", "Doors open 6:30pm".
            for alias in sorted(ALIASES, key=len, reverse=True):
                if lower.startswith(alias + ' '):
                    m = (alias, line[len(alias):].strip())
                    break
        if not m:
            # Existing notes sometimes read "6:30pm doors open".
            time_first = _TIME_FIRST.match(lower)
            if time_first and time_first.group(2) in ALIASES:
                m = (time_first.group(2), time_first.group(1))

        if m:
            if isinstance(m, tuple):
                alias, value = m
            else:
                alias, value = _clean(m.group(1)).lower(), _clean(m.group(2))
            key = ALIASES.get(alias)
            if key:
                value = _clean(value).rstrip(';,. ')
                if not value:
                    notes.issues.append(Issue('error', f'"{line}" has no value; '
                                              'the show will not be published', lineno))
                    notes.private_lines.append(line)
                    notes.invalid_publish = True
                    stopped = True
                    continue
                limit = MAX_LENGTH.get(key, DEFAULT_MAX_LENGTH)
                if len(value) > limit:
                    notes.issues.append(Issue('error', f'{key}: is longer than {limit} characters, so it is not '
                                                       'published; shorten it', lineno))
                    notes.private_lines.append(line)
                    notes.invalid_publish = True
                    stopped = True
                    continue
                notes.entries.append(Entry(key, value, lineno))
                continue

        notes.private_lines.append(line)
        notes.invalid_publish = True
        stopped = True
        word = _clean(m.group(1)).lower() if m and not isinstance(m, tuple) else ''
        guessed = ALIASES.get(word) or PRICE_WORDS.get(word) or _closest_key(word) if word else None
        if guessed:
            notes.loose_keys.append((lineno, line, guessed))
        notes.issues.append(Issue('error', f'"{line}" is not a recognised website instruction; '
                                          'the show will not be published', lineno))
    return notes
