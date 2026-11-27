# Contributing to Uncle J's Refinery

## Quick start

Clone the repository and run the installer from its directory.

```bash
git clone https://github.com/williamblair333/Uncle-J-s-Refinery.git
cd Uncle-J-s-Refinery
./install.sh
```

## Making changes

1. Fork the repository (make a copy under your account) and create a branch for your work.
2. Make your changes on that branch.
3. Run the session-end checklist before you commit. Git runs a pre-commit hook,
   a script that blocks the commit if `CHANGELOG.md` or `HANDOFF.md` updates are
   missing.
   ```bash
   # The hook blocks commits missing CHANGELOG.md or HANDOFF.md updates.
   # Run the session-end-checklist skill, or update manually.
   git commit -m "feat: your change"
   ```
4. Push your branch and open a pull request so others can review your changes.

## Commit message format

```
type: short description (72 chars max)

Optional longer explanation. Reference issues with #123.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`

## Session-end documentation standard

Every commit that touches code files must update `CHANGELOG.md` and `HANDOFF.md`.
For the full rules and instructions for setting up `.session-end.yml`, see
[docs/SESSION-END.md](docs/SESSION-END.md).

## Code style

- Bash scripts must pass the `bash -n` syntax check. Check all shell scripts with
  `find . -name '*.sh' -exec bash -n {} \;`.
- Follow PEP 8, the Python style guide. Find the tests in `tests/` and run them
  with `uv run pytest`.
- Add `set -euo pipefail` at the top of shell scripts.

## License

By contributing, you agree to license your work under [AGPL-3.0](LICENSE).
This is a strong copyleft license. It requires modifications and
network-deployed versions to be released under AGPL-3.0 as well.
