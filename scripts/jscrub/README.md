# jscrub

Invisible-Unicode hygiene for text files: find and remove the zero-width
characters, bidi controls, tag characters, private-use codepoints,
noncharacters and space homoglyphs that break diffs, `grep`, and copy-paste.

```bash
./scripts/jscrub/jscrub --help
./scripts/jscrub/jscrub inspect README.md
./scripts/jscrub/jscrub clean --in-place docs/
./scripts/jscrub/jscrub audit . --include '*.py' --quiet
```

Stdlib-only, Python 3.10+. No venv, no service, no network.

## Commands

| Command | Writes? | Use |
|---|---|---|
| `inspect PATH…` | never | What invisible characters are in here, and where |
| `clean PATH…` | stdout by default; `-i` to rewrite | Remove them |
| `audit PATH…` | never | Tree sweep with a CI-shaped exit code |
| `check-vendor UPSTREAM` | never | Has the vendored engine drifted? |

Directories are walked by every command. `.git`, `node_modules`, `__pycache__`,
`.venv`, `dist`, `build` and friends are skipped.

## Exit codes

```
0  scanned everything; nothing found
1  scanned everything; hits found / changes made
2  at least one target could not be scanned
```

The three-way split is the whole point of the `audit` command. A tool that
collapses "scanned it, it's clean" into "never managed to scan it" reports a
green tree it never looked at. **Treat `2` as a failure in CI**, not a pass:

```bash
jscrub audit . --include '*.md' || exit 1
```

When a run produces both findings and skips, the exit code is `2` — an
unchecked file is an unknown, and an unknown outranks a known finding.

(argparse also exits `2` on a usage error; those are distinguishable by the
`usage:` banner on stderr.)

## Safety properties

These are not incidental — each one has a named test in `test_cli.py`.

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

`text_unicode.py` is vendored, **not** first-party. Do not edit it — changes
are destroyed on the next re-vendor.

| | |
|---|---|
| Upstream | <https://github.com/guillaumemeyer/watermarks-remover> |
| Path | `service/scripts/text_unicode.py` |
| Commit | `c2c79590cbe5ce6f05cf53251cc0d02ebc216fff` (2026-08-23) |
| Repo HEAD at vendor time | `be38ccc35e8ec39c3db3f420023fcdae1527cb79` |
| License | MIT — Copyright (c) 2026 Guillaume Meyer and contributors |
| Vendored | 2026-09-01 |

It is taken unmodified. The only local addition is a 12-line provenance
comment block above the module docstring, so:

```bash
tail -n +13 scripts/jscrub/text_unicode.py   # == the upstream file, byte for byte
```

To check for drift against a checkout:

```bash
jscrub check-vendor /path/to/watermarks-remover
```

To re-vendor: copy the upstream file in, re-apply the 12-line header, bump the
commit and date above, and re-run the tests.

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
it maps to. Adding a knob is one row: the argparse wiring, the `--help` output
and the kwargs handed to the engine all derive from it, so they cannot drift
apart. `TestOptionTableIsSingleSource` asserts every declared dest exists on the
parsed namespace and that the derived kwargs match the engine signatures.

## Tests

```bash
python3 scripts/jscrub/test_cli.py
```

30 tests, stdlib `unittest`, no dependencies. Test classes are named after the
pre-mortem findings they lock in (`TestFinding2BackupNeverClobbered`,
`TestFinding3ByteFaithfulIO`, `TestFinding6SkipsAreLoud`,
`TestFinding7AtomicWrite`, `TestFinding10VendorProvenance`) so a regression
surfaces as a named failure rather than a quietly lost mitigation.
