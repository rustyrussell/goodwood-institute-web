"""Web app: public JSON API, staff admin pages, and (in development) the static site."""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from . import config as config_mod
from .gcal import FileCalendar, GoogleCalendar
from .notes import KEYWORDS
from .publish import STATUSES, Rule, valid_url
from .service import Service
from .store import Store


def make_service(cfg: config_mod.Config) -> Service:
    if cfg.calendar_file:
        source = FileCalendar(cfg.calendar_file)
    else:
        source = GoogleCalendar(cfg.calendar_id, cfg.credentials)
    return Service(Store(cfg.database), source, ZoneInfo(cfg.timezone), cfg.refresh_seconds, venues=cfg.venues, include_drafts=cfg.include_drafts)


def create_app(cfg: config_mod.Config, service: Service | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)        # only used for flash messages
    service = service or make_service(cfg)
    app.config['service'] = service

    DEFAULT_CURTAIN = '#67192B'  # oxblood
    HEX = re.compile(r'^#[0-9a-fA-F]{6}

    def public_json(data: dict) -> Response:
        resp = jsonify(data)
        resp.headers['Cache-Control'] = 'public, max-age=30'
        return resp

    @app.get('/api/shows.json')
    def shows():
        return public_json(service.output().shows)

    @app.get('/api/regulars.json')
    def regulars():
        return public_json(service.output().regulars)

    @app.get('/api/appearance.json')
    def appearance():
        colour = service.store.get('curtain_color') or DEFAULT_CURTAIN
        response = jsonify({'curtain': colour})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/contact')
    def contact():
        # Anonymous, public endpoint. Origin and honeypot protect against basic
        # form spam; rate limits / CAPTCHA can be added before production launch.
        if not same_origin():
            abort(403)
        if request.content_length and request.content_length > 16384:
            abort(413)
        if request.form.get('website', '').strip():  # hidden honeypot
            return jsonify({'ok': True}), 201
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        message = request.form.get('message', '').strip()
        if not (2 <= len(name) <= 120 and len(email) <= 254 and
                re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) and
                len(phone) <= 60 and 10 <= len(message) <= 5000):
            return jsonify({'error': 'Please enter your name, email address and a message of at least 10 characters.'}), 400
        service.store.save_contact(name, email, phone, message)
        return jsonify({'ok': True}), 201

    # ------------------------------------------------------------ admin

    def admin_only(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.authorization
            if cfg.admin_password and (not auth or not hmac.compare_digest((auth.password or '').encode(), cfg.admin_password.encode())):
                return Response('Staff login required', 401, {'WWW-Authenticate': 'Basic realm="Goodwood admin"'})
            if request.method == 'POST' and not same_origin():
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    @app.get('/admin/')
    @admin_only
    def admin():
        out = service.output()
        prefill = {k: request.args.get(k, '') for k in ('match', 'name')}
        return render_template('admin.html', r=out.report, prefill=prefill,\n                               curtain=service.store.get('curtain_color') or DEFAULT_CURTAIN,\n                               contacts=service.store.contacts())

    @app.post('/admin/appearance')
    @admin_only
    def save_appearance():
        colour = request.form.get('curtain', '').strip()
        if not HEX.fullmatch(colour):
            abort(400)
        service.store.set('curtain_color', colour.upper())
        flash('Curtain colour updated.')
        return redirect(url_for('admin') + '#appearance')

    @app.post('/admin/contacts/<int:contact_id>/handled')
    @admin_only
    def contact_handled(contact_id: int):
        service.store.handle_contact(contact_id)
        flash('Enquiry marked as handled.')
        return redirect(url_for('admin') + '#contacts')

    @app.get('/admin/guide')
    @admin_only
    def guide():
        return render_template('guide.html', keywords=KEYWORDS,
                               statuses=sorted(set(STATUSES) - {'canceled'}))

    @app.post('/admin/refresh')
    @admin_only
    def refresh():
        service.refresh_now()
        flash('Refreshed from the calendar.')
        return redirect(url_for('admin'))

    @app.post('/admin/rules')
    @admin_only
    def save_rule():
        f = request.form
        rule = Rule(id=int(f.get('id') or 0), match=f.get('match', '').strip(), name=f.get('name', '').strip(),
                    activity=f.get('activity', '').strip(), website=f.get('website', '').strip())
        problems = []
        if not rule.match or not rule.name:
            problems.append('A regular needs both "calendar title contains" and "public name".')
        if rule.website and (problem := valid_url(rule.website)):
            problems.append(problem)
        if problems:
            for p in problems:
                flash(p, 'error')
        else:
            service.store.save_rule(rule)
            service.rebuild()
            flash(f'Saved regular "{rule.name}".')
        return redirect(url_for('admin') + '#regulars')

    @app.post('/admin/rules/<int:rule_id>/delete')
    @admin_only
    def delete_rule(rule_id: int):
        service.store.delete_rule(rule_id)
        service.rebuild()
        flash('Regular removed.')
        return redirect(url_for('admin') + '#regulars')

    # ------------------------------------------------------------ development: static site

    if cfg.site_dir:
        site = Path(cfg.site_dir)

        @app.get('/')
        def site_index():
            return send_from_directory(site, 'index.html')

        @app.get('/docs/<path:name>')
        def site_docs(name):
            return send_from_directory(site.parent / 'docs', name)

        @app.get('/<path:name>')
        def site_file(name):
            return send_from_directory(site, name)

    return app


def wsgi() -> Flask:
    """Production entry point: gunicorn 'goodwood.app:wsgi()'"""
    logging.basicConfig(level=logging.INFO)
    return create_app(config_mod.load())


def main():
    app = wsgi()
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '8080')))


if __name__ == '__main__':
    main()
)

    def same_origin() -> bool:
        origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
        return urlsplit(origin).netloc == request.host and urlsplit(origin).scheme == request.scheme

    # ------------------------------------------------------------ public API

    def public_json(data: dict) -> Response:
        resp = jsonify(data)
        resp.headers['Cache-Control'] = 'public, max-age=30'
        return resp

    @app.get('/api/shows.json')
    def shows():
        return public_json(service.output().shows)

    @app.get('/api/regulars.json')
    def regulars():
        return public_json(service.output().regulars)

    # ------------------------------------------------------------ admin

    def admin_only(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            auth = request.authorization
            if cfg.admin_password and (not auth or not hmac.compare_digest((auth.password or '').encode(), cfg.admin_password.encode())):
                return Response('Staff login required', 401, {'WWW-Authenticate': 'Basic realm="Goodwood admin"'})
            if request.method == 'POST':
                # Basic auth is sent automatically by the browser, so refuse
                # form posts that come from another site.
                origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
                if urlsplit(origin).netloc != request.host:
                    abort(403)
            return view(*args, **kwargs)
        return wrapped

    @app.get('/admin/')
    @admin_only
    def admin():
        out = service.output()
        prefill = {k: request.args.get(k, '') for k in ('match', 'name')}
        return render_template('admin.html', r=out.report, prefill=prefill)

    @app.get('/admin/guide')
    @admin_only
    def guide():
        return render_template('guide.html', keywords=KEYWORDS,
                               statuses=sorted(set(STATUSES) - {'canceled'}))

    @app.post('/admin/refresh')
    @admin_only
    def refresh():
        service.refresh_now()
        flash('Refreshed from the calendar.')
        return redirect(url_for('admin'))

    @app.post('/admin/rules')
    @admin_only
    def save_rule():
        f = request.form
        rule = Rule(id=int(f.get('id') or 0), match=f.get('match', '').strip(), name=f.get('name', '').strip(),
                    activity=f.get('activity', '').strip(), website=f.get('website', '').strip())
        problems = []
        if not rule.match or not rule.name:
            problems.append('A regular needs both "calendar title contains" and "public name".')
        if rule.website and (problem := valid_url(rule.website)):
            problems.append(problem)
        if problems:
            for p in problems:
                flash(p, 'error')
        else:
            service.store.save_rule(rule)
            service.rebuild()
            flash(f'Saved regular "{rule.name}".')
        return redirect(url_for('admin') + '#regulars')

    @app.post('/admin/rules/<int:rule_id>/delete')
    @admin_only
    def delete_rule(rule_id: int):
        service.store.delete_rule(rule_id)
        service.rebuild()
        flash('Regular removed.')
        return redirect(url_for('admin') + '#regulars')

    # ------------------------------------------------------------ development: static site

    if cfg.site_dir:
        site = Path(cfg.site_dir)

        @app.get('/')
        def site_index():
            return send_from_directory(site, 'index.html')

        @app.get('/docs/<path:name>')
        def site_docs(name):
            return send_from_directory(site.parent / 'docs', name)

        @app.get('/<path:name>')
        def site_file(name):
            return send_from_directory(site, name)

    return app


def wsgi() -> Flask:
    """Production entry point: gunicorn 'goodwood.app:wsgi()'"""
    logging.basicConfig(level=logging.INFO)
    return create_app(config_mod.load())


def main():
    app = wsgi()
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '8080')))


if __name__ == '__main__':
    main()
