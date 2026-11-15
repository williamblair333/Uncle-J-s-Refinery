"""scripts/buddy_mail.py: the buddy's Gmail over IMAP/SMTP (fake servers, no network)."""

import importlib.util
import json
from email.message import EmailMessage
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "buddy_mail.py"
SECRET = "abcd efgh ijkl mnop"


def load():
    spec = importlib.util.spec_from_file_location("buddy_mail", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def raw(uid, subject, body="hello there", sender="a@example.com"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "xforgelabs@gmail.com", subject
    m["Date"] = "Sat, 15 Nov 2026 08:00:00 +0000"
    m.set_content(body)
    return m.as_bytes()


class FakeIMAP:
    calls = []
    store = {b"1": raw(1, "first"), b"2": raw(2, "second", "body two")}

    def __init__(self, host, port):
        FakeIMAP.calls = [("connect", host, port)]

    def login(self, user, pw):
        FakeIMAP.calls.append(("login", user))
        if pw != SECRET:
            import imaplib
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b""]

    def select(self, box, readonly=False):
        FakeIMAP.calls.append(("select", box, readonly))
        return "OK", [str(len(self.store)).encode()]

    def uid(self, cmd, *args):
        FakeIMAP.calls.append(("uid", cmd) + args)
        if cmd == "SEARCH":
            return "OK", [b" ".join(sorted(self.store))]
        if cmd == "FETCH":
            uids, what = args
            out = []
            for u in uids.split(b",") if isinstance(uids, bytes) else uids.encode().split(b","):
                if u in self.store:
                    out.append((b"%s (UID %s BODY[] {n}" % (u, u), self.store[u]))
                    out.append(b")")
            return "OK", out
        raise AssertionError(cmd)

    def logout(self):
        FakeIMAP.calls.append(("logout",))


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, pw):
        assert pw == SECRET

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def mail(tmp_path, monkeypatch):
    env = tmp_path / "buddy-mail.env"
    env.write_text(f"BUDDY_MAIL_USER=xforgelabs@gmail.com\nBUDDY_MAIL_APP_PASSWORD={SECRET}\n")
    env.chmod(0o600)
    monkeypatch.setenv("BUDDY_MAIL_ENV", str(env))
    mod = load()
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.sent = []
    return mod


def run(mod, capsys, *argv):
    code = mod.main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_missing_config_is_a_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BUDDY_MAIL_ENV", str(tmp_path / "nope.env"))
    code, out = run(load(), capsys, "check")
    assert code == 1 and out["error"] == "no_config"


def test_check_logs_in_readonly(mail, capsys):
    code, out = run(mail, capsys, "check")
    assert code == 0 and out["user"] == "xforgelabs@gmail.com" and out["inbox"] == 2
    assert ("select", "INBOX", True) in FakeIMAP.calls


def test_list_newest_first_and_peeks(mail, capsys):
    code, out = run(mail, capsys, "list", "--n", "5")
    assert [m["subject"] for m in out["messages"]] == ["second", "first"]
    fetches = [c for c in FakeIMAP.calls if c[:2] == ("uid", "FETCH")]
    assert fetches and all("PEEK" in c[3] for c in fetches)


def test_read_returns_body(mail, capsys):
    code, out = run(mail, capsys, "read", "2")
    assert out["subject"] == "second" and "body two" in out["body"]


def test_search_uses_gmail_query(mail, capsys):
    run(mail, capsys, "search", "from:a@example.com")
    s = [c for c in FakeIMAP.calls if c[:2] == ("uid", "SEARCH")][0]
    assert "X-GM-RAW" in s and '"from:a@example.com"' in s


def test_send_one_message(mail, capsys):
    code, out = run(mail, capsys, "send", "--to", "bill@example.com", "--subject", "hi", "--body", "test")
    assert code == 0 and out["sent"] is True and len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["From"] == "xforgelabs@gmail.com"


def test_bad_password_never_echoed(tmp_path, monkeypatch, capsys):
    env = tmp_path / "e.env"
    env.write_text("BUDDY_MAIL_USER=x@gmail.com\nBUDDY_MAIL_APP_PASSWORD=wrong-secret-xyz\n")
    monkeypatch.setenv("BUDDY_MAIL_ENV", str(env))
    mod = load()
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)
    code, out = run(mod, capsys, "check")
    assert code == 1 and out["error"] == "login_failed"
    assert "wrong-secret-xyz" not in json.dumps(out)
