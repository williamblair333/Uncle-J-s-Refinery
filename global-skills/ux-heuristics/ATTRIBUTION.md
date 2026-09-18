# Attribution

`SKILL.md` in this directory is vendored unmodified from:

- **Source:** https://github.com/wondelai/skills (`ux-heuristics/SKILL.md`)
- **Author:** Wondel.ai sp. z o.o.
- **License:** MIT — full text in `LICENSE` beside this file
- **Version vendored:** 1.6.0
- **Vendored:** 2026-09-18

MIT permits commercial use, which is why this skill was chosen over the
CC BY-NC-SA product-management skill packs surveyed at the same time. Keep
`LICENSE` and this file with `SKILL.md` if it moves.

To update: re-fetch the file from the source repo and bump the version above.
Do not edit `SKILL.md` in place — local changes make the next update a merge,
and the attribution above would no longer describe what is here.

## How it is used here

`features/product-quality/install.sh` links this skill into `~/.claude/skills/`.
It is the UI half of the product-quality system: a changed interface — a web UI,
a TUI, or a CLI's terminal output — gets audited against Nielsen's heuristics
with severity ratings, and severity 3 (major) or 4 (catastrophic) findings block
release. See `docs/superpowers/specs/2026-09-18-product-quality-system-design.md`.
