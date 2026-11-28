# Leonxlnx/taste-skill

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/Leonxlnx/taste-skill
- Stars: 122447 (gh, 2026-11-28)
- Licence: MIT
- Last commit: 2026-11-26
- Source: top100 · GitHub top 100 (new entry)

Agent skills that give coding agents taste: art direction, reference images and a browser check instead of generic AI pages

## Take

Uncle J has no skill for art direction when it generates web pages; ux-heuristics only checks usability after a page exists, and live-preview only shows each step as it's built.

It's a set of plain agent skills that give a coding agent design rules, reference images and a visual check, so generated pages look less like generic AI templates. Skills drop in without taking over the runtime, and they'd mainly help creativity on frontend work in William's projects. Pull only the skill files and leave the TasteCode desktop app alone.

Risk: The 'browser check' may depend on Playwright or a hosted service, which William rules out, and the README is mostly sponsor promotion, so read the skill files before adopting and strip out any Microsoft-dependent or online steps.

Scores: tokens 2/5, accuracy 2/5, creativity 4/5, offline 4/5
