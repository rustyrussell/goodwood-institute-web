"""Send queued website enquiries via Google Workspace's IP-authenticated SMTP relay.

Run from a systemd oneshot timer. Only the fixed configured recipient gets mail;
visitor-provided addresses are used as Reply-To, never as SMTP recipients.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from .config import Config, load
from .store import Store

log = logging.getLogger(__name__)


def message_for(contact: dict, cfg: Config) -> EmailMessage:
    if not cfg.mail_from or not cfg.mail_to:
        raise ValueError('mail sender/recipient must be configured')
    msg = EmailMessage()
    msg['From'] = formataddr(('Goodwood Institute Website', cfg.mail_from))
    msg['To'] = cfg.mail_to
    msg['Reply-To'] = contact['email']
    prefix = cfg.mail_subject_prefix.strip()
    msg['Subject'] = f'{prefix + " " if prefix else ""}Goodwood website enquiry #{contact["id"]}'
    msg.set_content(
        f'New enquiry from the Goodwood Institute website (# {contact["id"]})\n\n'
        f'Name: {contact["name"]}\n'
        f'Email: {contact["email"]}\n'
        + (f'Phone: {contact["phone"]}\n' if contact["phone"] else '')
        + f'Space or enquiry type: {contact["space"] or "(not specified)"}\n'
        + f'Preferred dates/times: {contact["dates"] or "(not yet known)"}\n\n'
        + f'Details:\n{contact["message"]}\n\n'
        'This enquiry is also saved in the private website admin inbox.\n'
        'Please reply to the visitor, not to website@goodwoodinstitute.asn.au.\n'
    )
    return msg


def send_pending(cfg: Config, store: Store, smtp_factory=smtplib.SMTP) -> tuple[int, int]:
    if not cfg.smtp_host:
        raise ValueError('[mail] smtp_host is not configured; refusing to send')
    sent = failed = 0
    for contact in store.pending_emails():
        try:
            message = message_for(contact, cfg)
            with smtp_factory(cfg.smtp_host, cfg.smtp_port, timeout=15) as client:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
                client.send_message(message, from_addr=cfg.mail_from, to_addrs=[cfg.mail_to])
            store.mark_emailed(contact['id'])
            sent += 1
            log.info('Mailed website enquiry #%s', contact['id'])
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            # The customer sees "received" because the form was saved before
            # SMTP. Timer retries with backoff, and admin shows each failure.
            store.mark_email_failed(contact['id'], str(exc))
            failed += 1
            log.exception('Could not mail website enquiry #%s', contact['id'])
    return sent, failed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load()
    store = Store(cfg.database)
    sent, failed = send_pending(cfg, store)
    log.info('Website enquiry email queue: %d sent, %d failed', sent, failed)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
