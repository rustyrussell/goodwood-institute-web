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
