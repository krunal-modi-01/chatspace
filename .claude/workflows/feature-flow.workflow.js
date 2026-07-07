export const meta = {
  name: 'feature-flow',
  description: 'Orchestrate a feature from frozen spec to verified, review-ready change with adversarial verification',
  phases: [
    { title: 'Design' },
    { title: 'Implement' },
    { title: 'Review' },
    { title: 'Verify' },
  ],
}

// `args` = {
//   specLink,                       // technical spec path
//   contractDoc, dbDesignDoc,       // frozen, human-approved specs (optional overrides)
//   tasks: [{ id, kind: 'backend'|'frontend'|'mobile'|'infra', desc }]
// }
// This script prepares a change for the 🔒 human review + deploy gates. It NEVER merges or deploys.

// The harness may deliver `args` as a JSON-encoded string; normalize to an object.
const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})

const specLink = A?.specLink ?? 'docs/spec/chatspace-v1-technical-spec.md'
const contractDoc = A?.contractDoc ?? 'docs/spec/chatspace-v1-api-contract.md'
const dbDesignDoc = A?.dbDesignDoc ?? 'docs/spec/chatspace-v1-database-design.md'
const tasks = A?.tasks ?? []

// Map task kind → canonical roster agent (see CLAUDE.md AGENT ROSTER).
const ENGINEER = {
  backend: 'backend-engineer',
  frontend: 'frontend-engineer',
  mobile: 'mobile-engineer',
  infra: 'infrastructure-engineer',
}

const taskList = tasks.map((t) => `- ${t.id} (${t.kind}): ${t.desc}`).join('\n')

// ── Design: extract the relevant slice from the FROZEN specs (do not re-derive) ──
phase('Design')
const [contract, dataModel] = await Promise.all([
  agent(
    `The frozen, human-approved API contract lives at ${contractDoc}. Do NOT redesign it. Read it and return — verbatim where possible — only the endpoints, request/response schemas, and error shapes relevant to these tasks:\n${taskList}`,
    { label: 'design:api', phase: 'Design', agentType: 'api-reviewer' }
  ),
  agent(
    `The frozen, human-approved database design lives at ${dbDesignDoc}. Do NOT redesign it. Read it and return the tables, columns, enums, indexes, constraints, and any migration notes relevant to these tasks:\n${taskList}`,
    { label: 'design:db', phase: 'Design', agentType: 'database-engineer' }
  ),
])

// ── Implement → Review → fix, pipelined per task (no batch barrier) ──
const results = await pipeline(
  tasks,
  // Stage 1: implement (isolated worktree so parallel tasks don't collide)
  (t) => agent(
    `Implement task ${t.id} — "${t.desc}" — per technical spec ${specLink}.\n` +
      `Conform EXACTLY to this frozen API contract slice:\n${contract}\n` +
      `and this frozen data model slice:\n${dataModel}\n` +
      `Write code + tests, then run lint/typecheck/tests. Honor CLAUDE.md conventions, boundaries, and security requirements.\n` +
      `\nITERATION BUDGET — this is a hard limit, obey it strictly:\n` +
      `- You get at most 5 fix→re-run attempts on failing lint/typecheck/tests. Count them.\n` +
      `- Before each fix, classify the failure: is it (a) YOUR code/tests, or (b) the ENVIRONMENT/harness ` +
      `(DB or Redis unreachable, missing migration, fixture/conftest setup, service not running, env var)?\n` +
      `- Fix category (a). Do NOT try to repair category (b): do not probe connectivity, spin up services, ` +
      `hand-run migrations, or debug the test harness in a loop. That is out of scope for this task.\n` +
      `- STOP as soon as EITHER your target tests pass OR you hit 5 attempts OR you hit a category (b) blocker. ` +
      `Never exceed the budget "just to get green".\n` +
      `\nReturn a short report: what you implemented (files changed), test status (pass / which fail), and — if you ` +
      `stopped short of green — a BLOCKED section naming the exact blocker (category b details, or the failing ` +
      `assertion) so a human can unblock it. A correct implementation with a clearly-reported blocker is SUCCESS, ` +
      `not failure. Do not keep working past the budget.`,
    { label: `impl:${t.id}`, phase: 'Implement', isolation: 'worktree', agentType: ENGINEER[t.kind] ?? 'backend-engineer' }
  ),
  // Stage 2: review the produced change
  (impl, t) => agent(
    `Review the change for task ${t.id} — "${t.desc}".\n` +
      `The Implement stage already ran lint/typecheck/tests. Here is its report (files changed, test status, ` +
      `any blocker):\n${impl}\n\n` +
      `Review the DIFF STATICALLY (git diff + the code it touches). Do NOT re-run the full lint/typecheck/test ` +
      `suite, and do NOT debug the test environment (DB/Redis connectivity, migrations, fixtures) — trust the ` +
      `reported status above; if it reports a blocker, factor that into your verdict instead of reproducing it. ` +
      `If a specific finding truly needs execution to confirm, run at most ONE targeted command for it.\n` +
      `Return findings as file:line · severity · concrete failure scenario · fix. Verdict: approve/request-changes.`,
    { label: `review:${t.id}`, phase: 'Review', agentType: 'code-reviewer' }
  ).then((review) => ({ task: t, impl, review })),
)

// ── Verify: security + a concrete-failure check, per task, in parallel ──
phase('Verify')
const verified = await parallel(results.filter(Boolean).map((r) => () =>
  agent(
    `Adversarially verify the change for task ${r.task.id} — "${r.task.desc}". Apply the security skill checklist (auth/input/secrets/IDOR/PII).\n` +
      `The Implement stage already ran the test suite. Its report:\n${r.impl}\n\n` +
      `Analyze the code STATICALLY for exploitable security issues. Do NOT re-run the full lint/typecheck/test ` +
      `suite or debug the test environment (DB/Redis connectivity, migrations) — that is not your job at this gate. ` +
      `If confirming a specific suspected vulnerability truly needs execution, run at most ONE targeted probe for it.\n` +
      `Report any HIGH/CRITICAL with an exploit path, else 'clean'.`,
    { label: `verify:${r.task.id}`, phase: 'Verify', agentType: 'security-reviewer' }
  ).then((security) => ({ ...r, security }))
))

return {
  contract, dataModel,
  tasks: verified.filter(Boolean),
  note: 'Prepared for 🔒 human review + deploy gates. No merge/deploy performed.',
}
