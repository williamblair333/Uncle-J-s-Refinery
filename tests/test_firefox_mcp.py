"""scripts/firefox-mcp.sh and its quiet profile (config/firefox-mcp/user.js).

The egress result itself (zero contacts besides the target) was measured by hand on
2026-10-23 in a network namespace; these tests pin the pieces that result depends on.
"""

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "firefox-mcp.sh"
USER_JS = REPO_ROOT / "config" / "firefox-mcp" / "user.js"


def prefs() -> dict:
    out = {}
    for m in re.finditer(r'user_pref\("([^"]+)",\s*(.+?)\);', USER_JS.read_text()):
        out[m.group(1)] = json.loads(m.group(2))
    return out


def test_config_names_this_script_and_writes_nothing(tmp_path):
    r = subprocess.run(["bash", str(SCRIPT), "--config"], capture_output=True, text=True,
                       timeout=30, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    cfg = json.loads(r.stdout)
    assert cfg["mcpServers"]["firefox"]["command"] == str(SCRIPT)
    assert not any(tmp_path.iterdir())  # --config must not create the profile


def test_prefs_the_measurement_depended_on():
    p = prefs()
    # Each of these closed a contact seen in the 2026-10-22/23 captures.
    assert p["network.http.http3.enable"] is False
    assert p["network.captive-portal-service.enabled"] is False
    assert p["captivedetect.canonicalURL"] == ""
    assert p["services.settings.server"].startswith("http://127.0.0.1:")
    assert p["extensions.blocklist.enabled"] is False
    assert p["telemetry.fog.test.localhost_port"] < 0
    assert p["network.trr.mode"] == 5
    assert p["security.OCSP.enabled"] == 0


def test_launcher_passes_the_env_firefox_needs():
    text = SCRIPT.read_text()
    # Without this env var release Firefox ignores services.settings.server.
    assert "MOZ_REMOTE_SETTINGS_DEVTOOLS=1" in text
    # Private config dir: the host's Crash Reports store holds a pending ping.
    assert "XDG_CONFIG_HOME=" in text
    assert "SE_AVOID_STATS=true" in text
    # npx asks registry.npmjs.org on every start; the launcher runs node on a local install.
    assert not re.search(r"^\s*(exec\s+)?npx\b", text, re.M)
    assert re.search(r"^exec node ", text, re.M)
