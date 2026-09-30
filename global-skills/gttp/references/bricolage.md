# Bricolage levers

Read on the gttp Improvise route, in any domain. These levers generate
candidates. They don't choose among them: every candidate still goes through
the Step 4 kill-test and the Step 5 ranking in SKILL.md. The Hard-limit route
still overrides everything here.

Improvising means reaching the goal by another route when the obvious one is
blocked: a part that doesn't exist, a missing API or library, a feature the
vendor won't add. The domain doesn't matter. What matters is the move from
"the right thing isn't available" to "what else can do this job".

## 1. Name the function, not the missing thing

The missing thing is a means. State what it had to *do*.

| Stated as the missing thing | Stated as the function |
|---|---|
| "There's no handle for this spigot" | Apply torque to a 1/4 in square stem |
| "The API has no bulk export" | Get every record out once, complete and in a parseable form |
| "No library parses this format" | Turn these bytes into structured fields I can query |
| "The app can't schedule this" | Make X happen at time T without me |

## 2. Break functional fixedness

Describe each thing you have by what it *is*, not by what it's labelled for.
If you keep using the label, you're still fixed on it.

- A PVC cap is a rigid dome of a given ID. A brass nut is a threaded plug.
- A CSV or report export is a read API. So is a paginated UI list, if you
  script it.
- A cron job plus a diff is a webhook. A git repo is a versioned key-value
  store. An email inbox is a queue.
- A tool that already opens a format is a parser for it, even if it has no
  parsing API: convert, print, or export through it.
- A test fixture, a cache, or a backup may already hold the data a missing
  endpoint would have served.

## 3. Borrow from another domain

Ask where else this function gets solved. Combine two things that weren't
meant to meet.

- Seal a hole of the wrong shape → dentistry, electronics potting, casting.
- Get data out of a system with no export → scraping, screen readers, print
  to file, the vendor's own sync or migration tool, a support data-export request.
- Parse an undocumented format → the reverse-engineering habits of file-format
  archivists: find a sample with known content and diff the bytes.
- Coordinate with no scheduler → a shared file or row used as a lock, a
  calendar invite used as a trigger.

## 4. Use what's on hand

Build from the parts, tools, data, scripts, accounts, and access you already
have before acquiring anything. Read the user's inventory note if one exists
(SKILL.md Step 6). It lists physical stock and non-physical resources.

## 5. Satisfice

Define the real bar first: holds X, survives Y, reversible if Z, complete to
N records. Stop generating once a candidate clears it. The ranking and the
"do nothing" comparison happen in Steps 4–5, not here.

## Guardrails

- **Check that the repurposed property is real, not hoped for.** Epoxy won't
  bond what it can't bond. An export may silently drop fields or cap rows. An
  undocumented endpoint may change without notice. Name how you'd verify it.
- **Work around missing capability, never around access controls.** Don't
  bypass authentication, rate limits meant as limits, paywalls, DRM, licence
  terms, or terms of service, and don't use credentials or access that aren't
  the user's to use. If the block is a permission, the route is to ask for it:
  the vendor, the admin, or a data-export request. Hacking in the
  Stallman sense is clever use of what you're allowed to touch. It isn't
  breaking in.
- **Prefer reversible improvisations** while the mechanism is uncertain: a
  script over a schema change, a clamp over a bond.
