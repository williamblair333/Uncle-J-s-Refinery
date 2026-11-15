#!/usr/bin/env python3
"""buddy_vault.py: the buddy's own Vaultwarden account, read-only, through the official `bw` CLI.

    just vault status                 # logged in? locked? which server
    just vault list [SEARCH]          # item names and ids, no secrets
    just vault get ITEM [--field F]   # F = username | password | totp | uri | notes (default username)

Config: KEY=VALUE file at $BUDDY_VAULT_ENV (default ~/.config/uncle-j/buddy-vault.env), 0600,
written by Bill: BUDDY_VAULT_EMAIL, BUDDY_VAULT_PASSWORD (the buddy account's master password,
never Bill's). Optional BUDDY_VAULT_SERVER (https://vault.home.arpa), BUDDY_VAULT_CA (autark root).

Read-only by construction: only `bw status|login|unlock|sync|list items|get` are ever run, and
there is no add, edit or delete. bw's state lives in ~/.config/uncle-j/bw, apart from any other
Bitwarden CLI use. Output is one JSON object; failures are {"error": code, "detail": ...}, exit 1.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ENV = Path.home() / ".config" / "uncle-j" / "buddy-vault.env"
APPDATA = Path.home() / ".config" / "uncle-j" / "bw"
DEFAULT_SERVER = "https://vault.home.arpa"
DEFAULT_CA = "/usr/local/share/ca-certificates/autark-root.crt"
FIELDS = ("username", "password", "totp", "uri", "notes")


class Fail(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def load_config():
    path = Path(os.environ.get("BUDDY_VAULT_ENV") or DEFAULT_ENV)
    if not path.is_file():
        raise Fail("no_config", str(path))
    if path.stat().st_mode & 0o077:
        raise Fail("config_not_private", f"{path} must be 0600")
    cfg = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip("'\"")
    for key in ("BUDDY_VAULT_EMAIL", "BUDDY_VAULT_PASSWORD"):
        if not cfg.get(key):
            raise Fail("missing_key", key)
    return cfg


def bw_bin():
    found = os.environ.get("BUDDY_VAULT_BW") or shutil.which("bw") or str(Path.home() / ".local/bin/bw")
    if not Path(found).is_file():
        raise Fail("no_bw", "install: npm i -g --prefix ~/.local @bitwarden/cli")
    return found


def env_for(cfg, session=None):
    env = {**os.environ, "BITWARDENCLI_APPDATA_DIR": str(APPDATA),
           "NODE_EXTRA_CA_CERTS": cfg.get("BUDDY_VAULT_CA") or DEFAULT_CA,
           "BW_NOINTERACTION": "true", "BUDDY_VAULT_PW": cfg["BUDDY_VAULT_PASSWORD"]}
    if session:
        env["BW_SESSION"] = session
    return env


def bw(cfg, *args, session=None):
    r = subprocess.run([bw_bin(), *args], capture_output=True, text=True, timeout=120,
                       env=env_for(cfg, session))
    if r.returncode != 0:
        # bw's stderr never contains the password (it is passed by env var name only).
        raise Fail("bw_failed", f"bw {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def status(cfg):
    return json.loads(bw(cfg, "status") or "{}")


def ensure_server(cfg):
    want = cfg.get("BUDDY_VAULT_SERVER") or DEFAULT_SERVER
    if status(cfg).get("serverUrl") != want:
        bw(cfg, "config", "server", want)


def session_key(cfg):
    ensure_server(cfg)
    st = status(cfg).get("status")
    if st == "unauthenticated":
        bw(cfg, "login", cfg["BUDDY_VAULT_EMAIL"], "--passwordenv", "BUDDY_VAULT_PW", "--raw")
    key = bw(cfg, "unlock", "--passwordenv", "BUDDY_VAULT_PW", "--raw")
    if not key:
        raise Fail("unlock_failed", "no session key returned")
    bw(cfg, "sync", session=key)
    return key


def cmd_status(cfg, _args):
    st = status(cfg)
    return {k: st.get(k) for k in ("serverUrl", "userEmail", "status", "lastSync")}


def cmd_list(cfg, args):
    key = session_key(cfg)
    extra = ["--search", args.search] if args.search else []
    items = json.loads(bw(cfg, "list", "items", *extra, session=key) or "[]")
    return {"items": [{"id": i.get("id"), "name": i.get("name"),
                       "uri": ((i.get("login") or {}).get("uris") or [{}])[0].get("uri")}
                      for i in items]}


def cmd_get(cfg, args):
    key = session_key(cfg)
    return {"item": args.item, "field": args.field,
            "value": bw(cfg, "get", args.field, args.item, session=key)}


def parser():
    p = argparse.ArgumentParser(prog="buddy_vault", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    pl = sub.add_parser("list")
    pl.add_argument("search", nargs="?")
    pg = sub.add_parser("get")
    pg.add_argument("item")
    pg.add_argument("--field", choices=FIELDS, default="username")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        cfg = load_config()
        out = {"status": cmd_status, "list": cmd_list, "get": cmd_get}[args.cmd](cfg, args)
    except Fail as e:
        print(json.dumps({"error": e.code, "detail": e.detail}))
        return 1
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": "bw_timeout"}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
