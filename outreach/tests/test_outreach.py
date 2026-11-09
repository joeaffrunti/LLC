import csv
import email
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from outreach import agent, classify, db, inbox, mailer, templates
from outreach.config import load_config


def make_cfg(tmp: Path, **overrides):
    env = {
        "OUTREACH_DB": str(tmp / "t.db"),
        "OUTREACH_OUTBOX": str(tmp / "outbox"),
        "OUTREACH_FROM_EMAIL": "joe@example.test",
        "OUTREACH_COMPANY_NAME": "Acme Web",
        "OUTREACH_SENDER_NAME": "Joe",
        "OUTREACH_POSTAL_ADDRESS": "1 Main St, Springfield",
        "SMTP_HOST": "smtp.test", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
        "IMAP_HOST": "imap.test", "IMAP_USER": "u", "IMAP_PASSWORD": "p",
        "OUTREACH_MAX_PER_RUN": "25",
        "OUTREACH_FOLLOWUP_DAYS": "7",
    }
    env.update(overrides)
    return load_config(env)


class ClassifyTests(unittest.TestCase):
    def test_unsubscribe_wins(self):
        self.assertEqual(classify.classify("Please unsubscribe me. Sounds good though."), "unsubscribe")

    def test_not_interested_beats_interested(self):
        self.assertEqual(classify.classify("Not interested, thanks."), "not_interested")

    def test_positive(self):
        self.assertEqual(classify.classify("Yes, tell me more about pricing."), "interested")

    def test_question(self):
        self.assertEqual(classify.classify("Do you do menus?"), "question")

    def test_out_of_office(self):
        self.assertEqual(classify.classify("I am out of the office until Monday."), "out_of_office")

    def test_quoted_text_ignored(self):
        body = "Thanks.\n\nOn Mon, Joe wrote:\n> Would you be interested in a website?"
        self.assertEqual(classify.classify(body), "other")

    def test_empty_is_other(self):
        self.assertEqual(classify.classify("   "), "other")


class DbTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_duplicate_email_rejected(self):
        self.assertIsNotNone(db.add_lead(self.conn, "A", "a@x.test"))
        self.assertIsNone(db.add_lead(self.conn, "A2", "A@x.test"))

    def test_suppression(self):
        db.suppress(self.conn, "a@x.test", "test")
        self.assertTrue(db.is_suppressed(self.conn, "a@x.test"))
        self.assertFalse(db.is_suppressed(self.conn, "b@x.test"))

    def test_bad_status_rejected(self):
        lead_id = db.add_lead(self.conn, "A", "a@x.test")
        with self.assertRaises(ValueError):
            db.set_status(self.conn, lead_id, "nonsense")

    def test_followups_due_only_after_window(self):
        lead_id = db.add_lead(self.conn, "A", "a@x.test")
        db.mark_contacted(self.conn, lead_id, "pitched")
        self.assertEqual(db.followups_due(self.conn, 7), [])
        self.conn.execute("UPDATE leads SET last_contacted = last_contacted - ?", (8 * 86400,))
        self.conn.commit()
        self.assertEqual(len(db.followups_due(self.conn, 7)), 1)


class ImportTests(unittest.TestCase):
    def test_skips_sites_suppressed_and_bad_rows(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        db.suppress(conn, "blocked@x.test", "test")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "leads.csv"
            with path.open("w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["business_name", "email", "category", "city", "website"])
                w.writerow(["Good Diner", "ok@x.test", "restaurant", "Springfield", ""])
                w.writerow(["Has Site", "site@x.test", "bakery", "Springfield", "https://s.test"])
                w.writerow(["No Email", "not-an-email", "cafe", "Springfield", ""])
                w.writerow(["Blocked", "blocked@x.test", "cafe", "Springfield", ""])
                w.writerow(["Good Diner Again", "OK@x.test", "restaurant", "Springfield", ""])
            counts = agent.import_leads(conn, path)
        self.assertEqual(counts, {"added": 1, "has_website": 1, "bad_email": 1,
                                  "duplicate": 1, "suppressed": 1})


class TemplateTests(unittest.TestCase):
    def test_missing_field_raises(self):
        with self.assertRaises(KeyError):
            templates.render(templates.PITCH_BODY, business_name="X")

    def test_pitch_includes_address_and_opt_out(self):
        body = templates.render(templates.PITCH_BODY, business_name="X", city="Y", category="diner",
                                company_name="Acme Web", sender_name="Joe", postal_address="1 Main St",
                                from_email="j@x.test")
        self.assertIn("1 Main St", body)
        self.assertIn("unsubscribe", body.lower())


class SendTests(unittest.TestCase):
    def test_dry_run_writes_eml_and_marks_pitched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_cfg(Path(d))
            conn = db.connect(cfg.db_path)
            db.add_lead(conn, "Good Diner", "ok@x.test", "restaurant", "Springfield")
            agent.cmd_send(cfg, conn, live=False, kind="pitch")
            files = list(cfg.outbox_dir.glob("*.eml"))
            self.assertEqual(len(files), 1)
            parsed = email.message_from_bytes(files[0].read_bytes())
            self.assertEqual(parsed["To"], "ok@x.test")
            self.assertIn("Good Diner", parsed["Subject"])
            self.assertEqual(db.leads_with_status(conn, "pitched")[0]["email"], "ok@x.test")
            self.assertEqual(db.leads_with_status(conn, "new"), [])

    def test_live_send_requires_postal_address(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_cfg(Path(d), OUTREACH_POSTAL_ADDRESS="")
            with self.assertRaises(SystemExit):
                agent._require_live_config(cfg)

    def test_suppressed_lead_is_not_pitched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_cfg(Path(d))
            conn = db.connect(cfg.db_path)
            db.add_lead(conn, "Diner", "ok@x.test")
            db.suppress(conn, "ok@x.test", "unsubscribe reply")
            # Simulate a lead that was suppressed after import.
            agent.cmd_send(cfg, conn, live=False, kind="pitch")
            self.assertEqual(list(cfg.outbox_dir.glob("*.eml")) if cfg.outbox_dir.exists() else [], [])
            self.assertEqual(db.leads_with_status(conn, "unsubscribed")[0]["email"], "ok@x.test")


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.lead_id = db.add_lead(self.conn, "Good Diner", "ok@x.test")
        db.record_message(self.conn, self.lead_id, "out", "pitch", "s", "b", "<sent1@feel.test>")

    def tearDown(self):
        self.conn.close()

    def _reply(self, body, sender="ok@x.test", refs="<sent1@feel.test>"):
        msg = EmailMessage()
        msg["From"] = sender
        msg["Subject"] = "Re: A website"
        msg["Message-ID"] = "<reply1@x.test>"
        if refs:
            msg["In-Reply-To"] = refs
        msg.set_content(body)
        return email.message_from_bytes(bytes(msg))

    def test_interested_reply_flags_for_human(self):
        ev = inbox.handle_message(self.conn, self._reply("Sounds good, tell me more."))
        self.assertEqual(ev.intent, "interested")
        self.assertEqual(db.get_lead(self.conn, self.lead_id)["status"], "interested")

    def test_unsubscribe_suppresses(self):
        inbox.handle_message(self.conn, self._reply("Please remove me from your list."))
        self.assertEqual(db.get_lead(self.conn, self.lead_id)["status"], "unsubscribed")
        self.assertTrue(db.is_suppressed(self.conn, "ok@x.test"))

    def test_threading_matches_even_if_sender_differs(self):
        ev = inbox.handle_message(self.conn, self._reply("Not interested.", sender="assistant@x.test"))
        self.assertEqual(ev.lead_id, self.lead_id)
        self.assertEqual(db.get_lead(self.conn, self.lead_id)["status"], "not_interested")

    def test_unrelated_mail_ignored(self):
        self.assertIsNone(inbox.handle_message(self.conn, self._reply("Hi", sender="stranger@x.test", refs=None)))

    def test_bounce_marks_bounced(self):
        dsn = EmailMessage()
        dsn["From"] = "MAILER-DAEMON@x.test"
        dsn["Subject"] = "Undeliverable"
        dsn["Message-ID"] = "<dsn1@x.test>"
        dsn.set_content("Delivery failed for ok@x.test: user unknown")
        ev = inbox.handle_message(self.conn, email.message_from_bytes(bytes(dsn)))
        self.assertEqual(ev.kind, "bounce")
        self.assertEqual(db.get_lead(self.conn, self.lead_id)["status"], "bounced")
        self.assertTrue(db.is_suppressed(self.conn, "ok@x.test"))


if __name__ == "__main__":
    unittest.main()


class FakeIMAP:
    """Stands in for imaplib.IMAP4_SSL, returning the same response shapes a real server does."""

    def __init__(self, messages):
        self.messages = messages  # list of raw RFC822 bytes
        self.logged_out = False

    def login(self, user, password):
        return ("OK", [b"logged in"])

    def select(self, mailbox):
        return ("OK", [b"1"])

    def search(self, charset, criteria):
        assert criteria == "UNSEEN"
        nums = " ".join(str(i + 1) for i in range(len(self.messages))).encode()
        return ("OK", [nums])

    def fetch(self, num, parts):
        raw = self.messages[int(num) - 1]
        return ("OK", [(b"%s (RFC822 {%d}" % (num, len(raw)), raw), b")"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])


def _raw(from_addr, subject, body, msg_id, in_reply_to=None):
    m = EmailMessage()
    m["From"] = from_addr
    m["To"] = "joe@example.test"
    m["Subject"] = subject
    m["Message-ID"] = msg_id
    m["Date"] = "Mon, 09 Nov 2026 19:00:00 +0000"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    m.set_content(body)
    return bytes(m)


class PollEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = make_cfg(Path(self.tmp.name))
        self.conn = db.connect(self.cfg.db_path)
        self.addCleanup(self.conn.close)
        self.lead_id = db.add_lead(self.conn, "Good Diner", "owner@diner.test", "restaurant", "Springfield")
        db.mark_contacted(self.conn, self.lead_id, "pitched")
        db.record_message(self.conn, self.lead_id, "out", "pitch", "A website", "b",
                          "<pitch1@feelingswellmedia.test>")

    def _poll(self, messages):
        fake = FakeIMAP(messages)
        with mock.patch.object(inbox.imaplib, "IMAP4_SSL", return_value=fake):
            events = inbox.poll(self.cfg, self.conn)
        self.assertTrue(fake.logged_out)
        return events

    def test_real_shaped_imap_session(self):
        messages = [
            _raw("Owner <owner@diner.test>", "Re: A website for Good Diner?",
                 "Yes, send me pricing please.\n\nOn Mon, Joe wrote:\n> A website...",
                 "<r1@diner.test>", in_reply_to="<pitch1@feelingswellmedia.test>"),
            _raw("stranger@elsewhere.test", "Hello", "Who are you?", "<x1@elsewhere.test>"),
        ]
        events = self._poll(messages)
        self.assertEqual([e.intent for e in events], ["interested"])
        self.assertEqual(db.get_lead(self.conn, self.lead_id)["status"], "interested")

    def test_rerun_does_not_duplicate_replies(self):
        messages = [_raw("owner@diner.test", "Re", "Not interested, thanks.", "<r2@diner.test>")]
        self._poll(messages)
        self._poll(messages)
        replies = [m for m in db.messages_for_lead(self.conn, self.lead_id) if m["direction"] == "in"]
        self.assertEqual(len(replies), 1)

    def test_bounce_via_imap(self):
        dsn = _raw("Mail Delivery <MAILER-DAEMON@mx.test>", "Undeliverable",
                   "Your message to owner@diner.test could not be delivered.", "<dsn9@mx.test>")
        events = self._poll([dsn])
        self.assertEqual([e.kind for e in events], ["bounce"])
        self.assertTrue(db.is_suppressed(self.conn, "owner@diner.test"))
