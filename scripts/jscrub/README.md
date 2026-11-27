# jscrub

Find and remove Unicode characters that are hard to see but can break diffs, `grep`, and copy-paste. A lookalike space, for example, can make a search miss text that looks like a match. The tool checks for zero-width characters, bidi controls that affect reading order, tag characters, private-use codepoints, noncharacters, and lookalike spaces.

```bash
./scripts/jscrub/jscrub --help
./scripts/jscrub/jscrub inspect README.md
./scripts/jscrub/jscrub clean --in-place docs/
./scripts/jscrub/jscrub audit . --include '*.py' --quiet
```

Runs on Python 3.10+ using only its standard library. It needs no virtual environment, background service, or network access.

## Commands

| Command | Writes? | Use |
|---|---|---|
| `inspect PATH…` | never | What invisible characters are in here, and where |
| `clean PATH…` | Prints by default. Use `-i` to rewrite | Remove them |
| `audit PATH…` | never | Scans a directory and exits with a code that CI can act on |
| `check-vendor UPSTREAM` | never | Does the bundled engine still match its source? |

Directories are walked by every command. `.git`, `node_modules`, `__pycache__`,
`.venv`, `dist`, `build` and friends are skipped.

## Exit codes

```
0  scanned everything; nothing found
1  scanned everything; hits found / changes made
2  at least one target could not be scanned
```

An `audit` run reports whether it found a problem, found clean files, or could not finish checking. A skipped file might still contain bad characters. **Treat `2` as a failure in CI**, not a pass:

```bash
jscrub audit . --include '*.md' || exit 1
```

If the tool finds problems and also skips files, it exits `2`, not `1`. A file it couldn't check is an unknown, and an unknown counts for more than a problem it found.

(argparse also exits `2` on a usage error; those are distinguishable by the
`usage:` banner on stderr.)

## Safety properties

Each guarantee has a named test in `test_cli.py`.

- **Byte-faithful I/O.** Files are read and written as bytes. CRLF line endings
  survive, a leading UTF-8 BOM is preserved, and a missing trailing newline is
  not invented. Text-mode I/O would silently rewrite every line of a
  Windows-authored file.
- **No encoding guessing.** A file that is not valid UTF-8 is refused and
  counted as skipped, never transcoded through a latin-1 fallback. Files with a
  NUL byte in the first 8 KB are treated as binary and refused.
- **Atomic writes.** Content goes to a temp file in the same directory, is
  `fsync`ed, then `os.replace`d. An interrupt mid-run leaves the original
  wholly intact; file mode is preserved.
- **Backups are never clobbered.** `--in-place` writes `foo.md.bak`; a second
  run writes `foo.md.bak.1` rather than overwriting run 1's original.
  `--no-backup` opts out.
- **Symlinks are not followed** when walking a tree, so a link cannot redirect
  writes outside the directory you named. `--follow-symlinks` opts in.
- **Non-destructive by default.** `clean` writes to stdout; `-i`/`--in-place`
  is the explicit opt-in, and `--dry-run` reports without writing.
- **Size cap.** `--max-bytes` (default 10 MB) refuses oversize input rather
  than loading it whole into memory.

## Two behaviours worth knowing

**`inspect` is louder than `clean`, on purpose.** Bidi controls are legitimate
in RTL prose, so `clean` preserves them by default while `inspect` still
reports them. Pass `--strip-bidi` to remove them. This is upstream's design
(`inspect_text` calls the engine with `strip_bidi=True`, `clean_text` defaults
it to `False`) and is not a bug.

**Load-bearing invisibles are preserved.** Emoji ZWJ and variation selectors
(👨‍👩‍👧, ❤️‍🔥), script joiners in Arabic/Devanagari, complete flag tag sequences,
Mongolian free variation selectors, Khmer inherent vowels and Hangul jamo
fillers are all kept when they follow a base from their own script. Stripping
them visibly changes the text. `--strip-emoji-glue` opts into removing them.

## Vendored engine

`text_unicode.py` is vendored: this repo keeps a copy of a file from another project. **Don't edit it.** The next time someone copies it in again from upstream, local edits are lost.

| | |
|---|---|
| Upstream | <https://github.com/guillaumemeyer/watermarks-remover> |
| Path | `service/scripts/text_unicode.py` |
| Commit | `c2c79590cbe5ce6f05cf53251cc0d02ebc216fff` (2026-08-23) |
| Repo HEAD at vendor time | `be38ccc35e8ec39c3db3f420023fcdae1527cb79` |
| License | MIT — Copyright (c) 2026 Guillaume Meyer and contributors |
| Vendored | 2026-09-01 |

The only local addition is a 12-line comment above the module docstring (the description at the top of the file) that records where it came from. So:

```bash
tail -n +13 scripts/jscrub/text_unicode.py   # == the upstream file, byte for byte
```

### Checking it — two different questions

`check-vendor` answers two questions that need different evidence. Keep them
apart: a passing run of the first is **not** evidence for the second.

| Question | Command | Needs a checkout? |
|---|---|---|
| Has our copy been modified locally? | `jscrub check-vendor` | no |
| Has upstream moved on since we vendored? | `jscrub check-vendor PATH` | yes |

```bash
jscrub check-vendor
#   unmodified since vendoring  (sha256 ed86ed9715f40e30…)
```

The first check compares a fingerprint of the file with `UPSTREAM_BODY_SHA256` in `cli.py`. It runs anywhere, including CI. For the second check, pass the upstream copy at `reviewed/watermarks-remover` in the main checkout (not in a worktree). Git ignores that directory.

`just audit` (`scripts/jscrub/audit-repo.sh`) runs `check-vendor` plus `audit`
over git-tracked text files, and CI job `test-jscrub` runs the unit tests and
then the same script. Both are read-only. `clean`, `--in-place` and
`--follow-symlinks` are deliberately not wired into any automation.

The maintainers recorded the fingerprint after checking that the file matched the upstream copy byte for byte.

**This catches accidents; it can't prove nobody tampered with the file.** Someone with write access can change both the file and the fingerprint in the same commit. Check Git history when investigating deliberate changes.

To re-vendor: copy the upstream file in, re-apply the 12-line header, bump the
commit and date above, run `jscrub check-vendor` and paste the computed digest
into `UPSTREAM_BODY_SHA256`, then re-run the tests. The failure message prints
the digest for exactly this reason.

### What is deliberately not vendored

Upstream also removes C2PA Content Credentials, SynthID and statistical
token-sampling watermarks, and ships a `stealer/` module that reconstructs a
target model's watermark scorer. None of that is here. `jscrub` is scoped to
text hygiene — the characters that break tooling — not to making
AI-generated content unidentifiable as AI-generated.

For the provenance-stripping and binary-format side (PDF, DOCX, PNG, MP4…),
use upstream directly; it has a Docker service and a much wider format matrix.

## Extending it

Options live in one table at the top of `cli.py` — `ENGINE_OPTS`, `IO_OPTS`,
`WRITE_OPTS`. Each row carries its flags, its help text, and the engine keyword
it maps to. Adding an option takes one row: the argparse wiring, the `--help` output and the kwargs handed to the engine all derive from it, so they cannot drift apart. `TestOptionTableIsSingleSource` asserts every declared dest exists on the
parsed namespace and that the derived kwargs match the engine signatures.

## Tests

```bash
python3 scripts/jscrub/test_cli.py
```

35 tests, stdlib `unittest`, no dependencies. Test classes are named after the
pre-mortem findings they lock in (`TestFinding2BackupNeverClobbered`,
`TestFinding3ByteFaithfulIO`, `TestFinding6SkipsAreLoud`,
`TestFinding7AtomicWrite`, `TestFinding10VendorProvenance`, `TestVendorPin`)
so a regression surfaces as a named failure rather than a quietly lost
mitigation.

Linting is not part of CI here — this repo has no `ruff.toml` and `ruff` is not
installed on this host. It was run through `uvx` against default rules:

```bash
uvx ruff check scripts/jscrub/     # All checks passed!
```

Invisible characters in the test fixtures are built with `chr(0x200B)` rather
than written as literals, so the tool does not flag its own source and ruff's
`PLE2515` stays quiet. `jscrub audit scripts/` is clean across all 55 files.
