# Contributing to Uncle J's Refinery

## Quick start

```bash
git clone https://github.com/wblair8689/Uncle-J-s-Refinery.git
cd Uncle-J-s-Refinery
./install.sh
```

## Making changes

1. Fork the repo and create a branch
2. Make your changes
3. Run the session-end checklist before committing — the pre-commit hook will enforce it:
   ```bash
   # The hook blocks commits missing CHANGELOG.md or HANDOFF.md updates.
   # Run the session-end-checklist skill, or update manually.
   git commit -m "feat: your change"
   ```
4. Push and open a pull request

## Commit message format

```
type: short description (72 chars max)

Optional longer explanation. Reference issues with #123.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`

## Session-end documentation standard

Every commit that touches code files must update `CHANGELOG.md` and `HANDOFF.md`.
See [docs/SESSION-END.md](docs/SESSION-END.md) for the full standard and how to
configure `.session-end.yml` for your workflow.

## Code style

- **Bash**: scripts must pass `bash -n` (syntax check). Run `find . -name '*.sh' -exec bash -n {} \;`
- **Python**: follow PEP 8. Tests live in `tests/` and run with `uv run pytest`
- **Shell scripts**: add `set -euo pipefail` at the top

## License

By contributing, you agree your contributions are licensed under
[AGPL-3.0](LICENSE). This is a strong copyleft license — modifications and
network-deployed versions must also be released under AGPL-3.0.
