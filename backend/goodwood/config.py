"""Configuration, from a TOML file named by GOODWOOD_CONFIG (default: config.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    calendar_id: str = ''
    credentials: str = ''           # user token (goodwood.authorize) or service account key
    calendar_file: str = ''         # development: local JSON file instead of Google
    admin_password: str = ''
    database: str = 'var/goodwood.db'
    timezone: str = 'Australia/Adelaide'
    refresh_seconds: float = 30
    site_dir: str = ''              # development: serve the static site too
    venues: dict | None = None      # Google event colour ID -> venue name (None: built-in defaults)


def load(path: str | None = None) -> Config:
    path = Path(path or os.environ.get('GOODWOOD_CONFIG', 'config.toml'))
    data = tomllib.loads(path.read_text())
    base = path.parent.resolve()

    def rel(p: str) -> str:
        return str((base / p).resolve()) if p else ''

    cal, admin, app = data.get('calendar', {}), data.get('admin', {}), data.get('app', {})
    cfg = Config(
        calendar_id=cal.get('id', ''),
        credentials=rel(cal.get('credentials', '')),
        calendar_file=rel(cal.get('file', '')),
        admin_password=admin.get('password', ''),
        database=rel(app.get('database', Config.database)),
        timezone=app.get('timezone', Config.timezone),
        refresh_seconds=float(app.get('refresh_seconds', Config.refresh_seconds)),
        site_dir=rel(app.get('site_dir', '')),
        venues={str(k): v for k, v in data['venues'].items()} if 'venues' in data else None,
    )
    if not cfg.calendar_file and not (cfg.calendar_id and cfg.credentials):
        raise SystemExit(f'{path}: set [calendar] id and credentials (or file, for development)')
    # Empty password is allowed only behind the staff-only reverse-proxy gate.
    return cfg
