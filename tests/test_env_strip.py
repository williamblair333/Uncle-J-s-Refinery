"""ralph-harness and the Telegram gateway must not hand an Anthropic API key to `claude`.

With ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN in its environment, the CLI bills that
key per token instead of the subscription login. Static checks: both callers are long
scripts with network and cron side effects, so they aren't run here.
"""

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def test_ralph_unsets_both_keys_before_any_claude_call():
    text = (REPO_ROOT / "ralph-harness.sh").read_text()
    unset = re.search(r"^unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN$", text, re.M)
    assert unset, "ralph-harness.sh no longer unsets the Anthropic keys"
    first_call = re.search(r"claude -p", text[unset.end():])
    assert first_call
    assert "claude -p" not in re.sub(r"^\s*#.*$", "", text[: unset.start()], flags=re.M)


def test_ralph_unset_really_strips(tmp_path):
    script = "unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN; env"
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "ANTHROPIC_API_KEY": "x",
                              "ANTHROPIC_AUTH_TOKEN": "y", "KEEP": "1"}).stdout
    assert "KEEP=1" in out and not any(k in out for k in KEYS)


def _gateway_python() -> str:
    text = (REPO_ROOT / "scripts" / "telegram-gateway-poll.sh").read_text()
    m = re.search(r"<< ?'PYEOF'\n(.*?)\nPYEOF", text, re.S)
    assert m, "gateway's embedded python block not found"
    return m.group(1)


def test_gateway_claude_subprocess_filters_both_keys():
    tree = ast.parse(_gateway_python())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "subprocess.run"
             and n.args and ast.unparse(n.args[0]) == "claude_argv"]
    assert len(calls) == 1
    env = {kw.arg: kw.value for kw in calls[0].keywords}.get("env")
    assert env is not None, "claude subprocess inherits the full environment"
    src = ast.unparse(env)
    assert all(k in src for k in KEYS)
    # Evaluate the filter against a sample environment.
    sample = {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_AUTH_TOKEN": "y", "HOME": "/h"}

    class _OS:
        environ = sample

    assert eval(compile(ast.Expression(env), "<env>", "eval"), {"os": _OS}) == {"HOME": "/h"}
