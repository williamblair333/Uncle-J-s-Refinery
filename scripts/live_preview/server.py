"""live_preview — MCP server: publish frames from any project, watch them live in a browser.

The agent renders a picture however its project does (FreeCAD offscreen render,
browser screenshot, game frame) and calls preview_publish with the file paths.
preview_watch serves the session on 127.0.0.1 and returns the URL for the user.
Sessions live under LIVE_PREVIEW_HOME (default ~/.live-preview/<project>/<session>).

Writes only under LIVE_PREVIEW_HOME; accepts image files only; serves only on
127.0.0.1. Errors come back as {"error": ...}, never raised.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from live_preview import publish as lp  # noqa: E402
from live_preview.cli import start_watch  # noqa: E402

_servers: dict = {}  # (project, session) -> (server, url)
MAX_WATCHED = 16


def _guard(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}


def watch(project: str, session: str, port: int = 0) -> dict:
    key = (lp.check_name("project", project), lp.check_name("session", session))
    if key in _servers:
        return {"url": _servers[key][1], "already_running": True}
    if len(_servers) >= MAX_WATCHED:
        raise ValueError(f"already watching {MAX_WATCHED} sessions; preview_stop one first")
    server, url = start_watch(project, session, port)
    _servers[key] = (server, url)
    return {"url": url}


def stop(project: str, session: str) -> dict:
    entry = _servers.pop((project, session), None)
    if not entry:
        return {"error": "not_watching"}
    entry[0].shutdown()
    entry[0].server_close()  # release the port, or a re-watch on it fails "address in use"
    return {"stopped": entry[1]}


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("live_preview", log_level="WARNING", instructions=(
        "Live view of anything being built, for the user. After each meaningful step, render "
        "image(s) of the current state your project's own way, then call preview_publish with "
        "the paths and a short label. Call preview_watch once per session and give the user the "
        "URL. project/session are short slugs; use the repo name as project."))

    @mcp.tool(name="preview_publish")
    def _publish(project: str, session: str, images: list[str], label: str,
                 note: str | None = None, command: str | None = None) -> dict:
        """Add one step to a live session: image files (png/jpg/gif/webp, first is the hero) plus a short label. Optional note (why) and command (what produced it)."""
        return _guard(lp.publish, project, session, images, label, note=note, command=command)

    @mcp.tool(name="preview_watch")
    def _watch(project: str, session: str, port: int = 0) -> dict:
        """Serve a session's live page on 127.0.0.1 and return its URL. Idempotent per session."""
        return _guard(watch, project, session, port)

    @mcp.tool(name="preview_stop")
    def _stop(project: str, session: str) -> dict:
        """Stop serving a session started with preview_watch."""
        return _guard(stop, project, session)

    @mcp.tool(name="preview_status")
    def _status(project: str | None = None, session: str | None = None) -> dict:
        """Latest step of one session, or every session (newest first) when project/session are omitted."""
        if project and session:
            return _guard(lp.status, project, session)
        return _guard(lambda: {"sessions": lp.list_sessions()})

    return mcp


if __name__ == "__main__":
    build_server().run()
