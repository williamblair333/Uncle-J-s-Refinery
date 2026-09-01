#!/usr/bin/env python3
"""Tests for jscrub.

Every pre-mortem MEDIUM finding has a test named after it, so a regression
shows up as a named failure rather than a silent loss of the mitigation.

Run:  python3 scripts/jscrub/test_cli.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli  # noqa: E402

ZWSP = "​"  # zero width space
NBSP = " "  # no-break space
BOM = "﻿"


class TempTree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_cli(self, *argv: str) -> int:
        return cli.main([str(a) for a in argv])


class TestEngineWiring(TempTree):
    """The DRY option table must actually reach the engine."""

    def test_zero_width_is_removed(self) -> None:
        path = self.write("a.md", f"he{ZWSP}llo\n".encode())
        self.assertEqual(self.run_cli("clean", "-i", path), cli.EXIT_FINDINGS)
        self.assertEqual(path.read_bytes(), b"hello\n")

    def test_nbsp_normalised_to_plain_space(self) -> None:
        path = self.write("a.md", f"a{NBSP}b\n".encode())
        self.run_cli("clean", "-i", path)
        self.assertEqual(path.read_bytes(), b"a b\n")

    def test_no_normalize_spaces_flag_reaches_engine(self) -> None:
        path = self.write("a.md", f"a{NBSP}b\n".encode())
        self.run_cli("clean", "-i", path, "--no-normalize-spaces")
        self.assertEqual(path.read_bytes(), f"a{NBSP}b\n".encode())

    def test_emoji_zwj_sequence_is_preserved(self) -> None:
        original = "👨‍👩\n".encode()
        path = self.write("a.md", original)
        self.assertEqual(self.run_cli("clean", "-i", path), cli.EXIT_OK)
        self.assertEqual(path.read_bytes(), original)

    def test_clean_file_exits_zero(self) -> None:
        path = self.write("a.md", b"nothing to see\n")
        self.assertEqual(self.run_cli("audit", path), cli.EXIT_OK)


class TestFinding2BackupNeverClobbered(TempTree):
    def test_second_run_does_not_overwrite_the_original_backup(self) -> None:
        original = f"x{ZWSP}y\n".encode()
        path = self.write("a.md", original)

        self.run_cli("clean", "-i", path)
        bak = self.root / "a.md.bak"
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_bytes(), original)

        # Second pass: file is already clean, but force another backup cycle by
        # reintroducing a carrier. The first backup must survive untouched.
        path.write_bytes(f"x{ZWSP}y\n".encode())
        self.run_cli("clean", "-i", path)
        self.assertEqual(bak.read_bytes(), original, "run 2 clobbered run 1's backup")
        self.assertTrue((self.root / "a.md.bak.1").exists())

    def test_no_backup_flag_suppresses_sidecar(self) -> None:
        path = self.write("a.md", f"x{ZWSP}\n".encode())
        self.run_cli("clean", "-i", path, "--no-backup")
        self.assertFalse((self.root / "a.md.bak").exists())


class TestFinding3ByteFaithfulIO(TempTree):
    def test_crlf_line_endings_survive(self) -> None:
        path = self.write("a.txt", f"one\r\ntwo{ZWSP}\r\n".encode())
        self.run_cli("clean", "-i", path)
        self.assertEqual(path.read_bytes(), b"one\r\ntwo\r\n", "CRLF was rewritten to LF")

    def test_leading_bom_is_preserved(self) -> None:
        path = self.write("a.md", f"{BOM}hi{ZWSP}\n".encode())
        self.run_cli("clean", "-i", path)
        self.assertEqual(path.read_bytes(), f"{BOM}hi\n".encode())

    def test_invalid_utf8_is_refused_not_transcoded(self) -> None:
        original = b"caf\xe9\n"  # latin-1, not valid UTF-8
        path = self.write("a.txt", original)
        self.assertEqual(self.run_cli("clean", "-i", path), cli.EXIT_INCOMPLETE)
        self.assertEqual(path.read_bytes(), original, "file was transcoded")

    def test_binary_file_is_refused(self) -> None:
        original = b"\x89PNG\r\n\x00\x00hello\n"
        path = self.write("a.bin", original)
        self.assertEqual(self.run_cli("clean", "-i", path), cli.EXIT_INCOMPLETE)
        self.assertEqual(path.read_bytes(), original)

    def test_trailing_newline_not_invented(self) -> None:
        path = self.write("a.md", f"no trailing nl{ZWSP}".encode())
        self.run_cli("clean", "-i", path)
        self.assertEqual(path.read_bytes(), b"no trailing nl")


class TestFinding6SkipsAreLoud(TempTree):
    def test_unscannable_file_forces_exit_two(self) -> None:
        self.write("good.md", b"fine\n")
        self.write("bad.txt", b"caf\xe9\n")
        self.assertEqual(self.run_cli("audit", self.root), cli.EXIT_INCOMPLETE)

    def test_skip_outranks_findings(self) -> None:
        self.write("hit.md", f"a{ZWSP}\n".encode())
        self.write("bad.txt", b"caf\xe9\n")
        self.assertEqual(
            self.run_cli("audit", self.root),
            cli.EXIT_INCOMPLETE,
            "an unchecked file must not be reported as a mere finding",
        )

    def test_findings_alone_exit_one(self) -> None:
        self.write("hit.md", f"a{ZWSP}\n".encode())
        self.assertEqual(self.run_cli("audit", self.root), cli.EXIT_FINDINGS)

    def test_oversize_file_is_skipped_not_silently_passed(self) -> None:
        self.write("big.md", b"x" * 4096)
        self.assertEqual(
            self.run_cli("audit", self.root, "--max-bytes", "10"), cli.EXIT_INCOMPLETE
        )


class TestFinding7AtomicWrite(TempTree):
    def test_file_mode_is_preserved(self) -> None:
        path = self.write("a.sh", f"#!/bin/sh{ZWSP}\n".encode())
        os.chmod(path, 0o755)
        self.run_cli("clean", "-i", path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o755)

    def test_no_temp_files_left_behind(self) -> None:
        path = self.write("a.md", f"a{ZWSP}\n".encode())
        self.run_cli("clean", "-i", path)
        leftovers = [p.name for p in self.root.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_replaces_content_exactly(self) -> None:
        path = self.write("a.md", b"old\n")
        cli.atomic_write(path, b"new\n")
        self.assertEqual(path.read_bytes(), b"new\n")


class TestFinding10VendorProvenance(unittest.TestCase):
    def test_header_names_upstream_and_license(self) -> None:
        header = (Path(cli.__file__).parent / "text_unicode.py").read_text().split("\n", 12)[:12]
        blob = "\n".join(header)
        self.assertIn("VENDORED FILE — DO NOT EDIT", blob)
        self.assertIn("guillaumemeyer/watermarks-remover", blob)
        self.assertIn("MIT", blob)
        self.assertIn("c2c79590cbe5ce6f05cf53251cc0d02ebc216fff", blob)

    def test_header_is_exactly_twelve_lines(self) -> None:
        # check-vendor slices at 12; if the header grows the drift check breaks.
        lines = (Path(cli.__file__).parent / "text_unicode.py").read_text().split("\n")
        self.assertTrue(lines[11].startswith("# ═"), "line 12 must close the header block")
        self.assertTrue(lines[12].startswith('"""Layer A'), "line 13 must start upstream body")


class TestSelection(TempTree):
    def test_include_glob_limits_targets(self) -> None:
        self.write("keep.md", f"a{ZWSP}\n".encode())
        self.write("skip.py", f"b{ZWSP}\n".encode())
        self.run_cli("clean", "-i", self.root, "--include", "*.md")
        self.assertEqual((self.root / "keep.md").read_bytes(), b"a\n")
        self.assertEqual((self.root / "skip.py").read_bytes(), f"b{ZWSP}\n".encode())

    def test_skip_dirs_are_not_walked(self) -> None:
        self.write(".git/config.md", f"a{ZWSP}\n".encode())
        self.assertEqual(self.run_cli("audit", self.root), cli.EXIT_INCOMPLETE)  # no files matched

    def test_symlinks_not_followed_by_default(self) -> None:
        outside = self.write("real.md", f"a{ZWSP}\n".encode())
        tree = self.root / "tree"
        tree.mkdir()
        try:
            (tree / "link.md").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.run_cli("clean", "-i", tree)
        self.assertEqual(outside.read_bytes(), f"a{ZWSP}\n".encode(), "wrote through a symlink")


class TestNonDestructiveDefaults(TempTree):
    def test_dry_run_writes_nothing(self) -> None:
        original = f"a{ZWSP}\n".encode()
        path = self.write("a.md", original)
        self.assertEqual(self.run_cli("clean", "-i", path, "--dry-run"), cli.EXIT_FINDINGS)
        self.assertEqual(path.read_bytes(), original)

    def test_inspect_never_writes(self) -> None:
        original = f"a{ZWSP}\n".encode()
        path = self.write("a.md", original)
        self.run_cli("inspect", path)
        self.assertEqual(path.read_bytes(), original)

    def test_output_and_in_place_are_mutually_exclusive(self) -> None:
        path = self.write("a.md", b"x\n")
        self.assertEqual(
            self.run_cli("clean", path, "-i", "-o", str(self.root / "out.md")),
            cli.EXIT_INCOMPLETE,
        )

    def test_refuses_multiple_files_to_stdout(self) -> None:
        self.write("a.md", b"x\n")
        self.write("b.md", b"y\n")
        self.assertEqual(self.run_cli("clean", self.root), cli.EXIT_INCOMPLETE)


class TestOptionTableIsSingleSource(unittest.TestCase):
    """The DRY claim: argparse dests must match what engine_kwargs reads."""

    def test_every_engine_opt_dest_matches_argparse(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["clean", "x.md"])
        for opt in cli.ENGINE_OPTS:
            self.assertTrue(
                hasattr(args, opt.dest),
                f"{opt.flags} declares dest {opt.dest!r} that argparse never sets",
            )

    def test_engine_kwargs_match_clean_text_signature(self) -> None:
        import inspect as _inspect

        from text_unicode import clean_text, inspect_text

        parser = cli.build_parser()
        args = parser.parse_args(["clean", "x.md"])
        clean_params = set(_inspect.signature(clean_text).parameters)
        inspect_params = set(_inspect.signature(inspect_text).parameters)
        self.assertLessEqual(set(cli.engine_kwargs(args, "clean_kw")), clean_params)
        self.assertLessEqual(set(cli.engine_kwargs(args, "inspect_kw")), inspect_params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
