"""Keeps the published output up to date: syncs the calendar on demand, at most
once per interval, without ever making a visitor wait for Google."""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from zoneinfo import ZoneInfo

from .events import event_from_api
from .gcal import SyncTokenExpired
from .publish import Output, build
from .store import Store

log = logging.getLogger(__name__)


class Service:
    def __init__(self, store: Store, source, tz: ZoneInfo, interval: float = 30, clock=time.monotonic,
                 venues: dict[str, str] | None = None, include_drafts: bool = False):
        self.store = store
        self.source = source
        self.tz = tz
        self.interval = interval
        self.clock = clock
        self.venues = venues
        self.include_drafts = include_drafts
        self._lock = threading.Lock()
        self._syncing = False
        self._last_attempt: float | None = None
        self._output: Output | None = None

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.tz)

    def output(self) -> Output:
        """Current output.  Starts a background sync if the last one is stale;
        only the very first call (nothing built yet) waits for it."""
        with self._lock:
            stale = self._last_attempt is None or self.clock() - self._last_attempt >= self.interval
            start = stale and not self._syncing
            if start:
                self._syncing = True
                self._last_attempt = self.clock()
            first = self._output is None
        if start:
            if first:
                self._sync()
            else:
                threading.Thread(target=self._sync, daemon=True).start()
        if self._output is None:
            self.rebuild()
        return self._output

    def refresh_now(self) -> None:
        """Synchronous sync for the admin "Refresh now" button."""
        with self._lock:
            if self._syncing:
                return
            self._syncing = True
            self._last_attempt = self.clock()
        self._sync()

    def _sync(self) -> None:
        try:
            token = self.store.get('sync_token')
            identity = getattr(self.source, 'identity', self.source.description)
            if self.store.get('source_identity') != identity:
                token = None            # new calendar or login: start from a full sync
            try:
                result = self.source.sync(token)
            except SyncTokenExpired:
                log.info('sync token expired; doing a full sync')
                result = self.source.sync(None)
            self.store.apply_sync(result.items, result.full, result.token)
            self.store.set('source_identity', identity)
            self.store.set('last_sync', self.now().isoformat(timespec='seconds'))
            if result.full:
                self.store.set('last_full_sync', self.now().isoformat(timespec='seconds'))
            self.store.set('last_error', None)
        except Exception as e:
            log.exception('calendar sync failed')
            self.store.set('last_error', f'{self.now().isoformat(timespec="seconds")}: {e}')
        finally:
            try:
                self.rebuild()
            finally:
                with self._lock:
                    self._syncing = False

    def rebuild(self) -> None:
        events = []
        for item in self.store.events():
            try:
                events.append(event_from_api(item, self.tz))
            except Exception:
                log.exception('skipping malformed event %s', item.get('id'))
        sync_info = {
            'source': self.source.description,
            'lastSync': self.store.get('last_sync'),
            'lastFullSync': self.store.get('last_full_sync'),
            'lastError': self.store.get('last_error'),
            'events': len(events),
        }
        self._output = build(events, self.store.rules(), self.now(), sync_info, self.venues, include_drafts=self.include_drafts)
