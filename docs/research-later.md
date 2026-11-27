# Research later

Topics William flagged to look into when there's room. Newest first. When one is researched,
move it to the bottom under **Done** with a one-line verdict and a link to the write-up.

- **A chat room for all the LLM sessions** (added 2026-11-19). William wants
  Claude sessions (Uncle J, write-well, the project sessions), agy, Heretic and
  other models to talk in one room when he asks them to. Today, `SendMessage`
  connects local Claude sessions in pairs. agy and Heretic are outside those
  conversations, and there's no shared transcript. Could an existing multi-agent
  chat tool fit, such as an MCP server or a Matrix or IRC room with bots? Or is
  a simple room built on the delegate server enough? Decide who gets to speak
  and how to stop the models from replying to each other forever.

- **Local 125B agent model, once the machine has 128 GB RAM** (added 2026-11-04). Shelved
  at 46 GB. The only 125B model that fit was Strata's Qwen3.8-Flash-Next-GSQ-RCO **IQ1_M**.
  Under Claude Code it answered 0/5 bench tasks (context). Nobody has shown
  that it can hit the ~40 t/s goal on a 12 GB card.
  The model to beat is Heretic (Qwen3.6-35B-A3B) under Pi. It scored
  **15/40 vs agy's 31/40** on the same tasks. The judges scored the answers
  without knowing which model produced them (`/opt/docker/strata/bench/NOTES.md`, `run_pi.sh`).
  With 128 GB: an IQ3_S-or-better quant at 128k under Pi, uncensored via the refusal
  direction (`--cvec-mode project`). Test it with `run_pi.sh` and keep it only if it clearly
  beats 15/40. The Strata setup is still in place (`/opt/docker/strata`, image
  `strata:0.2.9-src`). The IQ1_M weights were removed 2026-11-04.
  Earlier scans are in `review/alternatives/2026-11-03-strata-avalon.md` and
  `…-agent-harness.md`. **Trigger:** `scripts/ram_revisit.sh` prints a healthcheck
  warning, shown at each session start, once MemTotal is ≥ 120 GiB. Below that it
  stays quiet.

- **Hallucination watcher for the digest** (added 2026-11-02). The referee (a
  second-opinion review by a different model) reviewed it in
  `review/2026-11-02-hallucination-watcher-review.md` (gitignored). Wait until
  the digest exists. Start with exact string checks that use no model. Every
  number, name, and URL in a summary must appear in the source. Use the digest's
  fixture week, a set of sample inputs, to measure the errors those checks miss.
  Add one small model (TinyLettuce or HHEM) to catch only those errors. Lynx 8B
  is CC-BY-NC-4.0.

- **vectorfall** (added 2026-10-31). Still to review. Find out whether
  vectorfall is a library, product, or paper. Then check whether it could
  help the tools that find relevant material, including memweave.

- **Manifold-Augmented Graph Embedding** (added 2026-10-31). Still to
  review. Could it help jcodemunch or jdocmunch find relevant code and docs
  by looking at how they connect? Could it help memweave recall relevant material?

## Done
