#!/usr/bin/env python3
"""buddy_mail.py: the buddy's mailbox (Gmail) over IMAP and SMTP, standard library only.

    just mail check                         # log in, count the inbox
    just mail list [--n 10] [--unseen]      # newest first, headers only
    just mail search "from:x newer_than:2d" # Gmail search syntax (X-GM-RAW)
    just mail read UID                      # one message, text body
    just mail send --to A --subject S (--body TEXT | --body-file F)

Config: KEY=VALUE file at $BUDDY_MAIL_ENV (default ~/.config/uncle-j/buddy-mail.env), 0600,
written by William (see the "Buddy accounts setup" doc): BUDDY_MAIL_USER, BUDDY_MAIL_APP_PASSWORD,
optional BUDDY_MAIL_IMAP (imap.gmail.com:993), BUDDY_MAIL_SMTP (smtp.gmail.com:465).

Reads never change mail (readonly select, BODY.PEEK); there is no delete. Output is one JSON
object; failures carry "error" and exit 1. The password is never printed.
Policy, not code: mail to anyone but William is confirm-first.
"""

import argparse
import email
import email.policy
import imaplib
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

DEFAULT_ENV = Path.home() / ".config" / "uncle-j" / "buddy-mail.env"
MAX_LIST = 50
MAX_BODY = 20_000


class Fail(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def load_config():
    path = Path(os.environ.get("BUDDY_MAIL_ENV") or DEFAULT_ENV)
    if not path.is_file():
        raise Fail("no_config", str(path))
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("'\"")
    for key in ("BUDDY_MAIL_USER", "BUDDY_MAIL_APP_PASSWORD"):
        if not cfg.get(key):
            raise Fail("missing_key", key)
    return cfg


def hostport(value, default):
    host, _, port = (value or default).rpartition(":")
    return host, int(port)


def imap_connect(cfg):
    host, port = hostport(cfg.get("BUDDY_MAIL_IMAP"), "imap.gmail.com:993")
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(cfg["BUDDY_MAIL_USER"], cfg["BUDDY_MAIL_APP_PASSWORD"])
    except imaplib.IMAP4.error:
        raise Fail("login_failed", "check the app password; Google revokes them on a password change")
    return conn


def fetch(conn, uids, what):
    if not uids:
        return {}
    typ, data = conn.uid("FETCH", ",".join(uids), what)
    out = {}
    for part in data or []:
        if isinstance(part, tuple):
            head = part[0].decode(errors="replace")
            uid = head.split("UID ", 1)[1].split()[0] if "UID " in head else None
            if uid:
                out[uid] = email.message_from_bytes(part[1], policy=email.policy.default)
    return out


def summary(uid, msg):
    return {"uid": uid, "date": str(msg.get("Date", "")), "from": str(msg.get("From", "")),
            "subject": str(msg.get("Subject", ""))}


def text_body(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    body = part.get_content()
    return body[:MAX_BODY]


def headers_for(conn, uids, n):
    uids = sorted(uids, key=int, reverse=True)[:min(n, MAX_LIST)]
    msgs = fetch(conn, uids, "(BODY.PEEK[HEADER.FIELDS (DATE FROM SUBJECT)])")
    return [summary(u, msgs[u]) for u in uids if u in msgs]


def search_uids(conn, *criteria):
    typ, data = conn.uid("SEARCH", *criteria)
    return [u.decode() for u in (data[0] or b"").split()] if data else []


def cmd_check(cfg, args):
    conn = imap_connect(cfg)
    try:
        typ, data = conn.select("INBOX", readonly=True)
        return {"user": cfg["BUDDY_MAIL_USER"], "inbox": int(data[0])}
    finally:
        conn.logout()


def cmd_list(cfg, args):
    conn = imap_connect(cfg)
    try:
        conn.select("INBOX", readonly=True)
        uids = search_uids(conn, "UNSEEN" if args.unseen else "ALL")
        return {"messages": headers_for(conn, uids, args.n)}
    finally:
        conn.logout()


def cmd_search(cfg, args):
    conn = imap_connect(cfg)
    try:
        conn.select('"[Gmail]/All Mail"' if args.all else "INBOX", readonly=True)
        quoted = '"' + args.query.replace("\\", "\\\\").replace('"', '\\"') + '"'
        uids = search_uids(conn, "X-GM-RAW", quoted)
        return {"query": args.query, "messages": headers_for(conn, uids, args.n)}
    finally:
        conn.logout()


def cmd_read(cfg, args):
    conn = imap_connect(cfg)
    try:
        conn.select("INBOX", readonly=True)
        msgs = fetch(conn, [args.uid], "(BODY.PEEK[])")
        if args.uid not in msgs:
            raise Fail("not_found", args.uid)
        msg = msgs[args.uid]
        return {**summary(args.uid, msg), "to": str(msg.get("To", "")), "body": text_body(msg)}
    finally:
        conn.logout()


def cmd_send(cfg, args):
    body = Path(args.body_file).read_text() if args.body_file else args.body
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["BUDDY_MAIL_USER"], args.to, args.subject
    msg.set_content(body)
    host, port = hostport(cfg.get("BUDDY_MAIL_SMTP"), "smtp.gmail.com:465")
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(cfg["BUDDY_MAIL_USER"], cfg["BUDDY_MAIL_APP_PASSWORD"])
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise Fail("login_failed", "check the app password")
    return {"sent": True, "to": args.to, "subject": args.subject}


def parser():
    p = argparse.ArgumentParser(prog="buddy_mail", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    lp = sub.add_parser("list")
    lp.add_argument("--n", type=int, default=10)
    lp.add_argument("--unseen", action="store_true")
    sp = sub.add_parser("search")
    sp.add_argument("query")
    sp.add_argument("--n", type=int, default=10)
    sp.add_argument("--all", action="store_true", help="search All Mail, not just the inbox")
    rp = sub.add_parser("read")
    rp.add_argument("uid")
    se = sub.add_parser("send")
    se.add_argument("--to", required=True)
    se.add_argument("--subject", required=True)
    body = se.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file")
    return p


COMMANDS = {"check": cmd_check, "list": cmd_list, "search": cmd_search, "read": cmd_read,
            "send": cmd_send}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = COMMANDS[args.cmd](load_config(), args), 0
    except Fail as e:
        result, code = {"error": e.code, "detail": e.detail}, 1
    except (OSError, imaplib.IMAP4.error, smtplib.SMTPException) as e:
        result, code = {"error": type(e).__name__, "detail": str(e)[:300]}, 1
    print(json.dumps({k: v for k, v in result.items() if v not in (None, "")}, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
