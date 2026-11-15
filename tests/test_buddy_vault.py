"""buddy_vault.py against a fake `bw` that logs every call."""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "buddy_vault.py"

FAKE_BW = r'''#!/usr/bin/env python3
import json, os, sys
state = os.environ["FAKE_STATE"]
with open(state + ".log", "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "session": os.environ.get("BW_SESSION"),
                         "pw_env": os.environ.get("BUDDY_VAULT_PW")}) + "\n")
s = json.load(open(state)) if os.path.exists(state) else {"status": "unauthenticated", "serverUrl": None}
a = sys.argv[1:]
def save(): json.dump(s, open(state, "w"))
if a[0] == "status": print(json.dumps({**s, "userEmail": "b@x"}))
elif a[0] == "config": s["serverUrl"] = a[2]; save()
elif a[0] == "login":
    if os.environ.get(a[a.index("--passwordenv") + 1]) != "pw": print("bad", file=sys.stderr); sys.exit(1)
    s["status"] = "locked"; save()
elif a[0] == "unlock": s["status"] = "unlocked"; save(); print("SESSIONKEY")
elif a[0] == "sync": print("Syncing complete.")
elif a[0] == "list": print(json.dumps([{"id": "1", "name": "site", "login": {"uris": [{"uri": "https://s"}],
                                         "password": "SECRET"}}]))
elif a[0] == "get": print({"totp": "123456", "password": "SECRET"}.get(a[1], "buddy"))
else: sys.exit(2)
'''


def setup(tmp_path, mode=0o600, body="BUDDY_VAULT_EMAIL=b@x\nBUDDY_VAULT_PASSWORD=pw\n"):
    bw = tmp_path / "bw"
    bw.write_text(FAKE_BW)
    bw.chmod(0o755)
    env_file = tmp_path / "buddy-vault.env"
    env_file.write_text(body)
    env_file.chmod(mode)
    return {**os.environ, "BUDDY_VAULT_BW": str(bw), "BUDDY_VAULT_ENV": str(env_file),
            "FAKE_STATE": str(tmp_path / "state"), "HOME": str(tmp_path)}


def run(env, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                       env=env, timeout=30)
    return r.returncode, json.loads(r.stdout)


def calls(tmp_path):
    return [json.loads(l) for l in (tmp_path / "state.log").read_text().splitlines()]


def test_get_totp_logs_in_unlocks_and_never_puts_password_in_argv(tmp_path):
    env = setup(tmp_path)
    rc, out = run(env, "get", "site", "--field", "totp")
    assert rc == 0 and out["value"] == "123456"
    log = calls(tmp_path)
    verbs = [c["argv"][0] for c in log]
    assert verbs[:2] == ["status", "config"] and "login" in verbs and "unlock" in verbs
    assert all("pw" not in c["argv"] for c in log)                  # password only via env
    assert [c["session"] for c in log if c["argv"][0] == "get"] == ["SESSIONKEY"]


def test_list_returns_names_without_secrets(tmp_path):
    rc, out = run(setup(tmp_path), "list")
    assert rc == 0 and out == {"items": [{"id": "1", "name": "site", "uri": "https://s"}]}
    assert "SECRET" not in json.dumps(out)


def test_second_call_skips_login(tmp_path):
    env = setup(tmp_path)
    run(env, "list")
    (tmp_path / "state.log").unlink()
    run(env, "get", "site")
    assert "login" not in [c["argv"][0] for c in calls(tmp_path)]


def test_only_read_verbs_are_ever_run(tmp_path):
    env = setup(tmp_path)
    for args in (["status"], ["list", "x"], ["get", "site", "--field", "password"]):
        run(env, *args)
    assert {c["argv"][0] for c in calls(tmp_path)} <= {"status", "config", "login", "unlock", "sync",
                                                        "list", "get"}


def test_config_must_be_private_and_complete(tmp_path):
    assert run(setup(tmp_path, mode=0o644), "status")[1]["error"] == "config_not_private"
    assert run(setup(tmp_path, body="BUDDY_VAULT_EMAIL=b@x\n"), "status")[1] == {
        "error": "missing_key", "detail": "BUDDY_VAULT_PASSWORD"}


def test_wrong_password_is_a_clean_error(tmp_path):
    rc, out = run(setup(tmp_path, body="BUDDY_VAULT_EMAIL=b@x\nBUDDY_VAULT_PASSWORD=nope\n"), "list")
    assert rc == 1 and out["error"] == "bw_failed" and "nope" not in json.dumps(out)
