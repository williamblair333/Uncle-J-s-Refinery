"""live-preview — publish frames from any project and watch them build in a browser.

  live-preview publish --project P --session S --label "step" img.png [more.png ...]
  live-preview watch   --project P --session S [--port N] [--open]
  live-preview status  --project P --session S
  live-preview list

Run from anywhere: python3 <refinery>/scripts/live_preview/cli.py ...  (or `just preview ...`).
Output is JSON on stdout; errors are {"error": ...} on stdout with exit code 1.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from live_preview import publish as lp  # noqa: E402
from live_preview import viewer  # noqa: E402


class _LocalOnlyHandler(viewer._NoCacheHandler):
    """The vendored no-cache handler, minus directory listings and foreign Host headers.

    Binding 127.0.0.1 keeps other machines out; checking Host keeps out web pages that
    rebind their own DNS name to 127.0.0.1 (DNS rebinding) and then read the session.
    """

    def send_head(self):
        port = self.server.server_port
        if self.headers.get("Host", "") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.send_error(403, "Host not allowed")
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None


def start_watch(project: str, session: str, port: int = 0, poll_ms: int = 1000) -> Tuple[ThreadingHTTPServer, str]:
    """Render the live page into the session dir and serve it on 127.0.0.1 in a daemon thread."""
    if not isinstance(port, int) or not (port == 0 or 1024 <= port <= 65535):
        raise ValueError(f"port must be 0 (any free port) or 1024-65535, got {port!r}")
    sdir = lp.session_path(project, session)
    if not (sdir / "session.json").is_file():
        raise FileNotFoundError(f"no session at {sdir}; publish a frame first")
    viewer.render_live_html(str(sdir), str(sdir / "index.html"), poll_ms=poll_ms)
    handler = functools.partial(_LocalOnlyHandler, directory=str(sdir))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/index.html"


def _default_project() -> str:
    name = Path.cwd().name
    try:
        return lp.check_name("project", name)
    except ValueError:
        return "default"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="live-preview", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def scoped(p):
        p.add_argument("--project", default=_default_project(), help="default: current directory name")
        p.add_argument("--session", default="default")
        return p

    pub = scoped(sub.add_parser("publish", help="add one step (one or more images)"))
    pub.add_argument("--label", required=True)
    pub.add_argument("--note")
    pub.add_argument("--command", dest="command_text")
    pub.add_argument("--keep", type=int, default=lp.DEFAULT_KEEP)
    pub.add_argument("images", nargs="+")

    w = scoped(sub.add_parser("watch", help="serve the live page until Ctrl-C"))
    w.add_argument("--port", type=int, default=0)
    w.add_argument("--open", action="store_true", help="open a browser window")

    scoped(sub.add_parser("status", help="latest step of a session"))
    sub.add_parser("list", help="all sessions, newest first")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "publish":
            out = lp.publish(args.project, args.session, args.images, args.label,
                             command=args.command_text, note=args.note, keep=args.keep)
        elif args.cmd == "status":
            out = lp.status(args.project, args.session)
        elif args.cmd == "list":
            out = {"sessions": lp.list_sessions()}
        else:
            server, url = start_watch(args.project, args.session, args.port)
            print(json.dumps({"url": url}), flush=True)
            if args.open:
                viewer.open_in_browser(url)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                server.shutdown()
                server.server_close()
            return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(out, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
