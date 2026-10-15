export const meta = {
  name: 'adversarial-review',
  description: 'Adversarial multi-agent code review — 4 hostile-but-fair reviewer personas debate findings across two rounds until only real problems survive',
  whenToUse: 'When you need a rigorous multi-perspective code review. Pass args as a string describing the target: "current git diff", "PR #42", "files: src/foo.py src/bar.py", or raw diff/code text.',
  phases: [
    { title: 'Independent Review', detail: '4 adversarial personas review independently in parallel' },
    { title: 'Cross-Attack', detail: 'Each reviewer attacks the others — refute, amplify, or surface new findings' },
    { title: 'Verdict', detail: 'Judge synthesizes: confirmed vs refuted, final ship/fix/rework decision' },
  ],
}

// ── Target ────────────────────────────────────────────────────────────────────
const target = args || 'the current git diff — run: git diff HEAD (or git diff $(git merge-base HEAD main)..HEAD for branch diff)'

// ── Personas ──────────────────────────────────────────────────────────────────
const PERSONAS = [
  {
    name: 'Paranoid',
    lens: 'security',
    voice: `You are a paranoid security reviewer. You assume every input is hostile.
Every permission is over-scoped. Every external call is a liability. Every
credential is a leak waiting to happen. You are not trying to make friends.
You are trying to find holes before attackers do.`,
    focus: `injection (SQL, shell, path traversal), auth bypass, privilege escalation,
SSRF, insecure deserialization, hardcoded secrets, over-broad permissions,
trust boundary violations, data exposure in logs/errors, supply chain risk`,
  },
  {
    name: 'Archaeologist',
    lens: 'coupling and hidden complexity',
    voice: `You are a code archaeologist. The real bug is never where you are looking —
it is five files away, in the assumption this code makes about its caller, in the
side effect nobody documented. You trace consequences. You distrust magic. You find
the load-bearing code that will silently break when someone touches anything nearby.`,
    focus: `hidden coupling, undocumented invariants, fragile caller assumptions,
cross-module side effects, functions that break their callers, stale comments
that contradict code, missing deprecation paths, implicit ordering dependencies`,
  },
  {
    name: 'Pedant',
    lens: 'correctness',
    voice: `You are a correctness absolutist. "This should not happen" is not an
acceptable error strategy — you accept error handling. Every edge case must be
handled or explicitly rejected. Where is the null check? What happens on empty
input? What happens at the exact boundary? You find the test that is missing.`,
    focus: `off-by-one errors, null/undefined/empty/zero boundary conditions,
unhandled exceptions, incorrect error propagation, missing validation,
race conditions, integer overflow/underflow, wrong operator precedence,
mutating inputs the caller still holds`,
  },
  {
    name: 'Cynic',
    lens: 'efficiency and simplicity',
    voice: `You are a performance cynic. Every abstraction is guilty until proven
innocent. You count allocations. You know what O(n²) looks like when it is hidden
inside a helper. You have seen "clean code" melt production. You want benchmarks,
not intentions. Simple is correct; clever is a liability.`,
    focus: `algorithmic complexity hidden in helpers, unnecessary allocations,
N+1 queries, premature abstraction, over-engineering, dead code, redundant
recomputation, blocking calls in async contexts, lock contention`,
  },
]

// ── Schemas ───────────────────────────────────────────────────────────────────
const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['reviewer', 'findings'],
  properties: {
    reviewer: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'severity', 'location', 'claim', 'evidence'],
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'nit'] },
          location: { type: 'string' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
  },
}

const ATTACK_SCHEMA = {
  type: 'object',
  required: ['reviewer', 'attacks', 'new_findings'],
  properties: {
    reviewer: { type: 'string' },
    attacks: {
      type: 'array',
      items: {
        type: 'object',
        required: ['target_id', 'verdict', 'argument'],
        properties: {
          target_id: { type: 'string' },
          verdict: { type: 'string', enum: ['refuted', 'overstated', 'confirmed', 'amplified'] },
          argument: { type: 'string' },
        },
      },
    },
    new_findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'severity', 'claim', 'evidence'],
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'nit'] },
          location: { type: 'string' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['executive_summary', 'confirmed_findings', 'refuted_findings', 'verdict'],
  properties: {
    executive_summary: { type: 'string' },
    confirmed_findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'severity', 'claim', 'attack_record', 'recommendation'],
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low', 'nit'] },
          claim: { type: 'string' },
          attack_record: { type: 'string' },
          recommendation: { type: 'string' },
        },
      },
    },
    refuted_findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'claim', 'killed_by'],
        properties: {
          id: { type: 'string' },
          claim: { type: 'string' },
          killed_by: { type: 'string' },
        },
      },
    },
    verdict: { type: 'string', enum: ['ship_it', 'fix_before_merge', 'needs_major_rework'] },
  },
}

// ── Phase 1: Independent Review ───────────────────────────────────────────────
phase('Independent Review')
log(`Target: ${String(target).slice(0, 120)}`)

const reviews = await parallel(PERSONAS.map(p => () =>
  agent(
    `You are ${p.name}, an adversarial code reviewer. Your lens: **${p.lens}**.

CHARACTER:
${p.voice}

FOCUS AREAS (stay in your lane — do not try to cover everything):
${p.focus}

TARGET:
${String(target)}

INSTRUCTIONS:
1. Fetch the actual code first. If the target says "git diff", run: Bash("git diff HEAD") or
   Bash("git diff $(git merge-base HEAD origin/main)..HEAD"). If it names files, read them.
   If it names a PR number, run: Bash("gh pr diff <number>"). If it is already code/diff, use it.
2. Review ONLY through your lens. Be ruthless and specific — no vague concerns.
3. Every finding needs: exact location (file:line), a falsifiable claim, and evidence from the code.
4. Do NOT soften findings. Do NOT add "however" clauses. You are not writing a performance review.
5. Severity: critical=exploitable/data-loss, high=likely prod bug, medium=should fix, low=worth noting, nit=minor.
6. Use finding IDs: ${p.name.toUpperCase()}-1, ${p.name.toUpperCase()}-2, etc.

Return reviewer="${p.name}".`,
    { label: `review:${p.name}`, phase: 'Independent Review', schema: FINDINGS_SCHEMA }
  )
))

const validReviews = reviews.filter(Boolean)
const allFindings = validReviews.flatMap(r => r.findings || [])
log(`Round 1: ${allFindings.length} findings from ${validReviews.length} reviewers`)

if (allFindings.length === 0) {
  log('No findings in Round 1 — code may be clean, or target could not be fetched. Returning early.')
  return { rounds: { review: validReviews, attacks: [] }, verdict: null }
}

// ── Phase 2: Cross-Attack ─────────────────────────────────────────────────────
phase('Cross-Attack')
log('Reviewers now reading each other\'s work...')

const attacks = await parallel(PERSONAS.map((p, i) => () => {
  const myReview = validReviews.find(r => r.reviewer === p.name)
  if (!myReview) return Promise.resolve(null)

  const othersFindings = validReviews
    .filter(r => r.reviewer !== p.name)
    .map(r => `\n=== ${r.reviewer.toUpperCase()} FINDINGS ===\n${r.findings.map(f =>
      `[${f.id}] ${f.severity.toUpperCase()} @ ${f.location}: ${f.claim}\nEvidence: ${f.evidence}`
    ).join('\n\n')}`)
    .join('\n')

  return agent(
    `You are ${p.name}. You have read your colleagues' findings. You do not trust them.

CHARACTER:
${p.voice}

YOUR JOB — two tasks:
1. ATTACK every finding from the other reviewers. Be specific and technical.
   - "refuted" = not actually a problem; give the technical reason
   - "overstated" = real problem but wrong severity; state the real severity
   - "confirmed" = you reluctantly agree (use sparingly — you are hostile)
   - "amplified" = it is worse than they said; explain exactly how much worse
   Every attack must name the finding ID and give a specific technical argument.
   "I disagree" is not an argument. "The evidence doesn't support this because X" is.

2. Find NEW findings your colleagues MISSED. What did their lenses leave blind?
   Use IDs: ${p.name.toUpperCase()}-R2-1, ${p.name.toUpperCase()}-R2-2, etc.

OTHER REVIEWERS' FINDINGS:
${othersFindings}

Return reviewer="${p.name}".`,
    { label: `attack:${p.name}`, phase: 'Cross-Attack', schema: ATTACK_SCHEMA }
  )
}))

const validAttacks = attacks.filter(Boolean)
const newR2Findings = validAttacks.flatMap(a => a.new_findings || [])
log(`Round 2: ${validAttacks.length} attack reports, ${newR2Findings.length} new findings surfaced`)

// ── Phase 3: Verdict ──────────────────────────────────────────────────────────
phase('Verdict')

const allFindingsSummary = [
  '=== ROUND 1 FINDINGS ===',
  ...allFindings.map(f =>
    `[${f.id}] ${f.severity.toUpperCase()} @ ${f.location || '?'}: ${f.claim}\nEvidence: ${f.evidence}`
  ),
  '\n=== ROUND 2 ATTACKS ===',
  ...validAttacks.flatMap(a => [
    `\n-- ${a.reviewer.toUpperCase()} ATTACKS --`,
    ...(a.attacks || []).map(atk =>
      `  → [${atk.target_id}]: ${atk.verdict.toUpperCase()} — ${atk.argument}`
    ),
  ]),
  '\n=== NEW FINDINGS FROM ROUND 2 ===',
  ...newR2Findings.map(f =>
    `[${f.id}] ${f.severity.toUpperCase()} @ ${f.location || '?'}: ${f.claim}\nEvidence: ${f.evidence}`
  ),
].join('\n')

const verdict = await agent(
  `You are the judge in an adversarial code review. Four hostile reviewers debated this code.
Your job: synthesize the battle into a final verdict.

RULES:
- A finding SURVIVES if it was not successfully refuted, or if it was confirmed/amplified.
- A finding is REFUTED only if a reviewer gave a specific technical counter that was not itself
  refuted. "I disagree" doesn't kill a finding — a technical argument does.
- Findings confirmed or amplified by any reviewer get elevated credibility.
- New Round-2 findings that were not challenged are tentatively confirmed (no defense was mounted).
- Use the HIGHEST severity assigned across the debate for each surviving finding.
- Be honest about what the debate resolved vs. what remains genuinely uncertain.

OUTPUT:
- executive_summary: 2-3 sentence plain-English summary for a PR description
- confirmed_findings: findings that survived, with attack_record (brief history) and recommendation
- refuted_findings: findings that were killed, with what killed them
- verdict: ship_it | fix_before_merge | needs_major_rework

THE DEBATE:
${allFindingsSummary}`,
  { label: 'judge', phase: 'Verdict', schema: VERDICT_SCHEMA }
)

if (verdict) {
  const crit = verdict.confirmed_findings.filter(f => f.severity === 'critical').length
  const high = verdict.confirmed_findings.filter(f => f.severity === 'high').length
  log(`VERDICT: ${verdict.verdict.toUpperCase()} | ${crit} critical · ${high} high · ${verdict.confirmed_findings.length} total confirmed | ${verdict.refuted_findings.length} refuted`)
}

return { rounds: { review: validReviews, attacks: validAttacks }, verdict }
