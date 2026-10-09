"""SMTP queue tests: secrets are not required; no messages go to real SMTP."""
from __future__ import annotations

import sqlite3

from goodwood.config import Config
from goodwood.mailer import send_pending
from goodwood.store import Store


CFG = Config(smtp_host='smtp-relay.gmail.com', smtp_port=587,
             mail_from='website@goodwoodinstitute.asn.au',
             mail_to='bookings@goodwoodinstitute.asn.au',
             mail_subject_prefix='[TEST]')


class FakeSMTP:
    sent = []
    fail = False

    def __init__(self, host, port, timeout):
        assert (host, port, timeout) == ('smtp-relay.gmail.com', 587, 15)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def ehlo(self):
        pass

    def starttls(self, context):
        assert context is not None

    def send_message(self, msg, from_addr, to_addrs):
        if self.fail:
            raise OSError('temporary relay failure')
        assert from_addr == CFG.mail_from
        assert to_addrs == [CFG.mail_to]
        self.sent.append(msg)


def test_message_is_sent_only_to_fixed_bookings_address_and_reply_to_sender():
    store = Store(':memory:')
    store.save_contact('Visitor', 'visitor@example.net', '', 'Can we hire the theatre?',
                       space='Studio Theatre', dates='Tue afternoons in November')
    FakeSMTP.sent = []
    FakeSMTP.fail = False
    assert send_pending(CFG, store, FakeSMTP) == (1, 0)
    [mail] = FakeSMTP.sent
    assert mail['To'] == CFG.mail_to
    assert mail['Reply-To'] == 'visitor@example.net'
    assert mail['Subject'].startswith('[TEST] Goodwood website enquiry #')
    assert 'Can we hire the theatre?' in mail.get_content()
    assert 'Space or enquiry type: Studio Theatre' in mail.get_content()
    assert 'Preferred dates/times: Tue afternoons in November' in mail.get_content()
    assert 'Phone:' not in mail.get_content()
    assert not store.pending_emails()
    assert store.contacts()[0]['emailed_at'] is not None


def test_failure_is_visible_and_retryable_without_losing_message():
    store = Store(':memory:')
    store.save_contact('Visitor', 'visitor@example.net', '', 'Please help with my booking.')
    FakeSMTP.fail = True
    assert send_pending(CFG, store, FakeSMTP) == (0, 1)
    [contact] = store.contacts()
    assert contact['email_attempts'] == 1
    assert 'temporary relay failure' in contact['last_email_error']
    assert store.pending_emails() == []
    store.retry_contact(contact['id'])
    FakeSMTP.fail = False
    assert send_pending(CFG, store, FakeSMTP) == (1, 0)
    assert store.contacts()[0]['emailed_at'] is not None


def test_existing_inbox_database_migrates_without_losing_enquiries(tmp_path):
    path = tmp_path / 'existing.db'
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE contact_messages (
            id INTEGER PRIMARY KEY,
            created TEXT NOT NULL DEFAULT (datetime('now')),
            name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL, handled INTEGER NOT NULL DEFAULT 0);
        INSERT INTO contact_messages (name, email, message)
        VALUES ('Old enquiry', 'old@example.com', 'I would like to visit.');
    """)
    db.close()
    store = Store(path)
    [contact] = store.pending_emails()
    assert contact['name'] == 'Old enquiry'
    assert contact['space'] == '' and contact['dates'] == ''
