import base64
import datetime as dt
import threading
from zoneinfo import ZoneInfo

from goodwood.app import create_app
from goodwood.config import Config
from goodwood.gcal import SyncResult, SyncTokenExpired
from goodwood.service import Service
from goodwood.store import Store

TZ = ZoneInfo('Australia/Adelaide')
SOON = dt.datetime.now(TZ).date() + dt.timedelta(days=10)


def item(id, summary='Show', notes='Publish to website\nshow starts: 7pm', status='confirmed'):
    return {'id': id, 'status': status, 'summary': summary, 'description': notes,
            'start': {'date': SOON.isoformat()}, 'end': {'date': (SOON + dt.timedelta(days=1)).isoformat()}, 'htmlLink': ''}


class FakeSource:
    description = 'fake'

    def __init__(self):
        self.calls = []
        self.results = []

    def sync(self, token):
        self.calls.append(token)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def make(results):
    src = FakeSource()
    src.results = results
    clock = Clock()
    svc = Service(Store(':memory:'), src, TZ, interval=30, clock=clock)
    return svc, src, clock


def wait_for_sync(svc):
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=5)


def titles(svc):
    return [s['title'] for s in svc.output().shows['shows']]


def test_first_request_syncs_then_throttles():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True)])
    assert titles(svc) == ['A']
    clock.t += 10
    assert titles(svc) == ['A']
    assert src.calls == [None]


def test_incremental_sync_after_interval_in_background():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True),
                            SyncResult([item('b', 'B'), item('a', status='cancelled')], 'tok2', False)])
    svc.output()
    clock.t += 31
    svc.output()            # served from cache; sync starts in background
    wait_for_sync(svc)
    assert src.calls == [None, 'tok1']
    assert titles(svc) == ['B']
    assert svc.store.get('sync_token') == 'tok2'


def test_failure_keeps_last_good_data_and_reports():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True), RuntimeError('Google is down')])
    svc.output()
    clock.t += 31
    svc.refresh_now()
    assert titles(svc) == ['A']
    assert 'Google is down' in svc.output().report['sync']['lastError']


def test_expired_token_does_full_sync():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True), SyncTokenExpired(),
                            SyncResult([item('c', 'C')], 'tok3', True)])
    svc.output()
    svc.refresh_now()
    assert src.calls == [None, 'tok1', None]
    assert titles(svc) == ['C']


def admin_client():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True)] + [SyncResult([], 't', False)] * 5)
    app = create_app(Config(admin_password='secret'), svc)
    return app.test_client(), svc


AUTH = {'Authorization': 'Basic ' + base64.b64encode(b'staff:secret').decode()}


def test_admin_requires_password():
    c, _ = admin_client()
    assert c.get('/admin/').status_code == 401
    assert c.get('/admin/', headers={'Authorization': 'Basic ' + base64.b64encode(b'x:wrong').decode()}).status_code == 401
    assert c.get('/admin/', headers=AUTH).status_code == 200
    assert c.get('/api/shows.json').status_code == 200


def test_admin_post_rejects_cross_site():
    c, svc = admin_client()
    form = {'match': 'Yoga', 'name': 'Yoga'}
    assert c.post('/admin/rules', data=form, headers=AUTH).status_code == 403
    assert c.post('/admin/rules', data=form, headers={**AUTH, 'Origin': 'https://evil.example'}).status_code == 403
    assert c.post('/admin/rules', data=form, headers={**AUTH, 'Origin': 'http://localhost'}).status_code == 302
    assert [r.name for r in svc.store.rules()] == ['Yoga']


def test_rule_validation():
    c, svc = admin_client()
    h = {**AUTH, 'Origin': 'http://localhost'}
    c.post('/admin/rules', data={'match': 'Yoga', 'name': 'Yoga', 'website': 'yoga.com'}, headers=h)
    c.post('/admin/rules', data={'match': '', 'name': 'Yoga'}, headers=h)
    assert svc.store.rules() == []


def test_changed_source_forces_full_sync():
    svc, src, clock = make([SyncResult([item('a', 'A')], 'tok1', True), SyncResult([item('b', 'B')], 'tok2', True)])
    svc.output()
    src.identity = 'another login'
    svc.refresh_now()
    assert src.calls == [None, None]
    assert titles(svc) == ['B']


def test_public_contact_is_private_and_staff_can_handle():
    c, svc = admin_client()
    data = {'name': 'Visitor', 'email': 'visitor@example.org', 'message': 'Can we hire the theatre?',
            'space': 'Studio Theatre', 'dates': 'Sat 21 Nov 2026, 3pm-11pm'}
    assert c.post('/api/contact', data=data).status_code == 403
    assert c.post('/api/contact', data=data, headers={'Origin': 'http://localhost'}).status_code == 201
    [msg] = svc.store.contacts()
    assert msg['name'] == 'Visitor'
    assert msg['space'] == 'Studio Theatre'
    assert msg['dates'] == 'Sat 21 Nov 2026, 3pm-11pm'
    assert msg['message'] == 'Can we hire the theatre?'
    assert 'Visitor' not in c.get('/api/shows.json').get_data(as_text=True)
    assert c.get('/admin/', headers=AUTH).status_code == 200
    assert c.post(f"/admin/contacts/{msg['id']}/handled",
                  headers={**AUTH, 'Origin': 'http://localhost'}).status_code == 302
    assert svc.store.contacts()[0]['handled'] == 1  # remains visible until emailed
    svc.store.mark_emailed(msg['id'])
    assert svc.store.contacts() == []


def test_contact_validation_and_honeypot():
    c, svc = admin_client()
    valid = {'name': 'Visitor', 'email': 'visitor@example.org', 'message': 'A long enough message.',
             'space': 'Not sure yet — please advise'}
    h = {'Origin': 'http://localhost'}
    assert c.post('/api/contact', data={**valid, 'email': 'wrong'}, headers=h).status_code == 400
    assert c.post('/api/contact', data={**valid, 'space': 'Other made-up'}, headers=h).status_code == 400
    assert c.post('/api/contact', data={**valid, 'space': ''}, headers=h).status_code == 400
    assert c.post('/api/contact', data={**valid, 'website': 'spambot.example'}, headers=h).status_code == 201
    assert svc.store.contacts() == []


def test_curtain_colour_api_and_admin_only_editing():
    c, svc = admin_client()
    assert c.get('/api/appearance.json').json == {'curtain': '#67192B'}
    assert c.post('/admin/appearance', data={'curtain': '#FFFFFF'}, headers={'Origin': 'http://localhost'}).status_code == 401
    assert c.post('/admin/appearance', data={'curtain': 'red'}, headers={**AUTH, 'Origin': 'http://localhost'}).status_code == 400
    assert c.post('/admin/appearance', data={'curtain': '#882233'}, headers={**AUTH, 'Origin': 'http://localhost'}).status_code == 302
    assert c.get('/api/appearance.json').json == {'curtain': '#882233'}
