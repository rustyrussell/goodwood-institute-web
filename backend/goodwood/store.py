"""SQLite storage: the local copy of the calendar, sync state, and regulars rules."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .publish import Rule

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL DEFAULT (datetime('now')),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    space TEXT NOT NULL DEFAULT '',
    dates TEXT NOT NULL DEFAULT '',
    handled INTEGER NOT NULL DEFAULT 0,
    emailed_at TEXT,
    email_attempts INTEGER NOT NULL DEFAULT 0,
    next_email_attempt TEXT,
    last_email_error TEXT
);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    match TEXT NOT NULL,
    name TEXT NOT NULL,
    activity TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT ''
);
"""


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        # SQLite's CREATE TABLE IF NOT EXISTS doesn't add columns to old databases.
        existing = {col[1] for col in self._db.execute('PRAGMA table_info(contact_messages)')}
        for column, definition in (
            ('space', "TEXT NOT NULL DEFAULT ''"),
            ('dates', "TEXT NOT NULL DEFAULT ''"),
            ('emailed_at', 'TEXT'),
            ('email_attempts', 'INTEGER NOT NULL DEFAULT 0'),
            ('next_email_attempt', 'TEXT'),
            ('last_email_error', 'TEXT'),
        ):
            if column not in existing:
                self._db.execute(f'ALTER TABLE contact_messages ADD COLUMN {column} {definition}')
        self._db.commit()
        self._lock = threading.Lock()

    # ---- events

    def events(self) -> list[dict]:
        with self._lock:
            return [json.loads(r[0]) for r in self._db.execute('SELECT data FROM events')]

    def apply_sync(self, items: list[dict], full: bool, token: str | None):
        """Store a sync result.  A full sync replaces everything; an incremental
        one upserts changed events and removes cancelled ones."""
        with self._lock, self._db:
            if full:
                self._db.execute('DELETE FROM events')
            for item in items:
                if item.get('status') == 'cancelled':
                    self._db.execute('DELETE FROM events WHERE id = ?', (item['id'],))
                else:
                    self._db.execute('INSERT OR REPLACE INTO events (id, data) VALUES (?, ?)',
                                     (item['id'], json.dumps(item)))
            self._set('sync_token', token)

    # ---- meta

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
            return row[0] if row else None

    def set(self, key: str, value: str | None):
        with self._lock, self._db:
            self._set(key, value)

    def _set(self, key, value):
        self._db.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)', (key, value))

    # ---- rules

    def rules(self) -> list[Rule]:
        with self._lock:
            rows = self._db.execute('SELECT id, match, name, activity, website FROM rules ORDER BY name COLLATE NOCASE')
            return [Rule(*r) for r in rows]

    def save_rule(self, rule: Rule) -> None:
        with self._lock, self._db:
            if rule.id:
                self._db.execute('UPDATE rules SET match=?, name=?, activity=?, website=? WHERE id=?',
                                 (rule.match, rule.name, rule.activity, rule.website, rule.id))
            else:
                self._db.execute('INSERT INTO rules (match, name, activity, website) VALUES (?, ?, ?, ?)',
                                 (rule.match, rule.name, rule.activity, rule.website))

    def delete_rule(self, rule_id: int) -> None:
        with self._lock, self._db:
            self._db.execute('DELETE FROM rules WHERE id = ?', (rule_id,))

    # ---- contact enquiries / durable SMTP delivery queue (never public JSON)

    def save_contact(self, name: str, email: str, phone: str, message: str,
                     space: str = '', dates: str = '') -> None:
        with self._lock, self._db:
            # Limit abuse without trusting potentially forged proxy IP headers.
            recent_total = self._db.execute(
                "SELECT count(*) FROM contact_messages WHERE created >= datetime('now', '-1 hour')"
            ).fetchone()[0]
            recent_sender = self._db.execute(
                "SELECT count(*) FROM contact_messages WHERE email = ? AND created >= datetime('now', '-1 hour')",
                (email,)
            ).fetchone()[0]
            if recent_total >= 60 or recent_sender >= 4:
                raise ValueError('Too many enquiries recently. Please email bookings@goodwoodinstitute.asn.au.')
            self._db.execute(
                'INSERT INTO contact_messages (name, email, phone, message, space, dates) VALUES (?, ?, ?, ?, ?, ?)',
                (name, email, phone, message, space, dates)
            )

    def contacts(self) -> list[dict]:
        # Unsent enquiries remain visible even if staff marked them handled.
        with self._lock:
            cur = self._db.execute(
                'SELECT id, created, name, email, phone, message, space, dates, emailed_at, email_attempts, '
                'last_email_error, handled FROM contact_messages '
                'WHERE handled = 0 OR emailed_at IS NULL ORDER BY id DESC LIMIT 100'
            )
            return [dict(zip(('id', 'created', 'name', 'email', 'phone', 'message', 'space', 'dates',
                              'emailed_at', 'email_attempts', 'last_email_error', 'handled'), row))
                    for row in cur]

    def handle_contact(self, contact_id: int) -> None:
        with self._lock, self._db:
            self._db.execute('UPDATE contact_messages SET handled = 1 WHERE id = ?', (contact_id,))

    def pending_emails(self) -> list[dict]:
        with self._lock:
            cur = self._db.execute(
                'SELECT id, name, email, phone, message, space, dates FROM contact_messages '
                'WHERE emailed_at IS NULL AND email_attempts < 12 '
                "AND (next_email_attempt IS NULL OR next_email_attempt <= datetime('now')) "
                'ORDER BY id LIMIT 20'
            )
            return [dict(zip(('id', 'name', 'email', 'phone', 'message', 'space', 'dates'), row)) for row in cur]

    def mark_emailed(self, contact_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE contact_messages SET emailed_at = datetime('now'), "
                "next_email_attempt = NULL, last_email_error = NULL WHERE id = ?",
                (contact_id,)
            )

    def mark_email_failed(self, contact_id: int, error: str) -> None:
        with self._lock, self._db:
            row = self._db.execute(
                'SELECT email_attempts FROM contact_messages WHERE id = ?', (contact_id,)
            ).fetchone()
            if row is None:
                return
            attempts = row[0] + 1
            minutes = min(60, 2 ** min(attempts - 1, 6))
            self._db.execute(
                "UPDATE contact_messages SET email_attempts = ?, last_email_error = ?, "
                "next_email_attempt = datetime('now', ?) WHERE id = ?",
                (attempts, error[:300], f'+{minutes} minutes', contact_id)
            )

    def retry_contact(self, contact_id: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                'UPDATE contact_messages SET email_attempts = 0, next_email_attempt = NULL, '
                'last_email_error = NULL WHERE id = ? AND emailed_at IS NULL',
                (contact_id,)
            )
