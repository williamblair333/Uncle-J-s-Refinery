"""Can bubblewrap actually sandbox here? Installed isn't enough: a CI job container
usually can't create the namespaces bwrap needs, and the jail tests would fail there."""
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def bwrap_unusable_reason():
    """None when bwrap can start a sandbox, else why it can't (for the skip message)."""
    if shutil.which("bwrap") is None:
        return "bubblewrap not installed"
    try:
        r = subprocess.run(["bwrap", "--unshare-pid", "--ro-bind", "/", "/",
                            "--proc", "/proc", "--dev", "/dev", "true"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"bwrap could not start: {e}"
    if r.returncode != 0:
        return f"bwrap cannot create a sandbox here: {r.stderr.strip()[:200]}"
    return None
