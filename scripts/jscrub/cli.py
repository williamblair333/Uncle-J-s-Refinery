#!/usr/bin/env python3
"""jscrub — inspect, clean and audit text files for invisible Unicode.

Layer A hygiene only: zero-width characters, bidi controls, tag characters,
private-use codepoints, noncharacters and space homoglyphs — the things that
break diffs, grep, and copy-paste. The cleaning engine is vendored from
watermarks-remover (see README.md); this module is the file-handling layer.

Deliberately out of scope: C2PA / SynthID / statistical-watermark removal and
anything that exists to make AI-generated content unidentifiable as such.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from text_unicode import clean_text, inspect_text  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Exit codes.  The three-way split is the point: a CI job must be able to tell
# "scanned it, it is clean" from "never managed to scan it".  Collapsing those
# is how a tool reports a green tree it never looked at.
# ─────────────────────────────────────────────────────────────────────────────
EXIT_OK = 0  # every target scanned; nothing to report
EXIT_FINDINGS = 1  # every target scanned; hits found / changes made
EXIT_INCOMPLETE = 2  # at least one target could not be scanned

MAX_BYTES_DEFAULT = 10 * 1024 * 1024
UTF8_BOM = b"\xef\xbb\xbf"

SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", ".bzr",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "node_modules", ".venv", "venv", ".tox", ".eggs",
        "dist", "build", ".next", ".nuxt", ".svelte-kit",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# DRY option table.
#
# Every flag is declared exactly once, here, together with the engine keyword
# it maps to.  Adding a knob is one row: argparse wiring, the --help text and
# the kwargs handed to the engine all derive from it, so they cannot drift
# apart.  `clean_kw` / `inspect_kw` differ because the two engine entry points
# spell some options differently.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Opt:
    flags: tuple[str, ...]
    help: str
    clean_kw: str | None = None
    inspect_kw: str | None = None
    action: str = "store_true"
    default: object = None
    metavar: str | None = None
    type: Callable | None = None

    def add_to(self, parser: argparse.ArgumentParser) -> None:
        kw: dict = {"help": self.help, "action": self.action}
        if self.action in ("store_true", "store_false"):
            pass
        else:
            kw["metavar"] = self.metavar
            kw["type"] = self.type
        if self.default is not None:
            kw["default"] = self.default
        parser.add_argument(*self.flags, **kw)

    @property
    def dest(self) -> str:
        return self.flags[-1].lstrip("-").replace("-", "_")


# Engine behaviour — shared by inspect, clean and audit so the three always
# agree on what counts as a hit.
ENGINE_OPTS: tuple[Opt, ...] = (
    Opt(
        ("--nfkc",),
        "Apply NFKC normalisation after stripping (folds ﬁ→fi, ①→1, fullwidth→ASCII)",
        clean_kw="nfkc",
    ),
    Opt(
        ("--aggressive-homoglyphs",),
        "Also map confusable Cyrillic/fullwidth letters to ASCII (е→e, Ａ→A)",
        clean_kw="aggressive_homoglyphs",
        inspect_kw="aggressive",
    ),
    Opt(
        ("--no-normalize-spaces",),
        "Leave exotic spaces (NBSP, en/em space, ideographic space) alone",
        clean_kw="normalize_spaces",
        action="store_false",
    ),
    Opt(
        ("--strip-emoji-glue",),
        "Also strip ZWJ/variation selectors that bind emoji sequences "
        "(destructive: breaks 👨‍👩‍👧 and ❤️‍🔥)",
        clean_kw="strip_emoji_glue",
        inspect_kw="strip_emoji_glue",
    ),
    Opt(
        ("--strip-bidi",),
        "Also strip directional controls. Preserved by default because they are "
        "legitimate in RTL prose; inspect reports them either way",
        clean_kw="strip_bidi",
    ),
)

# File selection and reporting — shared by every subcommand.
IO_OPTS: tuple[Opt, ...] = (
    Opt(("--json",), "Emit machine-readable JSON instead of a human report"),
    Opt(("-q", "--quiet"), "Only report files with findings or problems"),
    Opt(
        ("--max-bytes",),
        f"Refuse files larger than N bytes (default {MAX_BYTES_DEFAULT})",
        action="store",
        type=int,
        default=MAX_BYTES_DEFAULT,
        metavar="N",
    ),
    Opt(
        ("--include",),
        "Only consider files matching this glob; repeatable (e.g. --include '*.md')",
        action="append",
        metavar="GLOB",
    ),
    Opt(
        ("--exclude",),
        "Skip files matching this glob; repeatable",
        action="append",
        metavar="GLOB",
    ),
    Opt(
        ("--follow-symlinks",),
        "Follow symlinks when walking directories (off by default: a symlink "
        "can redirect writes outside the tree you named)",
    ),
)

WRITE_OPTS: tuple[Opt, ...] = (
    Opt(("-i", "--in-place"), "Rewrite files on disk (default: write to stdout)"),
    Opt(("-o", "--output"), "Write result here (single input file only)", action="store", metavar="PATH"),
    Opt(("-n", "--dry-run"), "Report what would change without writing anything"),
    Opt(("--no-backup",), "Skip the .bak sidecar that --in-place writes by default"),
)


def engine_kwargs(args: argparse.Namespace, attr: str) -> dict:
    """Build engine kwargs straight from the option table — no per-flag code."""
    out = {}
    for opt in ENGINE_OPTS:
        name = getattr(opt, attr)
        if name is not None:
            out[name] = getattr(args, opt.dest)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# File I/O.  Everything here is byte-level on purpose: reading in text mode
# would translate CRLF→LF on the way in and write LF back out, silently
# rewriting every line of a Windows-authored file that had one stray zero-width
# character in it.
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class FileResult:
    path: Path
    status: str  # "clean" | "findings" | "skipped"
    reason: str = ""
    removed: int = 0
    replaced: int = 0
    hits: list = field(default_factory=list)
    written: bool = False

    @property
    def exit_contribution(self) -> int:
        return {"clean": EXIT_OK, "findings": EXIT_FINDINGS, "skipped": EXIT_INCOMPLETE}[self.status]


def decode_file(path: Path, max_bytes: int) -> tuple[str, bool]:
    """Return (text, had_bom). Raises ValueError with a human reason on refusal."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"cannot stat: {exc.strerror or exc}") from exc
    if size > max_bytes:
        raise ValueError(f"larger than --max-bytes ({size} > {max_bytes})")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read: {exc.strerror or exc}") from exc

    had_bom = raw.startswith(UTF8_BOM)
    if had_bom:
        raw = raw[len(UTF8_BOM) :]
    # A NUL in the head is the cheap, reliable binary tell; decoding a binary
    # that happens to hold valid UTF-8 runs and writing it back mangles it.
    if b"\x00" in raw[:8192]:
        raise ValueError("looks binary (NUL byte in first 8KB)")
    try:
        return raw.decode("utf-8"), had_bom
    except UnicodeDecodeError as exc:
        # Never guess an encoding: a latin-1 fallback would silently transcode
        # the file into different bytes. Refuse and say so.
        raise ValueError(f"not valid UTF-8 (byte {exc.start})") from exc


def backup_path(path: Path) -> Path:
    """Never overwrite an existing backup — run 2 would clobber run 1's original."""
    candidate = path.with_name(path.name + ".bak")
    counter = 0
    while candidate.exists():
        counter += 1
        candidate = path.with_name(f"{path.name}.bak.{counter}")
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    """Write via temp file + os.replace, so an interrupt leaves the original intact."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)  # atomic on POSIX
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def iter_targets(
    paths: Sequence[Path],
    *,
    include: Sequence[str] | None,
    exclude: Sequence[str] | None,
    follow_symlinks: bool,
) -> Iterator[Path]:
    """Yield files. Directories are walked; symlinks are skipped unless asked for."""
    seen: set[Path] = set()

    def matches(candidate: Path) -> bool:
        if include and not any(candidate.match(pattern) for pattern in include):
            return False
        return not (exclude and any(candidate.match(pattern) for pattern in exclude))

    for path in paths:
        if path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=follow_symlinks):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in sorted(files):
                    candidate = Path(root) / name
                    if not follow_symlinks and candidate.is_symlink():
                        continue
                    if matches(candidate) and candidate not in seen:
                        seen.add(candidate)
                        yield candidate
        elif path not in seen:
            seen.add(path)
            yield path


# ─────────────────────────────────────────────────────────────────────────────
# Per-file work.  inspect/clean/audit all funnel through one function so the
# three subcommands cannot disagree about what a hit is.
# ─────────────────────────────────────────────────────────────────────────────
def process(path: Path, args: argparse.Namespace, *, mutate: bool) -> FileResult:
    try:
        text, had_bom = decode_file(path, args.max_bytes)
    except ValueError as exc:
        return FileResult(path, "skipped", reason=str(exc))

    if not mutate:
        report = inspect_text(text, **engine_kwargs(args, "inspect_kw"))
        status = "findings" if report.suspicious_total else "clean"
        return FileResult(
            path,
            status,
            removed=report.suspicious_total,
            hits=report.to_dict()["hits"],
        )

    cleaned, stats = clean_text(text, **engine_kwargs(args, "clean_kw"))
    changed = stats["removed_count"] + stats["replaced_count"]
    result = FileResult(
        path,
        "findings" if changed else "clean",
        removed=stats["removed_count"],
        replaced=stats["replaced_count"],
    )
    if not changed or args.dry_run or not args.in_place:
        return result

    payload = (UTF8_BOM if had_bom else b"") + cleaned.encode("utf-8")
    try:
        if not args.no_backup:
            shutil.copy2(path, backup_path(path))
        atomic_write(path, payload)
    except OSError as exc:
        return FileResult(path, "skipped", reason=f"cannot write: {exc.strerror or exc}")
    result.written = True
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
def render(results: list[FileResult], args: argparse.Namespace, command: str) -> None:
    scanned = [r for r in results if r.status != "skipped"]
    skipped = [r for r in results if r.status == "skipped"]
    findings = [r for r in results if r.status == "findings"]

    if args.json:
        json.dump(
            {
                "command": command,
                "files_scanned": len(scanned),
                "files_with_findings": len(findings),
                "files_skipped": len(skipped),
                "results": [
                    {
                        "path": str(r.path),
                        "status": r.status,
                        "reason": r.reason,
                        "removed": r.removed,
                        "replaced": r.replaced,
                        "written": r.written,
                        **({"hits": r.hits} if r.hits else {}),
                    }
                    for r in results
                    if not args.quiet or r.status != "clean"
                ],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return

    for result in results:
        if args.quiet and result.status == "clean":
            continue
        if result.status == "skipped":
            print(f"  skip  {result.path}  ({result.reason})")
        elif result.status == "clean":
            print(f"  ok    {result.path}")
        else:
            if command == "clean":
                detail = f"{result.removed} removed, {result.replaced} replaced"
                suffix = "" if result.written else "  (not written)"
            else:
                detail = f"{result.removed} suspicious"
                suffix = ""
            print(f"  HIT   {result.path}  ({detail}){suffix}")
            for hit in result.hits[:10]:
                print(f"          {hit['kind']}/{hit['confidence']}  {hit['label']}  x{hit['count']}")

    parts = [f"{len(scanned)} scanned", f"{len(findings)} with findings"]
    if skipped:
        parts.append(f"{len(skipped)} SKIPPED (not checked)")
    sys.stdout.flush()  # summary goes to stderr; keep it after the listing
    print(f"\n{', '.join(parts)}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────
def run_scan(args: argparse.Namespace, command: str, *, mutate: bool) -> int:
    targets = list(
        iter_targets(
            args.paths,
            include=args.include,
            exclude=args.exclude,
            follow_symlinks=args.follow_symlinks,
        )
    )
    if not targets:
        print("no files matched", file=sys.stderr)
        return EXIT_INCOMPLETE

    results = [process(path, args, mutate=mutate) for path in targets]
    render(results, args, command)
    # Worst outcome wins: "could not check" outranks "found something",
    # because an unchecked file is an unknown, not a pass.
    return max(r.exit_contribution for r in results)


def cmd_inspect(args: argparse.Namespace) -> int:
    return run_scan(args, "inspect", mutate=False)


def cmd_audit(args: argparse.Namespace) -> int:
    return run_scan(args, "audit", mutate=False)


def cmd_clean(args: argparse.Namespace) -> int:
    if args.output:
        if args.in_place:
            print("--output and --in-place are mutually exclusive", file=sys.stderr)
            return EXIT_INCOMPLETE
        if len(args.paths) != 1 or args.paths[0].is_dir():
            print("--output takes exactly one input file", file=sys.stderr)
            return EXIT_INCOMPLETE
        try:
            text, had_bom = decode_file(args.paths[0], args.max_bytes)
        except ValueError as exc:
            print(f"  skip  {args.paths[0]}  ({exc})", file=sys.stderr)
            return EXIT_INCOMPLETE
        cleaned, stats = clean_text(text, **engine_kwargs(args, "clean_kw"))
        atomic_write(Path(args.output), (UTF8_BOM if had_bom else b"") + cleaned.encode("utf-8"))
        print(
            f"  ok    {args.output}  ({stats['removed_count']} removed, "
            f"{stats['replaced_count']} replaced)",
            file=sys.stderr,
        )
        return EXIT_FINDINGS if stats["removed_count"] + stats["replaced_count"] else EXIT_OK

    if not args.in_place:
        # Default is non-destructive: stream one file to stdout.
        if len(args.paths) != 1 or args.paths[0].is_dir():
            print(
                "refusing to write multiple files to stdout — pass --in-place "
                "to rewrite them, or -o for a single output file",
                file=sys.stderr,
            )
            return EXIT_INCOMPLETE
        try:
            text, _ = decode_file(args.paths[0], args.max_bytes)
        except ValueError as exc:
            print(f"  skip  {args.paths[0]}  ({exc})", file=sys.stderr)
            return EXIT_INCOMPLETE
        cleaned, stats = clean_text(text, **engine_kwargs(args, "clean_kw"))
        sys.stdout.write(cleaned)
        return EXIT_FINDINGS if stats["removed_count"] + stats["replaced_count"] else EXIT_OK

    return run_scan(args, "clean", mutate=True)


def cmd_check_vendor(args: argparse.Namespace) -> int:
    """Compare the vendored engine against an upstream checkout (pre-mortem #4)."""
    here = Path(__file__).resolve().parent
    vendored = here / "text_unicode.py"
    upstream = Path(args.upstream) / "service" / "scripts" / "text_unicode.py"
    if not upstream.is_file():
        print(f"upstream file not found: {upstream}", file=sys.stderr)
        return EXIT_INCOMPLETE
    # Drop the 12-line provenance header; the rest is verbatim upstream.
    body = b"\n".join(vendored.read_bytes().split(b"\n")[12:])
    if body == upstream.read_bytes():
        print("vendored engine is byte-identical to upstream")
        return EXIT_OK
    print("VENDOR DRIFT: vendored engine differs from upstream", file=sys.stderr)
    print(f"  diff <(tail -n +13 {here / 'text_unicode.py'}) {upstream}", file=sys.stderr)
    return EXIT_FINDINGS


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────
EXAMPLES = """\
examples:
  # What invisible characters are in this file?
  jscrub inspect README.md

  # Same, as JSON, for a script to consume
  jscrub inspect README.md --json

  # Preview a clean without touching anything (default writes to stdout)
  jscrub clean notes.md | diff notes.md -

  # Rewrite a whole tree in place, keeping a .bak beside each changed file
  jscrub clean --in-place docs/

  # Markdown only, no backups, show only what changed
  jscrub clean -i . --include '*.md' --no-backup --quiet

  # See what a tree-wide clean would do, without writing
  jscrub clean -i docs/ --dry-run

  # CI gate: fail the build if any tracked file carries invisible Unicode
  jscrub audit . --include '*.py' --include '*.md' --quiet
  #   exit 0 = scanned, clean
  #   exit 1 = scanned, hits found
  #   exit 2 = something could not be scanned (treat as failure too)

  # Fold fullwidth/Cyrillic lookalikes as well (more aggressive)
  jscrub clean -i src/ --aggressive-homoglyphs --nfkc

  # Has the vendored engine drifted from upstream?
  jscrub check-vendor ../review/watermarks-remover

notes:
  * inspect reports bidi controls that clean preserves by default — bidi marks
    are legitimate in RTL prose. Pass --strip-bidi to remove them too.
  * emoji glue (ZWJ, variation selectors) is preserved by default; stripping it
    visibly breaks 👨‍👩‍👧 and ❤️‍🔥. --strip-emoji-glue opts in.
  * files that are not valid UTF-8 are refused, never transcoded, and counted
    as skipped so a clean report cannot hide them.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jscrub",
        description=__doc__.split("\n\n")[0],
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # One loop builds all three scanning subcommands from the option tables.
    specs = (
        ("inspect", "Report invisible Unicode without changing anything", cmd_inspect, False),
        ("clean", "Remove invisible Unicode from files", cmd_clean, True),
        ("audit", "Walk a tree and report findings; exit code suits a CI gate", cmd_audit, False),
    )
    for name, help_text, handler, writes in specs:
        sub = subparsers.add_parser(
            name,
            help=help_text,
            description=help_text,
            epilog=EXAMPLES,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub.add_argument("paths", nargs="+", type=Path, metavar="PATH", help="files or directories")
        for opt in ENGINE_OPTS:
            opt.add_to(sub)
        for opt in IO_OPTS:
            opt.add_to(sub)
        if writes:
            for opt in WRITE_OPTS:
                opt.add_to(sub)
        sub.set_defaults(handler=handler)

    vendor = subparsers.add_parser(
        "check-vendor",
        help="Verify the vendored engine still matches upstream",
        description="Compare scripts/jscrub/text_unicode.py against an upstream checkout.",
    )
    vendor.add_argument("upstream", help="path to a watermarks-remover checkout")
    vendor.set_defaults(handler=cmd_check_vendor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
