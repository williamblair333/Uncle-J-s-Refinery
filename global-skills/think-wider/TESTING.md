# think-wider — RED/GREEN record (2026-10-31)

Sonnet subagents, no tools, 3 planning scenarios × 2 reps + 1 known-cause bug fix × 2 (negative control).
S1 delegation failures 1-in-3 · S2 testing ruler changes in a noisy campaign · S3 assistant reacts instead of anticipating · S4 KeyError fix.

## Rubric
A transfer: names a DIFFERENT field/domain that solved a problem of the same shape AND states the mapping (their X = our Y, so do Z).
B outside view: names a reference class and a base rate/number (or says how to get one) before predicting success.
C first principles: states the irreducible constraint(s) / what must be true, and derives an option from that, not from current setup.
D hypotheses: marks new ideas as untested with a cheap test or kill criterion.

## RED (no skill)
S1r1: A0 B0 C0 D0 — single-domain ops plan (classify, fix biggest class, fallback). No other field, no base rate.
S1r2: A0 B0 C0 D0 — same shape as r1 (classify→fix deterministic→fallback). Break-even calc is in-domain, not a reference class.
S2r1: A0 B0 C½ D0 — strong in-domain plan (seeded RNG streams, paired seeds, old-vs-old noise floor, fixtures) = simulation-stats canon used implicitly; never names a source field or maps it, no base rate on "how often do ruler tweaks help".
S2r2: A0 B0 C½ D0 — near-identical to r1 (RNG streams, frozen snapshots, tiers, paired A/B). Convergent, in-domain.
S3r1: A0 B0 C½ D½ — rediscovers expert-bar (STANDARDS.md, seed from meta-questions, gap scan). Diagnosis "tools check work already chosen; nothing upstream" is first-principles-ish. Measures meta-q/week. No other field.
S3r2: A0 B0 C½ D0 — same as r1; self-states "won't make the assistant creative about genuinely novel risks".
TOTAL baseline: A 0/6, B 0/6, C ~2/6 (halves), D ~0.5/6. Failure type = omitted element -> structural contract with REQUIRED slots.

## GREEN (skill loaded)
S1r2: A1 B½ C1 D1 — manufacturing Pareto/FPY, logistics retries+fallback carrier, aviation "no fault found" audit -> false-fail audit. First principles: pre-flight allowlist. LOOPHOLE: outside view used own history as reference class, not an outside class.
S1r1: A1 B½ C1 D1 — manufacturing Pareto, clinical-lab false-negative vs gold standard, freight backup carrier; first-principles "shell-free job shapes". Reference class again = own log.
S2r1: A1 B1 C1 D1 — crop-breeding blocks, flight-test failure injection, clinical group-sequential stopping (NEW vs baseline); A/A as base rate.
S2r2: A1 B1 C1 D1 — clinical, crop breeding, sports-analytics shrinkage; A/A noise floor; injected event schedules.
S3r1: A1 B½ C1 D1 — hospital M&M, building code plan review, commander's intent; "pre-answer the meta-question". Base rate unknown, cheapest = count memweave.
S4r1,r2 (negative): both correctly skipped the skill, plain fix.
TOTAL green so far (5): A 5/5, B 3.5/5, C 5/5, D 5/5 vs baseline A0 B0 C~.3 D~.1.
REFACTOR: reference class must be OUTSIDE the project (own log = inside view); add to contract + common mistakes.
S3r2: A1 B½ C1 D1 — aviation checklists, medicine can't-miss list + time-out, Toyota 5-whys/poka-yoke; forecast-next-questions. FINAL green: A6/6 B4/6 C6/6 D6/6; negatives 2/2 skipped.

Refactor after GREEN: reference class must be outside the project (own log = inside view).

## Build step (2026-10-31, second round)

Two problems with no ready-made analogy: S5 forget-at-will memory, S6 local 9B review matching the cloud model.

E synthesis: names the contradiction blocking the obvious answer, splits the problem into functions, takes mechanisms from >=2 different fields, and COMPOSES them into one named design no single field has (not a list of separate analogies).
F honesty: says plainly whether a full solution exists; if not, names the constraint that blocks it and what part is solvable.

S6 RED: E½ F1 — analogies become pipeline steps (a de facto composition), but no named contradiction, no explicit composition step; honest 'straight answer' on parity.
S5 RED: E1 F1 — composed a named 5-step design from intelligence compartments + food-recall lot genealogy + court sealing, contradiction from first principles (bytes stay => 'forget' = no key); honest limit stated. => current skill ALREADY composes when partial transfers exist. Only gap: skill text lets 'say none applied' end the search.
S6 GREEN: E1 F1 — named contradiction (too shallow vs unlimited passes), jobs->mechanisms (manufacturing recall, drug-discovery orthogonal assay precision, radiology residue), composed 'Screen-and-Confirm', honest limit.

Change: the 'say none applied' escape hatch became a build step (contradiction → jobs → one mechanism per job → composed design) plus an honest stop (blocking constraint + largest solvable part).
