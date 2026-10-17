"""Publish image frames into a live preview session that viewer.py can watch.

A session is a directory under LIVE_PREVIEW_HOME (default ~/.live-preview):
<project>/<session>/ holding session.json, trajectory.json, bundles/ and a
`current` symlink to the newest bundle. Any project can publish into one; the
only input is a list of image files plus a label. How the images are made
(FreeCAD render, browser screenshot, game frame) is the caller's business.

Three properties the pre-mortem required (2026-10-17):
  * one publisher at a time per session (flock on <session>/.lock), so agents
    publishing concurrently never drop each other's steps;
  * every JSON write is temp-file + fsync + os.replace, so the viewer's 1 s poll
    never reads a half-written file and a crash never truncates one;
  * inputs are images only (extension + magic bytes, no symlinks, size cap) and
    names are a strict slug, so a confused agent can't copy a private file into
    a directory the viewer serves.
Security review (same day) added: images are validated and copied through one
O_NOFOLLOW descriptor (no check-then-swap), stored under generated names (the
vendored page doesn't escape filenames), and counts and text lengths are capped.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import shutil
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import bundle as pb

SESSION_PROTOCOL = "preview-live-session/v1"
RECIPE = "frames"
DEFAULT_KEEP = 300
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGES_PER_STEP = 16
MAX_TEXT_CHARS = 2000

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),  # plus b"WEBP" at offset 8, checked below
}


def sessions_root() -> Path:
    return Path(os.environ.get("LIVE_PREVIEW_HOME") or "~/.live-preview").expanduser()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def check_name(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value) or value in {".", ".."}:
        raise ValueError(f"{kind} must match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}, got {value!r}")
    return value


def session_path(project: str, session: str) -> Path:
    return sessions_root() / check_name("project", project) / check_name("session", session)


def _check_text(kind: str, value: Optional[str]) -> None:
    if value is not None and len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{kind} longer than {MAX_TEXT_CHARS} characters")


def open_image(path: str) -> Tuple[int, str]:
    """Open an image for copying and validate it through the open descriptor.

    Returns (fd, suffix). Everything is checked on the descriptor that will be copied,
    so swapping the file for a symlink or a device after the check changes nothing.
    """
    p = Path(path).expanduser()
    suffix = p.suffix.lower()
    if suffix not in _MAGIC:
        raise ValueError(f"not an allowed image type ({', '.join(sorted(_MAGIC))}): {path}")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise FileNotFoundError(f"image not found: {path}") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"refusing symlink: {path}") from None
        raise
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"not a regular file: {path}")
        if st.st_size > MAX_IMAGE_BYTES:
            raise ValueError(f"image over {MAX_IMAGE_BYTES} bytes: {path}")
        head = os.pread(fd, 12, 0)
        ok = any(head.startswith(m) for m in _MAGIC[suffix])
        if suffix == ".webp":
            ok = ok and head[8:12] == b"WEBP"
        if not ok:
            raise ValueError(f"file content is not a {suffix} image: {path}")
    except BaseException:
        os.close(fd)
        raise
    return fd, suffix


def _copy_fd(fd: int, dest: Path) -> None:
    """Copy from an already-validated descriptor, never more than MAX_IMAGE_BYTES."""
    copied = 0
    with open(dest, "xb") as out:
        while True:
            chunk = os.pread(fd, 1 << 20, copied)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_IMAGE_BYTES:
                raise ValueError(f"image grew past {MAX_IMAGE_BYTES} bytes while copying")
            out.write(chunk)


def _stored_name(index: int, suffix: str) -> str:
    # Never the caller's filename: the vendored page puts this name into an <img src="...">
    # without escaping, so a crafted name would inject script (security review, 2026-10-17).
    return f"{index:02d}-{'hero' if index == 0 else 'view'}{suffix}"


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@contextmanager
def _locked(session: Path) -> Iterator[None]:
    session.mkdir(parents=True, exist_ok=True)
    with open(session / ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _point_current(session: Path, bundle_dir: Path) -> None:
    tmp = session / f".current.{os.getpid()}.tmp"
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(os.path.relpath(bundle_dir, session))
    os.replace(tmp, session / "current")  # atomic: the viewer never sees a missing link


def _prune(session: Path, keep: int, current: Path) -> int:
    """Delete the oldest bundle dirs beyond `keep`. Steps keep their text; old ones lose pictures."""
    root = session / "bundles"
    # Bundle ids start with a whole-second timestamp, so same-second publishes sort by hash;
    # the manifest's write time orders them correctly.
    dirs = sorted((d for d in root.glob("*/*/*") if (d / "manifest.json").is_file()),
                  key=lambda d: (d / "manifest.json").stat().st_mtime_ns)
    removed = 0
    for d in dirs[: max(0, len(dirs) - keep)]:
        if d.resolve() == current.resolve() or root.resolve() not in d.resolve().parents:
            continue
        shutil.rmtree(d)
        removed += 1
    return removed


def publish(
    project: str,
    session: str,
    images: List[str],
    label: str,
    *,
    software: Optional[str] = None,
    command: Optional[str] = None,
    note: Optional[str] = None,
    reason: str = "update",
    keep: int = DEFAULT_KEEP,
) -> Dict[str, Any]:
    if not images:
        raise ValueError("publish needs at least one image")
    if not label or not label.strip():
        raise ValueError("publish needs a label")
    if not isinstance(keep, int) or keep < 1:
        raise ValueError(f"keep must be a positive integer, got {keep!r}")
    if len(images) > MAX_IMAGES_PER_STEP:
        raise ValueError(f"at most {MAX_IMAGES_PER_STEP} images per step")
    for kind, value in (("label", label), ("note", note), ("command", command)):
        _check_text(kind, value)
    sdir = session_path(project, session)
    software = software or project

    opened: List[Tuple[int, str]] = []
    try:
        for p in images:
            opened.append(open_image(p))
        _private_root()
        with _locked(sdir):
            committed = _publish_locked(sdir, opened, label, software=software, command=command,
                                        note=note, reason=reason, keep=keep, project=project,
                                        session=session)
    finally:
        for fd, _ in opened:
            os.close(fd)
    return committed


def _private_root() -> None:
    root = sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)  # labels, notes and paths are nobody else's business


def _publish_locked(sdir: Path, opened: List[Tuple[int, str]], label: str, *, software: str,
                    command: Optional[str], note: Optional[str], reason: str, keep: int,
                    project: str, session: str) -> Dict[str, Any]:
    """The publish itself; the caller holds the session lock."""
    existing = pb.load_live_trajectory(sdir)
    step_no = int(existing.get("step_count") or 0) + 1
    fingerprint = pb.fingerprint_data([os.fstat(fd).st_size for fd, _ in opened] + [label, step_no])
    prep = pb.prepare_bundle(
        software=software,
        recipe=RECIPE,
        bundle_kind="capture",
        source_fingerprint=fingerprint,
        root_dir=str(sdir / "bundles"),
        force=True,
    )
    bundle_dir = Path(prep["bundle_dir"])
    artifacts = []
    try:
        for i, (fd, suffix) in enumerate(opened):
            dest = Path(prep["artifacts_dir"]) / _stored_name(i, suffix)
            _copy_fd(fd, dest)
            artifacts.append(
                pb.artifact_record(
                    str(bundle_dir), str(dest), artifact_id=dest.name,
                    role="hero" if i == 0 else "view", kind="image", label=dest.stem,
                )
            )
    except BaseException:
        shutil.rmtree(bundle_dir, ignore_errors=True)  # no manifest-less orphans
        raise
    summary = {"headline": label, **({"note": note} if note else {})}
    manifest = pb.finalize_bundle(
        bundle_dir=str(bundle_dir),
        bundle_id=prep["bundle_id"],
        bundle_kind="capture",
        software=software,
        recipe=RECIPE,
        source={"capture_fingerprint": fingerprint},
        artifacts=artifacts,
        summary=summary,
        cache_key=prep["cache_key"],
        generator={"name": "live_preview", "command": command or label},
    )
    _point_current(sdir, bundle_dir)
    trajectory = pb.append_live_trajectory(
        sdir,
        software=software,
        recipe=RECIPE,
        bundle_manifest=manifest,
        publish_reason=reason,
        project_name=project,
        session_name=session,
        command=command or label,
        stage_label=label,
        note=note,
    )

    state_path = sdir / "session.json"
    state: Dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    history = list(state.get("history") or [])
    history.append(trajectory["latest_step"])
    state.update(
        {
            "protocol_version": SESSION_PROTOCOL,
            "software": software,
            "recipe": RECIPE,
            "status": "live",
            "project_name": f"{project} / {session}",
            "current_link": "current",
            "current_bundle_id": manifest["bundle_id"],
            "current_step_id": trajectory["current_step_id"],
            "latest_command": command or label,
            "latest_publish_reason": reason,
            "trajectory_protocol_version": pb.TRAJECTORY_PROTOCOL_VERSION,
            "trajectory_step_count": trajectory["step_count"],
            "history": history[-keep:],
            "updated_at": _now(),
            "publish_command": f"live-preview publish --project {project} --session {session}",
        }
    )
    state.setdefault("created_at", state["updated_at"])
    write_json_atomic(state_path, state)
    # The step is committed; pruning is best-effort, so an rmtree failure must not
    # report the publish as failed (the caller would retry and duplicate the step).
    try:
        pruned = _prune(sdir, keep, bundle_dir)
    except OSError:
        pruned = 0

    result = {
        "session_dir": str(sdir),
        "step": trajectory["current_step_id"],
        "step_count": trajectory["step_count"],
        "bundle_id": manifest["bundle_id"],
    }
    if pruned:
        result["pruned_bundles"] = pruned
    return result


def status(project: str, session: str) -> Dict[str, Any]:
    sdir = session_path(project, session)
    state_path = sdir / "session.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"no session at {sdir}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    history = state.get("history") or []
    last = history[-1] if history else {}
    return {
        "session_dir": str(sdir),
        "step_count": state.get("trajectory_step_count", len(history)),
        "updated_at": state.get("updated_at"),
        "latest_label": last.get("stage_label"),
        "latest_note": last.get("note"),
    }


def list_sessions() -> List[Dict[str, Any]]:
    root = sessions_root()
    out = []
    for state_path in sorted(root.glob("*/*/session.json")):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "project": state_path.parent.parent.name,
                "session": state_path.parent.name,
                "step_count": state.get("trajectory_step_count"),
                "updated_at": state.get("updated_at"),
            }
        )
    return sorted(out, key=lambda r: r.get("updated_at") or "", reverse=True)
