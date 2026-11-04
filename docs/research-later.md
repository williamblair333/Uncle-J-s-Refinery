# Research later

Topics Bill flagged to look into when there's room. Newest first. When one is researched,
move it to the bottom under **Done** with a one-line verdict and a link to the write-up.

- **Local 125B agent model, once the machine has 128 GB RAM** (added 2026-11-04). Shelved
  at 46 GB: the only 125B that fit was Strata's Qwen3.8-Flash-Next-GSQ-RCO **IQ1_M**. Under
  Claude Code it answered 0/5 bench tasks (context), and nobody has shown the ~40 t/s goal on a 12 GB card.
  The model to beat is Heretic (Qwen3.6-35B-A3B) under Pi: **15/40 vs agy's 31/40**,
  blind-judged on the same tasks (`/opt/docker/strata/bench/NOTES.md`, `run_pi.sh`).
  With 128 GB: an IQ3_S-or-better quant at 128k under Pi, uncensored via the refusal
  direction (`--cvec-mode project`). Bench it with `run_pi.sh` and keep it only if it clearly
  beats 15/40. Strata setup is kept (`/opt/docker/strata`, image `strata:0.2.9-src`); the
  IQ1_M weights were removed 2026-11-04. Scans: `review/alternatives/2026-11-03-strata-avalon.md`,
  `…-agent-harness.md`. **Trigger:** `scripts/ram_revisit.sh` prints a healthcheck warning
  (shown at every session start) once MemTotal is ≥ 120 GiB; silent below that.

- **Hallucination watcher for the digest** (added 2026-11-02). Reviewed:
  `review/2026-11-02-hallucination-watcher-review.md` (gitignored; referee pass). Interesting
  but premature: it guards a digest that doesn't exist yet. When the digest is built, start
  with deterministic claim checks (every number, name and URL in a summary must appear in the
  source) and add one small model (TinyLettuce or HHEM) only for the errors string checks can't
  see, measured on the digest's fixture week. Lynx 8B is CC-BY-NC-4.0.

- **vectorfall** (added 2026-10-31). Not yet looked at; first step is finding out what it is
  (library, product or paper) and whether it bears on the retrieval stack or memweave.

- **Manifold-Augmented Graph Embedding** (added 2026-10-31). Not yet looked at. Starting
  question: does it say anything useful for the retrieval stack (code/doc graph embeddings in
  jcodemunch/jdocmunch, memweave recall)?

## Done
